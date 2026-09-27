#include "capture_abi.h"
#include <limits.h>
#include <string.h>
#ifndef PT_BUILD_SHA256
#error "Build identity required; use the profile-checked build tool or explicit TEST-FAKE build"
#endif
#ifndef PT_PROFILE_SHA256
#error "Native profile identity required"
#endif
#if !defined(__linux__) && !defined(PT_TEST_FAKE)
#error "Production capture requires Linux headers/runtime"
#endif
uint32_t pt_capture_abi_version(void) { return PT_ABI_VERSION; }
int32_t pt_capture_identity(pt_identity *out) {
    if (!out) return PT_FAULT;
    memset(out, 0, sizeof(*out));
    out->abi_version = PT_ABI_VERSION; out->struct_size = sizeof(*out);
#ifdef PT_TEST_FAKE
    out->kind = PT_TEST_ARTIFACT;
#else
    out->kind = PT_PRODUCTION_LINUX;
#endif
    out->pointer_bits = sizeof(void *) * CHAR_BIT;
    _Static_assert(sizeof(PT_BUILD_SHA256) == 65, "build hash length");
    _Static_assert(sizeof(PT_PROFILE_SHA256) == 65, "profile hash length");
    memcpy(out->build_sha256, PT_BUILD_SHA256, 65);
    memcpy(out->profile_sha256, PT_PROFILE_SHA256, 65);
    return PT_OK;
}
#define O(t, f) ((uint32_t)offsetof(t, f))
#define END UINT32_MAX
static const uint32_t offsets1[] = {O(pt_error,abi_version),O(pt_error,struct_size),O(pt_error,domain),O(pt_error,code),END};
static const uint32_t offsets2[] = {O(pt_identity,abi_version),O(pt_identity,struct_size),O(pt_identity,kind),O(pt_identity,pointer_bits),O(pt_identity,build_sha256),O(pt_identity,profile_sha256),END};
static const uint32_t offsets3[] = {O(pt_audio_config,abi_version),O(pt_audio_config,struct_size),O(pt_audio_config,card),O(pt_audio_config,device),O(pt_audio_config,subdevice),O(pt_audio_config,channels),O(pt_audio_config,rate),O(pt_audio_config,chunk_frames),O(pt_audio_config,period_frames),O(pt_audio_config,period_min),O(pt_audio_config,period_max),O(pt_audio_config,buffer_frames),O(pt_audio_config,buffer_min),O(pt_audio_config,buffer_max),O(pt_audio_config,max_chunk_bytes),O(pt_audio_config,max_poll_descriptors),O(pt_audio_config,expected_pcm_id),END};
static const uint32_t offsets4[] = {O(pt_audio_actual,abi_version),O(pt_audio_actual,struct_size),O(pt_audio_actual,channels),O(pt_audio_actual,rate),O(pt_audio_actual,period_frames),O(pt_audio_actual,buffer_frames),O(pt_audio_actual,poll_descriptors),O(pt_audio_actual,format_s16_le),O(pt_audio_actual,pcm_id),END};
static const uint32_t offsets5[] = {O(pt_video_config,abi_version),O(pt_video_config,struct_size),O(pt_video_config,video_index),O(pt_video_config,width),O(pt_video_config,height),O(pt_video_config,buffer_count),O(pt_video_config,max_buffer_bytes),O(pt_video_config,max_mapped_bytes),O(pt_video_config,max_chunk_bytes),O(pt_video_config,cadence_numerator),O(pt_video_config,cadence_denominator),O(pt_video_config,expected_driver),O(pt_video_config,expected_card),O(pt_video_config,expected_bus_info),END};
static const uint32_t offsets6[] = {O(pt_video_actual,abi_version),O(pt_video_actual,struct_size),O(pt_video_actual,width),O(pt_video_actual,height),O(pt_video_actual,bytesperline),O(pt_video_actual,sizeimage),O(pt_video_actual,buffer_count),O(pt_video_actual,mapped_bytes),O(pt_video_actual,colorspace),O(pt_video_actual,ycbcr_enc),O(pt_video_actual,quantization),O(pt_video_actual,xfer_func),O(pt_video_actual,cadence_numerator),O(pt_video_actual,cadence_denominator),O(pt_video_actual,cadence_valid),O(pt_video_actual,driver),O(pt_video_actual,card),O(pt_video_actual,bus_info),END};
static const uint32_t offsets7[] = {O(pt_audio_record,abi_version),O(pt_audio_record,struct_size),O(pt_audio_record,valid),O(pt_audio_record,frames),O(pt_audio_record,bytes),O(pt_audio_record,state),O(pt_audio_record,audio_actual_type),O(pt_audio_record,audio_report_valid),O(pt_audio_record,audio_accuracy_report),O(pt_audio_record,audio_accuracy_ns),O(pt_audio_record,available_frames),O(pt_audio_record,delay_frames),O(pt_audio_record,htstamp_sec),O(pt_audio_record,htstamp_nsec),O(pt_audio_record,trigger_sec),O(pt_audio_record,trigger_nsec),O(pt_audio_record,audio_sec),O(pt_audio_record,audio_nsec),O(pt_audio_record,host_before_ns),O(pt_audio_record,host_after_ns),END};
static const uint32_t offsets8[] = {O(pt_video_record,abi_version),O(pt_video_record,struct_size),O(pt_video_record,valid),O(pt_video_record,bytes),O(pt_video_record,sequence),O(pt_video_record,raw_flags),O(pt_video_record,field),O(pt_video_record,timestamp_domain_flags),O(pt_video_record,timestamp_source_flags),O(pt_video_record,bytesused),O(pt_video_record,mapped_length),O(pt_video_record,bytesperline),O(pt_video_record,sizeimage),O(pt_video_record,padding_removed),O(pt_video_record,sequence_wrapped),O(pt_video_record,timestamp_sec),O(pt_video_record,timestamp_usec),O(pt_video_record,host_before_ns),O(pt_video_record,host_after_ns),END};
uint32_t pt_capture_size(uint32_t id) {
    static const uint32_t sizes[] = {0,sizeof(pt_error),sizeof(pt_identity),sizeof(pt_audio_config),sizeof(pt_audio_actual),sizeof(pt_video_config),sizeof(pt_video_actual),sizeof(pt_audio_record),sizeof(pt_video_record)};
    return id < sizeof(sizes)/sizeof(sizes[0]) ? sizes[id] : 0;
}
uint32_t pt_capture_offset(uint32_t id, uint32_t field) {
    static const uint32_t *const tables[] = {NULL, offsets1,offsets2,offsets3,offsets4,offsets5,offsets6,offsets7,offsets8};
    if (id == 0 || id >= sizeof(tables)/sizeof(tables[0])) return END;
    for (uint32_t i = 0; tables[id][i] != END; i++) if (i == field) return tables[id][i];
    return END;
}
int32_t pt_copy_yuyv(const uint8_t *src, uint32_t mapped, uint32_t used,
                     uint32_t width, uint32_t height, uint32_t stride,
                     uint8_t *dst, uint32_t capacity, uint32_t *written) {
    if (written) *written = 0;
    uint64_t row = (uint64_t)width * 2, active = row * height;
    uint64_t required = height ? (uint64_t)(height - 1) * stride + row : 0;
    if (!src || !dst || !written || !width || !height || (width & 1u) ||
        (uint64_t)width * height > PT_MAX_PIXELS || stride < row ||
        used > mapped || required > used || active > capacity || active > PT_MAX_CHUNK)
        return PT_FAULT;
    for (uint32_t y = 0; y < height; y++)
        memcpy(dst + (size_t)y * (size_t)row, src + (size_t)y * stride, (size_t)row);
    *written = (uint32_t)active;
    return PT_OK;
}
