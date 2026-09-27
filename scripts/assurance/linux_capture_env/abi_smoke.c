/* No devices, enumeration, ioctls, ALSA handles, or capture calls.
 * Only compiled layout/constants and the ALSA library version are observed.
 */
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>
#include <sys/time.h>
#include <alsa/asoundlib.h>
#include <linux/videodev2.h>

static void json_string(const char *value)
{
    const unsigned char *p = (const unsigned char *)value;
    putchar('"');
    for (; *p != 0; ++p) {
        if (*p == '"' || *p == '\\') {
            putchar('\\');
            putchar(*p);
        } else if (*p < 0x20) {
            printf("\\u%04x", (unsigned int)*p);
        } else {
            putchar(*p);
        }
    }
    putchar('"');
}

#define SIZE(type) printf("\"" #type "\":%zu", sizeof(type))
#define OFFSET(type, field) printf("\"" #field "\":%zu", offsetof(type, field))
#define CONSTANT(name) printf("\"" #name "\":%llu", (unsigned long long)(name))

int main(void)
{
    const uint32_t order = UINT32_C(0x01020304);
    const unsigned char first = *(const unsigned char *)&order;
    const char *runtime_version = snd_asoundlib_version();
    if (runtime_version == NULL) {
        return 2;
    }
    printf("{\"schema\":\"poseidon.linux-capture-abi-smoke.v1\",");
    printf("\"pointer_size\":%zu,\"endianness\":", sizeof(void *));
    json_string(first == 4 ? "little" : first == 1 ? "big" : "mixed");
    printf(",\"alsa_runtime_version\":");
    json_string(runtime_version);
    printf(",\"alsa_header_version\":");
    json_string(SND_LIB_VERSION_STR);
    printf(",\"scalar_sizes\":{");
    SIZE(size_t); printf(","); SIZE(long); printf(","); SIZE(time_t);
    printf(","); SIZE(snd_pcm_sframes_t); printf(","); SIZE(snd_pcm_uframes_t);
    printf(","); SIZE(snd_pcm_format_t); printf(","); SIZE(snd_pcm_access_t);
    printf(","); SIZE(snd_pcm_stream_t); printf(","); SIZE(snd_pcm_state_t);
    printf("},\"struct_sizes\":{");
    SIZE(struct timeval); printf(","); SIZE(struct timespec);
    printf(","); SIZE(struct v4l2_capability); printf(","); SIZE(struct v4l2_format);
    printf(","); SIZE(struct v4l2_pix_format); printf(","); SIZE(struct v4l2_pix_format_mplane);
    printf(","); SIZE(struct v4l2_requestbuffers); printf(","); SIZE(struct v4l2_buffer);
    printf(","); SIZE(struct v4l2_plane); printf(","); SIZE(struct v4l2_timecode);
    printf(","); SIZE(struct v4l2_exportbuffer);
    printf("},\"struct_alignments\":{\"v4l2_buffer\":%zu,\"v4l2_format\":%zu,\"v4l2_plane\":%zu},",
           _Alignof(struct v4l2_buffer), _Alignof(struct v4l2_format), _Alignof(struct v4l2_plane));
    printf("\"offsets\":{\"v4l2_buffer\":{");
    OFFSET(struct v4l2_buffer, index); printf(","); OFFSET(struct v4l2_buffer, type);
    printf(","); OFFSET(struct v4l2_buffer, bytesused); printf(","); OFFSET(struct v4l2_buffer, flags);
    printf(","); OFFSET(struct v4l2_buffer, field); printf(","); OFFSET(struct v4l2_buffer, timestamp);
    printf(","); OFFSET(struct v4l2_buffer, timecode); printf(","); OFFSET(struct v4l2_buffer, sequence);
    printf(","); OFFSET(struct v4l2_buffer, memory); printf(","); OFFSET(struct v4l2_buffer, m);
    printf(","); OFFSET(struct v4l2_buffer, length); printf(","); OFFSET(struct v4l2_buffer, reserved2);
    printf(","); OFFSET(struct v4l2_buffer, request_fd);
    printf("},\"v4l2_format\":{");
    OFFSET(struct v4l2_format, type); printf(","); OFFSET(struct v4l2_format, fmt);
    printf("},\"v4l2_requestbuffers\":{");
    OFFSET(struct v4l2_requestbuffers, count); printf(","); OFFSET(struct v4l2_requestbuffers, type);
    printf(","); OFFSET(struct v4l2_requestbuffers, memory); printf(","); OFFSET(struct v4l2_requestbuffers, capabilities);
    printf("},\"v4l2_plane\":{");
    OFFSET(struct v4l2_plane, bytesused); printf(","); OFFSET(struct v4l2_plane, length);
    printf(","); OFFSET(struct v4l2_plane, m); printf(","); OFFSET(struct v4l2_plane, data_offset);
    printf("}},\"constants\":{");
    CONSTANT(V4L2_BUF_TYPE_VIDEO_CAPTURE); printf(","); CONSTANT(V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE);
    printf(","); CONSTANT(V4L2_MEMORY_MMAP); printf(","); CONSTANT(V4L2_MEMORY_USERPTR);
    printf(","); CONSTANT(V4L2_MEMORY_DMABUF); printf(","); CONSTANT(V4L2_FIELD_ANY);
    printf(","); CONSTANT(V4L2_CAP_VIDEO_CAPTURE); printf(","); CONSTANT(V4L2_CAP_VIDEO_CAPTURE_MPLANE);
    printf(","); CONSTANT(V4L2_CAP_STREAMING); printf(","); CONSTANT(V4L2_CAP_DEVICE_CAPS);
    printf(","); CONSTANT(V4L2_PIX_FMT_YUYV); printf(","); CONSTANT(V4L2_PIX_FMT_MJPEG);
    printf(","); CONSTANT(V4L2_BUF_FLAG_ERROR); printf(","); CONSTANT(V4L2_BUF_FLAG_TIMESTAMP_MONOTONIC);
    printf(","); CONSTANT(VIDIOC_QUERYCAP); printf(","); CONSTANT(VIDIOC_G_FMT);
    printf(","); CONSTANT(VIDIOC_S_FMT); printf(","); CONSTANT(VIDIOC_REQBUFS);
    printf(","); CONSTANT(VIDIOC_QUERYBUF); printf(","); CONSTANT(VIDIOC_QBUF);
    printf(","); CONSTANT(VIDIOC_DQBUF); printf(","); CONSTANT(VIDIOC_STREAMON);
    printf(","); CONSTANT(VIDIOC_STREAMOFF);
    printf(","); CONSTANT(SND_PCM_STREAM_CAPTURE); printf(","); CONSTANT(SND_PCM_ACCESS_RW_INTERLEAVED);
    printf(","); CONSTANT(SND_PCM_FORMAT_S16_LE); printf(","); CONSTANT(SND_PCM_FORMAT_S24_3LE);
    printf(","); CONSTANT(SND_PCM_FORMAT_S32_LE);
    printf("},\"device_access_occurred\":false,\"hardware_qualified\":false}\n");
    return ferror(stdout) ? 3 : 0;
}
