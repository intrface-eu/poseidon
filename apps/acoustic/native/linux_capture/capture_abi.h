#ifndef PT_CAPTURE_ABI_H
#define PT_CAPTURE_ABI_H
#include <stdint.h>
#include <stddef.h>

/* All public integers are fixed width. No kernel/ALSA structs cross this ABI. */
#define PT_ABI_VERSION 1u
#define PT_MAX_CHUNK (8u * 1024u * 1024u)
#define PT_MAX_PIXELS 1048576u
#define PT_MAX_BUFFERS 8u
#define PT_OK 0
#define PT_AGAIN 1
#define PT_CANCELLED 2
#define PT_FAULT 3
#define PT_DOMAIN_NONE 0u
#define PT_DOMAIN_ERRNO 1u
#define PT_DOMAIN_ALSA 2u
#define PT_DOMAIN_CONTRACT 3u
#define PT_PRODUCTION_LINUX 1u
#define PT_TEST_ARTIFACT 2u
#define PT_VALID_STATUS 1u
#define PT_VALID_HTSTAMP 2u
#define PT_VALID_TRIGGER 4u
#define PT_VALID_AUDIO_STAMP 8u
#define PT_VALID_ACCURACY 16u
#define PT_VALID_HOST 32u
#define PT_VALID_VIDEO_STAMP 64u

typedef struct { uint32_t abi_version, struct_size, domain; int32_t code; } pt_error;
typedef struct {
    uint32_t abi_version, struct_size, kind, pointer_bits;
    char build_sha256[65], profile_sha256[65];
} pt_identity;
typedef struct {
    uint32_t abi_version, struct_size, card, device, subdevice, channels, rate;
    uint32_t chunk_frames, period_frames, period_min, period_max;
    uint32_t buffer_frames, buffer_min, buffer_max, max_chunk_bytes, max_poll_descriptors;
    char expected_pcm_id[64];
} pt_audio_config;
typedef struct {
    uint32_t abi_version, struct_size, channels, rate, period_frames, buffer_frames;
    uint32_t poll_descriptors, format_s16_le;
    char pcm_id[64];
} pt_audio_actual;
typedef struct {
    uint32_t abi_version, struct_size, video_index, width, height, buffer_count;
    uint32_t max_buffer_bytes, max_mapped_bytes, max_chunk_bytes;
    uint32_t cadence_numerator, cadence_denominator;
    char expected_driver[16], expected_card[32], expected_bus_info[32];
} pt_video_config;
typedef struct {
    uint32_t abi_version, struct_size, width, height, bytesperline, sizeimage;
    uint32_t buffer_count, mapped_bytes, colorspace, ycbcr_enc, quantization, xfer_func;
    uint32_t cadence_numerator, cadence_denominator, cadence_valid;
    char driver[16], card[32], bus_info[32];
} pt_video_actual;
typedef struct {
    uint32_t abi_version, struct_size, valid, frames, bytes, state;
    uint32_t audio_actual_type, audio_report_valid, audio_accuracy_report, audio_accuracy_ns;
    int64_t available_frames, delay_frames;
    int64_t htstamp_sec, htstamp_nsec, trigger_sec, trigger_nsec, audio_sec, audio_nsec;
    int64_t host_before_ns, host_after_ns;
} pt_audio_record;
typedef struct {
    uint32_t abi_version, struct_size, valid, bytes, sequence, raw_flags, field;
    uint32_t timestamp_domain_flags, timestamp_source_flags, bytesused, mapped_length;
    uint32_t bytesperline, sizeimage, padding_removed, sequence_wrapped;
    int64_t timestamp_sec, timestamp_usec, host_before_ns, host_after_ns;
} pt_video_record;

uint32_t pt_capture_abi_version(void);
int32_t pt_capture_identity(pt_identity *out);
/* Record IDs 1..8 correspond to the eight public structs above. */
uint32_t pt_capture_size(uint32_t record_id);
uint32_t pt_capture_offset(uint32_t record_id, uint32_t field_id);
int32_t pt_alsa_open(const pt_audio_config *, void **, pt_audio_actual *, pt_error *);
int32_t pt_alsa_start(void *, pt_error *);
int32_t pt_alsa_poll_copy(void *, uint8_t *, uint32_t, int32_t, uint32_t, pt_audio_record *, pt_error *);
int32_t pt_alsa_stop_close(void *, pt_error *);
int32_t pt_v4l2_open(const pt_video_config *, void **, pt_video_actual *, pt_error *);
int32_t pt_v4l2_start(void *, pt_error *);
int32_t pt_v4l2_poll_copy(void *, uint8_t *, uint32_t, int32_t, uint32_t, pt_video_record *, pt_error *);
int32_t pt_v4l2_stop_close(void *, pt_error *);
/* Pure checked row algorithm, also exercised by the portable test-fake artifact. */
int32_t pt_copy_yuyv(const uint8_t *, uint32_t, uint32_t, uint32_t, uint32_t,
                     uint32_t, uint8_t *, uint32_t, uint32_t *);
#endif
