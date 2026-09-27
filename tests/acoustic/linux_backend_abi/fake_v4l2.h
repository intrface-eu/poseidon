/* Minimal synthetic API shapes, deliberately NOT Linux UAPI qualification. */
#ifndef PT_FAKE_V4L2_H
#define PT_FAKE_V4L2_H
#ifndef PT_TEST_FAKE
#error "TEST-FAKE only"
#endif
#include <stdint.h>
#include <sys/time.h>
#include <sys/stat.h>
#include <sys/types.h>
enum v4l2_buf_type { V4L2_BUF_TYPE_VIDEO_CAPTURE=1 };
#define V4L2_MEMORY_MMAP 1
#define V4L2_CAP_VIDEO_CAPTURE 1u
#define V4L2_CAP_STREAMING 0x04000000u
#define V4L2_CAP_DEVICE_CAPS 0x80000000u
#define V4L2_CAP_TIMEPERFRAME 0x1000u
#define V4L2_PIX_FMT_YUYV 0x56595559u
#define V4L2_FIELD_NONE 1u
#define V4L2_BUF_FLAG_ERROR 0x40u
#define V4L2_BUF_FLAG_TIMESTAMP_MASK 0xe000u
#define V4L2_BUF_FLAG_TIMESTAMP_UNKNOWN 0u
#define V4L2_BUF_FLAG_TIMESTAMP_MONOTONIC 0x2000u
#define V4L2_BUF_FLAG_TSTAMP_SRC_MASK 0x70000u
#define V4L2_BUF_FLAG_TSTAMP_SRC_EOF 0u
#define V4L2_BUF_FLAG_TSTAMP_SRC_SOE 0x10000u
/* Fake request numbers cannot be sent to a real kernel API. */
#define VIDIOC_QUERYCAP 1
#define VIDIOC_S_FMT 2
#define VIDIOC_G_PARM 3
#define VIDIOC_S_PARM 4
#define VIDIOC_REQBUFS 5
#define VIDIOC_QUERYBUF 6
#define VIDIOC_QBUF 7
#define VIDIOC_STREAMON 8
#define VIDIOC_STREAMOFF 9
#define VIDIOC_DQBUF 10
struct v4l2_capability { uint8_t driver[16],card[32],bus_info[32]; uint32_t capabilities,device_caps; };
struct v4l2_pix_format { uint32_t width,height,pixelformat,field,bytesperline,sizeimage,colorspace,ycbcr_enc,quantization,xfer_func; };
struct v4l2_format { uint32_t type; union {struct v4l2_pix_format pix;} fmt; };
struct v4l2_fract { uint32_t numerator,denominator; };
struct v4l2_streamparm { uint32_t type; union { struct { uint32_t capability; struct v4l2_fract timeperframe; } capture; } parm; };
struct v4l2_requestbuffers { uint32_t count,type,memory; };
struct v4l2_buffer { uint32_t type,memory,index,length,bytesused,field,flags,sequence; struct timeval timestamp; union {uint32_t offset;} m; };
int pt_test_open(const char *, int);
int pt_test_fstat(int, struct stat *);
int pt_test_ioctl(int, unsigned long, void *);
void *pt_test_mmap(void *, size_t, int, int, int, off_t);
int pt_test_munmap(void *, size_t);
#define open pt_test_open
#define fstat pt_test_fstat
#define ioctl pt_test_ioctl
#define mmap pt_test_mmap
#define munmap pt_test_munmap
#ifdef major
#undef major
#endif
#ifdef minor
#undef minor
#endif
#define major(dev) ((unsigned int)((dev) >> 16))
#define minor(dev) ((unsigned int)((dev) & 65535))
#endif
