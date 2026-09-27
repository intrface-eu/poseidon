#define _POSIX_C_SOURCE 200809L
#include "capture_internal.h"
#ifdef PT_TEST_FAKE
#include "fake_alsa.h"
#else
#include <alsa/asoundlib.h>
#endif
#include <stdio.h>

typedef struct {
    snd_pcm_t *pcm;
    snd_pcm_status_t *status;
    struct pollfd *pollfds;
    pt_audio_config config;
    uint32_t count;
    bool started, failed, have_report;
    unsigned last_type, last_valid;
    int64_t last_host_ns;
} audio_handle;

static int audio_state_error(snd_pcm_state_t state) {
    if (state == SND_PCM_STATE_XRUN) return -EPIPE;
    if (state == SND_PCM_STATE_SUSPENDED) return -ESTRPIPE;
    if (state == SND_PCM_STATE_DISCONNECTED) return -ENODEV;
    return -EIO;
}
static int audio_destroy(audio_handle *h) {
    int first = 0, rc;
    if (!h) return 0;
    if (h->pcm) {
        /* drop is safe on partial initialization; always attempt close as well. */
        rc = snd_pcm_drop(h->pcm);
        if (rc < 0 && rc != -EBADFD) first = rc;
        rc = snd_pcm_close(h->pcm);
        if (!first && rc < 0) first = rc;
    }
    if (h->status) snd_pcm_status_free(h->status);
    free(h->pollfds); free(h);
    return first;
}
int32_t pt_alsa_open(const pt_audio_config *c, void **out, pt_audio_actual *actual, pt_error *e) {
    pt_clear_error(e);
    if (out) *out = NULL;
    if (actual) PT_INIT(actual);
    if (!out || !actual || !PT_HEADER(c) || c->card > 65535 || c->device > 65535 ||
        c->subdevice > 65535 || !c->channels || c->channels > 8 || !c->rate || c->rate > 384000 ||
        !c->chunk_frames || !c->max_chunk_bytes || c->max_chunk_bytes > PT_MAX_CHUNK ||
        (uint64_t)c->chunk_frames * c->channels * 2 > c->max_chunk_bytes ||
        !c->period_min || c->period_min > c->period_frames || c->period_frames > c->period_max ||
        !c->buffer_min || c->buffer_min > c->buffer_frames || c->buffer_frames > c->buffer_max ||
        c->period_max > c->buffer_max || (uint64_t)c->buffer_max * c->channels * 2 > PT_MAX_CHUNK ||
        !c->max_poll_descriptors || c->max_poll_descriptors > 64 ||
        !pt_literal(c->expected_pcm_id, sizeof(c->expected_pcm_id)))
        return pt_fail(e, PT_DOMAIN_CONTRACT, EINVAL);
    audio_handle *h = calloc(1, sizeof(*h));
    if (!h) return pt_fail(e, PT_DOMAIN_ERRNO, ENOMEM);
    h->config = *c;
    snd_config_t *local = NULL;
    snd_pcm_hw_params_t *hw = NULL;
    snd_pcm_sw_params_t *sw = NULL;
    snd_pcm_info_t *info = NULL;
    int rc = 0, direction = 0;
    char text[256];
    /* Only numeric fields enter this private tree. No global/user ALSA config. */
    int n = snprintf(text, sizeof(text), "pcm.pt_selected { type hw card %u device %u subdevice %u }", c->card,c->device,c->subdevice);
    if (n < 0 || (size_t)n >= sizeof(text)) { rc = -EINVAL; goto fail; }
#define ALSA(call) do { rc = (call); if (rc < 0) goto fail; } while (0)
    ALSA(snd_config_load_string(&local, text, (size_t)n));
    ALSA(snd_pcm_open_lconf(&h->pcm, "pt_selected", SND_PCM_STREAM_CAPTURE, SND_PCM_NONBLOCK, local));
    ALSA(snd_pcm_info_malloc(&info));
    ALSA(snd_pcm_info(h->pcm, info));
    const char *id = snd_pcm_info_get_id(info);
    if (snd_pcm_info_get_card(info) != (int)c->card || snd_pcm_info_get_device(info) != c->device ||
        snd_pcm_info_get_subdevice(info) != c->subdevice || !id ||
        strnlen(id, sizeof(actual->pcm_id)) >= sizeof(actual->pcm_id) || strcmp(id,c->expected_pcm_id)) {
        rc = -ENODEV; goto fail;
    }
    memcpy(actual->pcm_id, id, strlen(id) + 1);
    ALSA(snd_pcm_hw_params_malloc(&hw));
    ALSA(snd_pcm_hw_params_any(h->pcm, hw));
    ALSA(snd_pcm_hw_params_set_rate_resample(h->pcm, hw, 0));
    ALSA(snd_pcm_hw_params_set_access(h->pcm, hw, SND_PCM_ACCESS_RW_INTERLEAVED));
    ALSA(snd_pcm_hw_params_set_format(h->pcm, hw, SND_PCM_FORMAT_S16_LE));
    ALSA(snd_pcm_hw_params_set_channels(h->pcm, hw, c->channels));
    ALSA(snd_pcm_hw_params_set_rate(h->pcm, hw, c->rate, 0));
    snd_pcm_uframes_t period = c->period_frames, buffer = c->buffer_frames;
    ALSA(snd_pcm_hw_params_set_period_size_near(h->pcm, hw, &period, &direction));
    ALSA(snd_pcm_hw_params_set_buffer_size_near(h->pcm, hw, &buffer));
    if (period < c->period_min || period > c->period_max || buffer < c->buffer_min || buffer > c->buffer_max || period > buffer) { rc = -EINVAL; goto fail; }
    ALSA(snd_pcm_hw_params(h->pcm, hw));
    ALSA(snd_pcm_hw_params_current(h->pcm, hw));
    snd_pcm_access_t access; snd_pcm_format_t format; unsigned channels, rate;
    ALSA(snd_pcm_hw_params_get_access(hw, &access));
    ALSA(snd_pcm_hw_params_get_format(hw, &format));
    ALSA(snd_pcm_hw_params_get_channels(hw, &channels));
    ALSA(snd_pcm_hw_params_get_rate(hw, &rate, &direction));
    if (access != SND_PCM_ACCESS_RW_INTERLEAVED || format != SND_PCM_FORMAT_S16_LE || channels != c->channels || rate != c->rate || direction != 0) { rc = -EINVAL; goto fail; }
    ALSA(snd_pcm_hw_params_get_period_size(hw, &period, &direction));
    ALSA(snd_pcm_hw_params_get_buffer_size(hw, &buffer));
    if (period < c->period_min || period > c->period_max || buffer < c->buffer_min || buffer > c->buffer_max || period > buffer) { rc = -EINVAL; goto fail; }
    ALSA(snd_pcm_sw_params_malloc(&sw));
    ALSA(snd_pcm_sw_params_current(h->pcm, sw));
    snd_pcm_uframes_t boundary;
    ALSA(snd_pcm_sw_params_get_boundary(sw, &boundary));
    ALSA(snd_pcm_sw_params_set_start_threshold(h->pcm, sw, boundary));
    ALSA(snd_pcm_sw_params_set_avail_min(h->pcm, sw, period));
    ALSA(snd_pcm_sw_params_set_tstamp_mode(h->pcm, sw, SND_PCM_TSTAMP_ENABLE));
    ALSA(snd_pcm_sw_params_set_tstamp_type(h->pcm, sw, SND_PCM_TSTAMP_TYPE_MONOTONIC));
    ALSA(snd_pcm_sw_params(h->pcm, sw));
    ALSA(snd_pcm_status_malloc(&h->status));
    rc = snd_pcm_poll_descriptors_count(h->pcm);
    if (rc <= 0 || (unsigned)rc > c->max_poll_descriptors) { rc = -EINVAL; goto fail; }
    h->count = (uint32_t)rc;
    h->pollfds = calloc(h->count + 1, sizeof(*h->pollfds));
    if (!h->pollfds) { rc = -ENOMEM; goto fail; }
    ALSA(snd_pcm_poll_descriptors(h->pcm, h->pollfds, h->count));
    if ((uint32_t)rc != h->count) { rc = -EIO; goto fail; }
    ALSA(snd_pcm_prepare(h->pcm));
    actual->channels = channels; actual->rate = rate; actual->period_frames = (uint32_t)period;
    actual->buffer_frames = (uint32_t)buffer; actual->poll_descriptors = h->count; actual->format_s16_le = 1;
    snd_pcm_info_free(info); snd_pcm_hw_params_free(hw); snd_pcm_sw_params_free(sw); snd_config_delete(local);
    *out = h;
    return PT_OK;
fail:
    if (info) snd_pcm_info_free(info);
    if (hw) snd_pcm_hw_params_free(hw);
    if (sw) snd_pcm_sw_params_free(sw);
    audio_destroy(h);
    if (local) snd_config_delete(local);
    PT_INIT(actual);
    return pt_fail(e, PT_DOMAIN_ALSA, rc);
#undef ALSA
}
int32_t pt_alsa_start(void *handle, pt_error *e) {
    audio_handle *h = handle; pt_clear_error(e);
    if (!h || h->started || h->failed) return pt_fail(e, PT_DOMAIN_CONTRACT, EINVAL);
    int rc = snd_pcm_start(h->pcm);
    if (rc < 0) { h->failed = true; return pt_fail(e, PT_DOMAIN_ALSA, rc); }
    h->started = true; return PT_OK;
}
static int get_status(audio_handle *h, pt_audio_record *r) {
    snd_pcm_audio_tstamp_config_t request = {.type_requested=SND_PCM_AUDIO_TSTAMP_TYPE_DEFAULT,.report_delay=1};
    snd_pcm_status_set_audio_htstamp_config(h->status, &request);
    int rc = snd_pcm_status(h->pcm, h->status);
    if (rc < 0) return rc;
    snd_pcm_state_t state = snd_pcm_status_get_state(h->status);
    if (state != SND_PCM_STATE_RUNNING) return audio_state_error(state);
    r->state = (uint32_t)state;
    snd_pcm_uframes_t avail = snd_pcm_status_get_avail(h->status);
    if ((uint64_t)avail > INT64_MAX) return -EOVERFLOW;
    r->available_frames = (int64_t)avail; r->delay_frames = (int64_t)snd_pcm_status_get_delay(h->status);
    r->valid |= PT_VALID_STATUS;
    snd_htimestamp_t t;
    snd_pcm_status_get_htstamp(h->status, &t);
    if (t.tv_sec >= 0 && t.tv_nsec >= 0 && t.tv_nsec < 1000000000 && (t.tv_sec || t.tv_nsec)) {
        r->htstamp_sec=t.tv_sec; r->htstamp_nsec=t.tv_nsec; r->valid |= PT_VALID_HTSTAMP;
    }
    snd_pcm_status_get_trigger_htstamp(h->status, &t);
    if (t.tv_sec >= 0 && t.tv_nsec >= 0 && t.tv_nsec < 1000000000 && (t.tv_sec || t.tv_nsec)) {
        r->trigger_sec=t.tv_sec; r->trigger_nsec=t.tv_nsec; r->valid |= PT_VALID_TRIGGER;
    }
    snd_pcm_audio_tstamp_report_t report = {0};
    snd_pcm_status_get_audio_htstamp_report(h->status, &report);
    r->audio_actual_type=report.actual_type; r->audio_report_valid=report.valid;
    r->audio_accuracy_report=report.accuracy_report;
    if (h->have_report && (h->last_type != report.actual_type || h->last_valid != report.valid)) return -ESTALE;
    h->last_type=report.actual_type; h->last_valid=report.valid; h->have_report=true;
    if (report.valid) {
        snd_pcm_status_get_audio_htstamp(h->status, &t);
        if (t.tv_sec < 0 || t.tv_nsec < 0 || t.tv_nsec >= 1000000000) return -EIO;
        r->audio_sec=t.tv_sec; r->audio_nsec=t.tv_nsec; r->valid |= PT_VALID_AUDIO_STAMP;
        if (report.accuracy_report) { r->audio_accuracy_ns=report.accuracy; r->valid |= PT_VALID_ACCURACY; }
    }
    return 0;
}
int32_t pt_alsa_poll_copy(void *handle, uint8_t *dst, uint32_t capacity, int32_t cancel_fd,
                         uint32_t timeout_ms, pt_audio_record *r, pt_error *e) {
    audio_handle *h=handle; pt_clear_error(e); if (r) PT_INIT(r);
    if (!h || !r || !dst || !h->started || h->failed || cancel_fd < 0 || !timeout_ms || timeout_ms > 60000 ||
        capacity < (uint64_t)h->config.chunk_frames*h->config.channels*2 || capacity > PT_MAX_CHUNK)
        return pt_fail(e, PT_DOMAIN_CONTRACT, EINVAL);
    int64_t before=pt_now();
    if (before < 0) { h->failed=true; return pt_fail(e, PT_DOMAIN_ERRNO, errno); }
    if (before < h->last_host_ns) { h->failed=true; return pt_fail(e, PT_DOMAIN_CONTRACT, EIO); }
    int64_t deadline, last_seen=before;
    if (pt_make_deadline(before,timeout_ms,&deadline,e)!=PT_OK) { h->failed=true; return PT_FAULT; }
    for (;;) {
        int32_t status=pt_wait(h->pollfds,h->count,cancel_fd,&last_seen,deadline,e);
        if (status != PT_OK) { h->last_host_ns=last_seen; if (status == PT_FAULT) h->failed=true; return status; }
        unsigned short events=0;
        int rc=snd_pcm_poll_descriptors_revents(h->pcm,h->pollfds,h->count,&events);
        if (rc < 0) { h->failed=true; return pt_fail(e,PT_DOMAIN_ALSA,rc); }
        if (events & (POLLERR|POLLHUP|POLLNVAL)) { h->failed=true; return pt_fail(e,PT_DOMAIN_ALSA,audio_state_error(snd_pcm_state(h->pcm))); }
        if (!(events & POLLIN)) continue;
        snd_pcm_sframes_t frames=snd_pcm_readi(h->pcm,dst,h->config.chunk_frames);
        if (frames == -EAGAIN || frames == -EINTR || frames == 0) continue;
        if (frames < 0) { h->failed=true; return pt_fail(e,PT_DOMAIN_ALSA,(int32_t)frames); }
        if ((uint64_t)frames > h->config.chunk_frames) { h->failed=true; return pt_fail(e,PT_DOMAIN_CONTRACT,EOVERFLOW); }
        rc=get_status(h,r);
        if (rc < 0) { h->failed=true; PT_INIT(r); return pt_fail(e,PT_DOMAIN_ALSA,rc); }
        r->host_after_ns=pt_now();
        if (r->host_after_ns < last_seen) { h->failed=true; PT_INIT(r); return pt_fail(e,PT_DOMAIN_ERRNO,EIO); }
        h->last_host_ns=r->host_after_ns;
        r->host_before_ns=before; r->valid |= PT_VALID_HOST;
        r->frames=(uint32_t)frames; r->bytes=(uint32_t)frames*h->config.channels*2;
        return PT_OK;
    }
}
int32_t pt_alsa_stop_close(void *handle, pt_error *e) {
    pt_clear_error(e);
    int rc=audio_destroy(handle);
    return rc < 0 ? pt_fail(e,PT_DOMAIN_ALSA,rc) : PT_OK;
}
