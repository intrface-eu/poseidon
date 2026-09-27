/* All calls from real algorithms terminate here, never at devices or Linux. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include "fake_system.h"
#include "fake_v4l2.h"
uint32_t pt_test_mode,pt_test_poll_count,pt_test_closes,pt_test_maps,pt_test_unmaps;
uint32_t pt_test_streamoffs,pt_test_releases,pt_test_audio_closes,pt_test_drops;
static uint32_t ticks,video_index,queue_count,sequence,dequeues;
static int streaming;
static uint8_t *maps[8];
void pt_test_reset(uint32_t mode) {
    pt_test_mode=mode;pt_test_poll_count=pt_test_closes=pt_test_maps=pt_test_unmaps=0;
    pt_test_streamoffs=pt_test_releases=pt_test_audio_closes=pt_test_drops=0;
    ticks=queue_count=sequence=dequeues=0;streaming=0;
    memset(maps,0,sizeof(maps));
}
uint32_t pt_test_counter(uint32_t index) {
    const uint32_t values[]={pt_test_poll_count,pt_test_closes,pt_test_maps,pt_test_unmaps,pt_test_streamoffs,pt_test_releases,pt_test_audio_closes,pt_test_drops,queue_count};
    return index<sizeof(values)/sizeof(values[0])?values[index]:UINT32_MAX;
}
int pt_test_clock_gettime(clockid_t clock,struct timespec *t) {
    if(clock!=CLOCK_MONOTONIC){errno=EINVAL;return -1;}
    ticks++;t->tv_sec=1+ticks/1000;t->tv_nsec=(long)(ticks%1000)*1000000;
    if(pt_test_mode==40)t->tv_nsec=1000000000;
    if(pt_test_mode==41)t->tv_sec=(time_t)INT64_MAX;
    if(pt_test_mode==42 && ticks==2)t->tv_nsec=0;
    if(pt_test_mode==43){t->tv_sec=(time_t)(INT64_MAX/1000000000);t->tv_nsec=(long)(INT64_MAX%1000000000-1);}
    if(pt_test_mode==44)t->tv_sec=-1;
    if(pt_test_mode==45 && ticks==4)t->tv_nsec=2000000;
    if((pt_test_mode==46 || pt_test_mode==47) && ticks==3)t->tv_nsec=1500000;
    return 0;
}
int pt_test_poll(struct pollfd *fds,nfds_t count,int timeout) {
    pt_test_poll_count++;
    if(timeout<=0 || (count!=2 && count!=3)){errno=EINVAL;return -1;}
    if(pt_test_mode==38){errno=EINTR;return -1;}
    if(pt_test_mode==37){fds[count-1].revents=POLLIN;return 1;}
    /* Audio readiness arrives on descriptor two: using descriptor zero alone fails. */
    fds[count-2].revents=pt_test_mode==6?POLLERR:POLLIN;return 1;
}
int pt_test_close(int fd) { if(fd!=101){errno=EBADF;return -1;}pt_test_closes++;return 0; }
int pt_test_open(const char *node,int flags) {
    if(sscanf(node,"/dev/video%u",&video_index)!=1 ||
       (flags&(O_RDWR|O_NONBLOCK|O_CLOEXEC|O_NOFOLLOW))!=(O_RDWR|O_NONBLOCK|O_CLOEXEC|O_NOFOLLOW)) {errno=EINVAL;return -1;}
    return 101;
}
int pt_test_fstat(int fd,struct stat *st) {
    if(fd!=101){errno=EBADF;return -1;}memset(st,0,sizeof(*st));st->st_mode=S_IFCHR;st->st_rdev=(dev_t)((81u<<16)|video_index);return 0;
}
int pt_test_ioctl(int fd,unsigned long request,void *arg) {
    if(fd!=101){errno=EBADF;return -1;}
    switch(request) {
    case VIDIOC_QUERYCAP: {
        struct v4l2_capability *c=arg;memset(c,0,sizeof(*c));
        memcpy(c->driver,"TEST",5);memcpy(c->card,"FAKE",5);memcpy(c->bus_info,"no-device",10);
        c->capabilities=V4L2_CAP_DEVICE_CAPS;c->device_caps=V4L2_CAP_VIDEO_CAPTURE|V4L2_CAP_STREAMING;
        if(pt_test_mode==34)c->device_caps=V4L2_CAP_STREAMING;
        if(pt_test_mode==35)c->driver[0]='X';return 0;
    }
    case VIDIOC_S_FMT: {
        struct v4l2_format *f=arg;if(pt_test_mode==33)f->fmt.pix.width++;
        f->fmt.pix.bytesperline=6;f->fmt.pix.sizeimage=12;return 0;
    }
    case VIDIOC_G_PARM: ((struct v4l2_streamparm *)arg)->parm.capture.capability=V4L2_CAP_TIMEPERFRAME;return 0;
    case VIDIOC_S_PARM: {
        struct v4l2_streamparm *p=arg;
        if(pt_test_mode==48)p->parm.capture.timeperframe.denominator++;
        if(pt_test_mode==49){p->parm.capture.timeperframe.numerator*=2;p->parm.capture.timeperframe.denominator*=2;}
        return 0;
    }
    case VIDIOC_REQBUFS: {
        struct v4l2_requestbuffers *r=arg;
        if(!r->count){pt_test_releases++;return 0;}
        if(pt_test_mode==21)r->count=9;return 0;
    }
    case VIDIOC_QUERYBUF: {
        struct v4l2_buffer *b=arg;b->length=pt_test_mode==22?129:12;
        b->m.offset=pt_test_mode==36?0:b->index*4096;return 0;
    }
    case VIDIOC_QBUF: {
        struct v4l2_buffer *b=arg;queue_count++;
        if((pt_test_mode==24 && queue_count==2) || (pt_test_mode==31 && streaming)){errno=EIO;return -1;}
        if(streaming && b->index<8 && maps[b->index])memset(maps[b->index],0,12);
        return 0;
    }
    case VIDIOC_STREAMON:
        if(pt_test_mode==25){errno=EIO;return -1;}streaming=1;return 0;
    case VIDIOC_STREAMOFF: pt_test_streamoffs++;streaming=0;return 0;
    case VIDIOC_DQBUF: {
        struct v4l2_buffer *b=arg;dequeues++;
        if(pt_test_mode==39 && dequeues==1){errno=EINTR;return -1;}
        b->index=pt_test_mode==26?99:0;b->length=12;b->bytesused=pt_test_mode==27?9:pt_test_mode==32?13:12;
        b->field=V4L2_FIELD_NONE;b->flags=pt_test_mode==28?V4L2_BUF_FLAG_ERROR:0;
        if(pt_test_mode==30 && sequence)b->flags=V4L2_BUF_FLAG_TIMESTAMP_MONOTONIC;
        b->sequence=sequence++;if(pt_test_mode==29 && b->sequence)b->sequence++;
        b->timestamp.tv_sec=0;b->timestamp.tv_usec=0;
        if(maps[0]) {const uint8_t row[]={1,2,3,4,99,98,5,6,7,8,97,96};memcpy(maps[0],row,12);}return 0;
    }
    default: errno=EINVAL;return -1;
    }
}
void *pt_test_mmap(void *address,size_t length,int prot,int flags,int fd,off_t offset) {
    (void)address;(void)prot;(void)flags;
    if(fd!=101 || offset<0 || offset/4096>=8 || (pt_test_mode==23 && pt_test_maps==1)){errno=ENOMEM;return MAP_FAILED;}
    void *result=calloc(1,length);if(!result){errno=ENOMEM;return MAP_FAILED;}
    maps[offset/4096]=result;pt_test_maps++;return result;
}
int pt_test_munmap(void *address,size_t length) {
    (void)length;
    for(unsigned i=0;i<8;i++)if(maps[i]==address){free(address);maps[i]=NULL;pt_test_unmaps++;return 0;}
    errno=EINVAL;return -1;
}
