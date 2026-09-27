#define _GNU_SOURCE
#include "capture_internal.h"
#include <fcntl.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#ifdef PT_TEST_FAKE
#include "fake_v4l2.h"
#else
#include <linux/videodev2.h>
#include <sys/sysmacros.h>
#endif

typedef struct { void *address; uint32_t length, offset; bool mapped, queued; } video_map;
typedef struct {
    int fd; bool requested, started, stream_attempted, failed, have_sequence, have_timestamp;
    pt_video_config config; pt_video_actual actual;
    video_map maps[PT_MAX_BUFFERS];
    uint32_t count, previous_sequence, timestamp_flags;
    int64_t last_host_ns;
} video_handle;
/* ioctl EINTR returns to the caller: no unbounded configuration retry. */
static int video_destroy(video_handle *h) {
    if (!h) return 0;
    int first=0;
    if (h->fd >= 0) {
        if (h->stream_attempted) {
            enum v4l2_buf_type type=V4L2_BUF_TYPE_VIDEO_CAPTURE;
            if (ioctl(h->fd,VIDIOC_STREAMOFF,&type)<0) first=errno;
        }
        for (uint32_t i=0;i<h->count;i++) if (h->maps[i].mapped)
            if (munmap(h->maps[i].address,h->maps[i].length)<0 && !first) first=errno;
        if (h->requested) {
            struct v4l2_requestbuffers request={.count=0,.type=V4L2_BUF_TYPE_VIDEO_CAPTURE,.memory=V4L2_MEMORY_MMAP};
            if (ioctl(h->fd,VIDIOC_REQBUFS,&request)<0 && !first) first=errno;
        }
        if (close(h->fd)<0 && !first) first=errno;
    }
    free(h); return first;
}
static int identity_equal(const char *expected, const uint8_t *actual, size_t size) {
    return pt_literal(expected,size) && memchr(actual,0,size) && !strcmp(expected,(const char *)actual);
}
int32_t pt_v4l2_open(const pt_video_config *c, void **out, pt_video_actual *actual, pt_error *e) {
    pt_clear_error(e); if (out) *out=NULL; if (actual) PT_INIT(actual);
    if (!out || !actual || !PT_HEADER(c) || c->video_index>65535 || !c->width || !c->height || (c->width&1u) ||
        (uint64_t)c->width*c->height>PT_MAX_PIXELS || !c->buffer_count || c->buffer_count>PT_MAX_BUFFERS ||
        !c->max_buffer_bytes || c->max_buffer_bytes>PT_MAX_CHUNK || !c->max_mapped_bytes ||
        c->max_mapped_bytes>PT_MAX_BUFFERS*PT_MAX_CHUNK || !c->max_chunk_bytes || c->max_chunk_bytes>PT_MAX_CHUNK ||
        (uint64_t)c->width*c->height*2>c->max_chunk_bytes ||
        (!!c->cadence_numerator != !!c->cadence_denominator) ||
        !pt_literal(c->expected_driver,sizeof(c->expected_driver)) || !pt_literal(c->expected_card,sizeof(c->expected_card)) ||
        !pt_literal(c->expected_bus_info,sizeof(c->expected_bus_info))) return pt_fail(e,PT_DOMAIN_CONTRACT,EINVAL);
    video_handle *h=calloc(1,sizeof(*h));
    if (!h) return pt_fail(e,PT_DOMAIN_ERRNO,ENOMEM);
    h->fd=-1; h->config=*c;
    int saved=0; uint32_t domain=PT_DOMAIN_ERRNO;
    char node[64];
    int n=snprintf(node,sizeof(node),"/dev/video%u",c->video_index);
    if (n<0 || (size_t)n>=sizeof(node)) { saved=EINVAL; domain=PT_DOMAIN_CONTRACT; goto fail; }
    h->fd=open(node,O_RDWR|O_NONBLOCK|O_CLOEXEC|O_NOFOLLOW);
    if (h->fd<0) { saved=errno; goto fail; }
    struct stat st;
    if (fstat(h->fd,&st)<0) { saved=errno; goto fail; }
    if (!S_ISCHR(st.st_mode) || major(st.st_rdev)!=81 || minor(st.st_rdev)!=c->video_index) { saved=ENODEV; goto fail; }
#define IO(call) do { if ((call)<0) { saved=errno; goto fail; } } while (0)
#define REQUIRE(test) do { if (!(test)) { saved=EINVAL; domain=PT_DOMAIN_CONTRACT; goto fail; } } while (0)
    struct v4l2_capability caps={0};
    IO(ioctl(h->fd,VIDIOC_QUERYCAP,&caps));
    uint32_t features=(caps.capabilities&V4L2_CAP_DEVICE_CAPS)?caps.device_caps:caps.capabilities;
    REQUIRE((features&V4L2_CAP_VIDEO_CAPTURE) && (features&V4L2_CAP_STREAMING));
    REQUIRE(identity_equal(c->expected_driver,caps.driver,sizeof(caps.driver)) &&
            identity_equal(c->expected_card,caps.card,sizeof(caps.card)) &&
            identity_equal(c->expected_bus_info,caps.bus_info,sizeof(caps.bus_info)));
    struct v4l2_format format={.type=V4L2_BUF_TYPE_VIDEO_CAPTURE};
    format.fmt.pix.width=c->width; format.fmt.pix.height=c->height;
    format.fmt.pix.pixelformat=V4L2_PIX_FMT_YUYV; format.fmt.pix.field=V4L2_FIELD_NONE;
    IO(ioctl(h->fd,VIDIOC_S_FMT,&format));
    struct v4l2_pix_format *p=&format.fmt.pix;
    uint64_t required=(uint64_t)(c->height-1)*p->bytesperline+(uint64_t)c->width*2;
    REQUIRE(format.type==V4L2_BUF_TYPE_VIDEO_CAPTURE && p->width==c->width && p->height==c->height &&
            p->pixelformat==V4L2_PIX_FMT_YUYV && p->field==V4L2_FIELD_NONE &&
            p->bytesperline>=(uint64_t)c->width*2 && required<=p->sizeimage &&
            p->sizeimage<=c->max_buffer_bytes);
    actual->width=p->width; actual->height=p->height; actual->bytesperline=p->bytesperline; actual->sizeimage=p->sizeimage;
    actual->colorspace=p->colorspace; actual->ycbcr_enc=p->ycbcr_enc;
    actual->quantization=p->quantization; actual->xfer_func=p->xfer_func;
    memcpy(actual->driver,caps.driver,sizeof(actual->driver)); memcpy(actual->card,caps.card,sizeof(actual->card));
    memcpy(actual->bus_info,caps.bus_info,sizeof(actual->bus_info));
    if (c->cadence_numerator) {
        struct v4l2_streamparm parm={.type=V4L2_BUF_TYPE_VIDEO_CAPTURE};
        IO(ioctl(h->fd,VIDIOC_G_PARM,&parm));
        REQUIRE(parm.type==V4L2_BUF_TYPE_VIDEO_CAPTURE && (parm.parm.capture.capability&V4L2_CAP_TIMEPERFRAME));
        memset(&parm,0,sizeof(parm)); parm.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;
        parm.parm.capture.timeperframe.numerator=c->cadence_numerator;
        parm.parm.capture.timeperframe.denominator=c->cadence_denominator;
        IO(ioctl(h->fd,VIDIOC_S_PARM,&parm));
        REQUIRE(parm.type==V4L2_BUF_TYPE_VIDEO_CAPTURE && parm.parm.capture.timeperframe.numerator && parm.parm.capture.timeperframe.denominator &&
                (uint64_t)parm.parm.capture.timeperframe.numerator*c->cadence_denominator ==
                (uint64_t)c->cadence_numerator*parm.parm.capture.timeperframe.denominator);
        actual->cadence_numerator=parm.parm.capture.timeperframe.numerator;
        actual->cadence_denominator=parm.parm.capture.timeperframe.denominator; actual->cadence_valid=1;
    }
    struct v4l2_requestbuffers request={.count=c->buffer_count,.type=V4L2_BUF_TYPE_VIDEO_CAPTURE,.memory=V4L2_MEMORY_MMAP};
    h->requested=true;
    IO(ioctl(h->fd,VIDIOC_REQBUFS,&request));
    REQUIRE(request.count && request.count<=c->buffer_count && request.count<=PT_MAX_BUFFERS &&
            request.type==V4L2_BUF_TYPE_VIDEO_CAPTURE && request.memory==V4L2_MEMORY_MMAP);
    h->count=request.count;
    uint64_t total=0;
    for (uint32_t i=0;i<h->count;i++) {
        struct v4l2_buffer b={.type=V4L2_BUF_TYPE_VIDEO_CAPTURE,.memory=V4L2_MEMORY_MMAP,.index=i};
        IO(ioctl(h->fd,VIDIOC_QUERYBUF,&b));
        REQUIRE(b.index==i && b.type==V4L2_BUF_TYPE_VIDEO_CAPTURE && b.memory==V4L2_MEMORY_MMAP &&
                b.length>=p->sizeimage && b.length<=c->max_buffer_bytes && total+b.length<=c->max_mapped_bytes);
        for (uint32_t j=0;j<i;j++)
            REQUIRE((uint64_t)b.m.offset+b.length<=h->maps[j].offset ||
                    (uint64_t)h->maps[j].offset+h->maps[j].length<=b.m.offset);
        h->maps[i].length=b.length; h->maps[i].offset=b.m.offset;
        h->maps[i].address=mmap(NULL,b.length,PROT_READ|PROT_WRITE,MAP_SHARED,h->fd,(off_t)b.m.offset);
        if (h->maps[i].address==MAP_FAILED) { saved=errno; goto fail; }
        h->maps[i].mapped=true; total+=b.length;
        IO(ioctl(h->fd,VIDIOC_QBUF,&b)); h->maps[i].queued=true;
    }
    actual->buffer_count=h->count; actual->mapped_bytes=(uint32_t)total; h->actual=*actual;
    *out=h; return PT_OK;
fail:
    video_destroy(h); PT_INIT(actual); return pt_fail(e,domain,saved);
#undef IO
#undef REQUIRE
}
int32_t pt_v4l2_start(void *handle, pt_error *e) {
    video_handle *h=handle; pt_clear_error(e);
    if (!h || h->started || h->failed) return pt_fail(e,PT_DOMAIN_CONTRACT,EINVAL);
    enum v4l2_buf_type type=V4L2_BUF_TYPE_VIDEO_CAPTURE;
    h->stream_attempted=true;
    if (ioctl(h->fd,VIDIOC_STREAMON,&type)<0) { h->failed=true; return pt_fail(e,PT_DOMAIN_ERRNO,errno); }
    h->started=true; return PT_OK;
}
int32_t pt_v4l2_poll_copy(void *handle, uint8_t *dst, uint32_t capacity, int32_t cancel_fd,
                         uint32_t timeout_ms, pt_video_record *r, pt_error *e) {
    video_handle *h=handle; pt_clear_error(e); if (r) PT_INIT(r);
    if (!h || !r || !dst || !h->started || h->failed || cancel_fd<0 || !timeout_ms || timeout_ms>60000 ||
        capacity<(uint64_t)h->config.width*h->config.height*2 || capacity>PT_MAX_CHUNK)
        return pt_fail(e,PT_DOMAIN_CONTRACT,EINVAL);
    int64_t before=pt_now();
    if (before<0) { h->failed=true; return pt_fail(e,PT_DOMAIN_ERRNO,errno); }
    if (before<h->last_host_ns) { h->failed=true; return pt_fail(e,PT_DOMAIN_CONTRACT,EIO); }
    int64_t deadline, last_seen=before;
    if (pt_make_deadline(before,timeout_ms,&deadline,e)!=PT_OK) { h->failed=true; return PT_FAULT; }
    struct pollfd fds[2]={{.fd=h->fd,.events=POLLIN},{0}};
    for (;;) {
        int32_t status=pt_wait(fds,1,cancel_fd,&last_seen,deadline,e);
        if (status!=PT_OK) { h->last_host_ns=last_seen; if (status==PT_FAULT) h->failed=true; return status; }
        if (fds[0].revents&(POLLERR|POLLHUP|POLLNVAL)) { h->failed=true; return pt_fail(e,PT_DOMAIN_ERRNO,EIO); }
        if (!(fds[0].revents&POLLIN)) continue;
        struct v4l2_buffer b={.type=V4L2_BUF_TYPE_VIDEO_CAPTURE,.memory=V4L2_MEMORY_MMAP};
        if (ioctl(h->fd,VIDIOC_DQBUF,&b)<0) {
            if (errno==EAGAIN || errno==EINTR) continue;
            h->failed=true; return pt_fail(e,PT_DOMAIN_ERRNO,errno);
        }
        /* On ambiguous index/ownership never QBUF an untrusted index. */
        if (b.index>=h->count || !h->maps[b.index].queued) goto invalid;
        h->maps[b.index].queued=false;
        video_map *m=&h->maps[b.index];
        uint32_t domain=b.flags&V4L2_BUF_FLAG_TIMESTAMP_MASK;
        uint32_t source=b.flags&V4L2_BUF_FLAG_TSTAMP_SRC_MASK;
        if (b.type!=V4L2_BUF_TYPE_VIDEO_CAPTURE || b.memory!=V4L2_MEMORY_MMAP ||
            b.field!=V4L2_FIELD_NONE || (b.flags&V4L2_BUF_FLAG_ERROR) || b.length!=m->length ||
            b.bytesused>h->actual.sizeimage || b.timestamp.tv_sec<0 || b.timestamp.tv_usec<0 || b.timestamp.tv_usec>=1000000 ||
            (domain!=V4L2_BUF_FLAG_TIMESTAMP_UNKNOWN && domain!=V4L2_BUF_FLAG_TIMESTAMP_MONOTONIC) ||
            (source!=V4L2_BUF_FLAG_TSTAMP_SRC_EOF && source!=V4L2_BUF_FLAG_TSTAMP_SRC_SOE)) goto invalid;
        if (h->have_sequence && b.sequence!=(uint32_t)(h->previous_sequence+1u)) goto discontinuity;
        if (h->have_timestamp && h->timestamp_flags!=(domain|source)) goto discontinuity;
        /* Both active rows and the metadata that explains removed padding precede QBUF. */
        if (pt_copy_yuyv(m->address,m->length,b.bytesused,h->config.width,h->config.height,
                         h->actual.bytesperline,dst,capacity,&r->bytes)!=PT_OK) goto invalid;
        r->sequence=b.sequence; r->raw_flags=b.flags; r->field=b.field;
        r->timestamp_domain_flags=domain; r->timestamp_source_flags=source;
        r->timestamp_sec=b.timestamp.tv_sec; r->timestamp_usec=b.timestamp.tv_usec;
        r->bytesused=b.bytesused; r->mapped_length=m->length; r->bytesperline=h->actual.bytesperline;
        r->sizeimage=h->actual.sizeimage; r->padding_removed=(r->bytes!=b.bytesused || r->bytesperline!=h->config.width*2);
        r->sequence_wrapped=h->have_sequence && h->previous_sequence==UINT32_MAX && b.sequence==0;
        r->host_before_ns=before; r->host_after_ns=pt_now();
        if (r->host_after_ns<last_seen) goto invalid;
        h->last_host_ns=r->host_after_ns;
        r->valid=PT_VALID_VIDEO_STAMP|PT_VALID_HOST;
        if (ioctl(h->fd,VIDIOC_QBUF,&b)<0) { int saved=errno; h->failed=true; PT_INIT(r); return pt_fail(e,PT_DOMAIN_ERRNO,saved); }
        m->queued=true; h->previous_sequence=r->sequence; h->have_sequence=true;
        h->timestamp_flags=domain|source; h->have_timestamp=true;
        return PT_OK;
    }
discontinuity:
    h->failed=true; PT_INIT(r); return pt_fail(e,PT_DOMAIN_CONTRACT,ESTALE);
invalid:
    h->failed=true; PT_INIT(r); return pt_fail(e,PT_DOMAIN_CONTRACT,EIO);
}
int32_t pt_v4l2_stop_close(void *handle, pt_error *e) {
    pt_clear_error(e); int rc=video_destroy(handle);
    return rc ? pt_fail(e,PT_DOMAIN_ERRNO,rc) : PT_OK;
}
