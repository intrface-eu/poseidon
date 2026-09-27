/* Portable TEST-FAKE only: no ALSA, Linux UAPI, devices, syscalls or capture. */
#ifndef PT_TEST_FAKE
#error "Fake ABI must never be built as a production artifact"
#endif
#include "capture_abi.h"
#include <stdlib.h>
#include <string.h>

typedef struct { uint32_t step, channels; } fake_handle;
static uint32_t scenario, opened, closed;
void pt_test_scenario(uint32_t value) { scenario=value; }
uint32_t pt_test_opened(void) { return opened; }
uint32_t pt_test_closed(void) { return closed; }
#define INIT(p) do { memset(p,0,sizeof(*(p))); (p)->abi_version=PT_ABI_VERSION; (p)->struct_size=sizeof(*(p)); } while (0)
static int32_t failure(pt_error *e, uint32_t domain, int32_t code) { INIT(e); e->domain=domain; e->code=code; return PT_FAULT; }
int32_t pt_alsa_open(const pt_audio_config *c, void **out, pt_audio_actual *a, pt_error *e) {
    INIT(e); INIT(a); *out=NULL;
    fake_handle *h=calloc(1,sizeof(*h));
    if (!h) return failure(e,1,12);
    h->channels=c->channels; *out=h; opened++;
    if (scenario==10) return failure(e,2,-19); /* deliberate partial handle for wrapper cleanup */
    a->channels=c->channels; a->rate=c->rate; a->period_frames=c->period_frames;
    a->buffer_frames=c->buffer_frames; a->poll_descriptors=2; a->format_s16_le=1;
    memcpy(a->pcm_id,c->expected_pcm_id,sizeof(a->pcm_id)); return PT_OK;
}
int32_t pt_alsa_start(void *h, pt_error *e) { (void)h; INIT(e); return scenario==11?failure(e,2,-32):PT_OK; }
int32_t pt_alsa_poll_copy(void *handle, uint8_t *dst, uint32_t cap, int32_t cancel, uint32_t timeout, pt_audio_record *r, pt_error *e) {
    (void)cancel; (void)timeout; fake_handle *h=handle; INIT(e); INIT(r);
    if (scenario==1) return PT_AGAIN;
    if (scenario==2) return failure(e,2,-32);
    if (scenario==3) return failure(e,2,-86);
    if (scenario==4) return failure(e,2,-19);
    if (scenario==5) return PT_CANCELLED;
    if (scenario==6) return failure(e,2,32); /* deliberately malformed ALSA sign */
    r->frames=2; r->bytes=2*h->channels*2;
    if (r->bytes>cap) return failure(e,3,75);
    memset(dst,(int)(++h->step),r->bytes);
    if (scenario==7) r->bytes=cap+1;
    if (scenario==8) { r->valid=PT_VALID_AUDIO_STAMP|PT_VALID_ACCURACY; r->audio_report_valid=1; r->audio_accuracy_report=1; r->audio_actual_type=1; }
    if (scenario==9) { r->valid=PT_VALID_STATUS; r->state=4; }
    return PT_OK;
}
int32_t pt_alsa_stop_close(void *h, pt_error *e) { INIT(e); if(h) {free(h);closed++;} return PT_OK; }
int32_t pt_v4l2_open(const pt_video_config *c, void **out, pt_video_actual *a, pt_error *e) {
    INIT(e); INIT(a); *out=calloc(1,sizeof(fake_handle)); if(!*out) return failure(e,1,12); opened++;
    a->width=c->width; a->height=c->height; a->bytesperline=c->width*2+2;
    a->sizeimage=a->bytesperline*c->height; a->buffer_count=1; a->mapped_bytes=a->sizeimage;
    a->cadence_valid=!!c->cadence_numerator; a->cadence_numerator=c->cadence_numerator; a->cadence_denominator=c->cadence_denominator;
    memcpy(a->driver,c->expected_driver,sizeof(a->driver)); memcpy(a->card,c->expected_card,sizeof(a->card));
    memcpy(a->bus_info,c->expected_bus_info,sizeof(a->bus_info)); return PT_OK;
}
int32_t pt_v4l2_start(void *h, pt_error *e) { return pt_alsa_start(h,e); }
int32_t pt_v4l2_poll_copy(void *handle, uint8_t *dst, uint32_t cap, int32_t cancel, uint32_t timeout, pt_video_record *r, pt_error *e) {
    (void)cancel; (void)timeout; fake_handle *h=handle; INIT(e); INIT(r);
    uint8_t mapped[12]={1,2,3,4,99,98,5,6,7,8,97,96};
    if(pt_copy_yuyv(mapped,12,12,2,2,6,dst,cap,&r->bytes)!=PT_OK) return failure(e,3,22);
    /* Simulate immediate reuse AFTER the production common algorithm copied. */
    memset(mapped,0,sizeof(mapped));
    r->sequence=h->step++; r->field=1; r->bytesused=12; r->mapped_length=12;
    r->bytesperline=6; r->sizeimage=12; r->padding_removed=1;
    if(scenario==12) r->sequence+=h->step;
    return PT_OK;
}
int32_t pt_v4l2_stop_close(void *h, pt_error *e) { return pt_alsa_stop_close(h,e); }
