/* Fake public API for testing the ACTUAL audio algorithm, not ALSA headers/runtime. */
#ifndef PT_FAKE_ALSA_H
#define PT_FAKE_ALSA_H
#ifndef PT_TEST_FAKE
#error "TEST-FAKE only"
#endif
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <poll.h>
#include <time.h>
#include "fake_system.h"
typedef unsigned long snd_pcm_uframes_t;
typedef long snd_pcm_sframes_t;
typedef int snd_pcm_state_t;
typedef int snd_pcm_access_t;
typedef int snd_pcm_format_t;
typedef struct timespec snd_htimestamp_t;
typedef struct { unsigned card,device,subdevice; } snd_config_t;
typedef struct { unsigned card,device,subdevice,channels,rate,reads; } snd_pcm_t;
typedef struct { unsigned channels,rate; snd_pcm_uframes_t period,buffer; int access,format; } snd_pcm_hw_params_t;
typedef struct { int unused; } snd_pcm_sw_params_t;
typedef struct { unsigned card,device,subdevice; } snd_pcm_info_t;
typedef struct { int unused; } snd_pcm_status_t;
typedef struct { unsigned type_requested, report_delay; } snd_pcm_audio_tstamp_config_t;
typedef struct { unsigned valid,actual_type,accuracy_report,accuracy; } snd_pcm_audio_tstamp_report_t;
#define SND_PCM_STATE_RUNNING 3
#define SND_PCM_STATE_XRUN 4
#define SND_PCM_STATE_SUSPENDED 7
#define SND_PCM_STATE_DISCONNECTED 8
#define SND_PCM_STREAM_CAPTURE 1
#define SND_PCM_NONBLOCK 1
#define SND_PCM_ACCESS_RW_INTERLEAVED 3
#define SND_PCM_FORMAT_S16_LE 2
#define SND_PCM_TSTAMP_ENABLE 1
#define SND_PCM_TSTAMP_TYPE_MONOTONIC 1
#define SND_PCM_AUDIO_TSTAMP_TYPE_DEFAULT 1
#define MALLOC_FN(name,type) static inline int name(type **out) { *out=calloc(1,sizeof(**out)); return *out?0:-ENOMEM; }
MALLOC_FN(snd_pcm_hw_params_malloc,snd_pcm_hw_params_t)
MALLOC_FN(snd_pcm_sw_params_malloc,snd_pcm_sw_params_t)
MALLOC_FN(snd_pcm_info_malloc,snd_pcm_info_t)
MALLOC_FN(snd_pcm_status_malloc,snd_pcm_status_t)
#define snd_pcm_hw_params_free free
#define snd_pcm_sw_params_free free
#define snd_pcm_info_free free
#define snd_pcm_status_free free
static inline int snd_config_load_string(snd_config_t **out,const char *text,size_t size) {
    (void)size; *out=calloc(1,sizeof(**out)); if(!*out) return -ENOMEM;
    if(sscanf(text,"pcm.pt_selected { type hw card %u device %u subdevice %u }",&(*out)->card,&(*out)->device,&(*out)->subdevice)!=3) return -EINVAL;
    return 0;
}
static inline int snd_config_delete(snd_config_t *c) { free(c); return 0; }
static inline int snd_pcm_open_lconf(snd_pcm_t **out,const char *name,int stream,int mode,snd_config_t *c) {
    if(strcmp(name,"pt_selected") || stream!=SND_PCM_STREAM_CAPTURE || mode!=SND_PCM_NONBLOCK) return -EINVAL;
    if(pt_test_mode==9) return -ENODEV;
    *out=calloc(1,sizeof(**out)); if(!*out) return -ENOMEM;
    (*out)->card=c->card; (*out)->device=c->device; (*out)->subdevice=c->subdevice; return 0;
}
static inline int snd_pcm_info(snd_pcm_t *p,snd_pcm_info_t *i) { i->card=p->card;i->device=p->device;i->subdevice=p->subdevice;return 0; }
static inline const char *snd_pcm_info_get_id(const snd_pcm_info_t *i) { (void)i;return "TEST-FAKE"; }
static inline int snd_pcm_info_get_card(const snd_pcm_info_t *i) { return (int)i->card; }
static inline unsigned snd_pcm_info_get_device(const snd_pcm_info_t *i) { return i->device; }
static inline unsigned snd_pcm_info_get_subdevice(const snd_pcm_info_t *i) { return i->subdevice; }
static inline int snd_pcm_hw_params_any(snd_pcm_t *p,snd_pcm_hw_params_t *h) { (void)p;(void)h;return 0; }
static inline int snd_pcm_hw_params_set_rate_resample(snd_pcm_t *p,snd_pcm_hw_params_t *h,unsigned value) { (void)p;(void)h;return value?-EINVAL:0; }
static inline int snd_pcm_hw_params_set_access(snd_pcm_t *p,snd_pcm_hw_params_t *h,int v) { (void)p;h->access=v;return 0; }
static inline int snd_pcm_hw_params_set_format(snd_pcm_t *p,snd_pcm_hw_params_t *h,int v) { (void)p;h->format=v;return 0; }
static inline int snd_pcm_hw_params_set_channels(snd_pcm_t *p,snd_pcm_hw_params_t *h,unsigned v) { p->channels=v;h->channels=v;return 0; }
static inline int snd_pcm_hw_params_set_rate(snd_pcm_t *p,snd_pcm_hw_params_t *h,unsigned v,int dir) { if(dir)return -EINVAL;p->rate=v;h->rate=v;return 0; }
static inline int snd_pcm_hw_params_set_period_size_near(snd_pcm_t *p,snd_pcm_hw_params_t *h,snd_pcm_uframes_t *v,int *dir) { (void)p;*dir=0;if(pt_test_mode==10)*v=99999;h->period=*v;return 0; }
static inline int snd_pcm_hw_params_set_buffer_size_near(snd_pcm_t *p,snd_pcm_hw_params_t *h,snd_pcm_uframes_t *v) { (void)p;h->buffer=*v;return 0; }
static inline int snd_pcm_hw_params(snd_pcm_t *p,snd_pcm_hw_params_t *h) { (void)p;(void)h;return 0; }
static inline int snd_pcm_hw_params_current(snd_pcm_t *p,snd_pcm_hw_params_t *h) { (void)p;if(pt_test_mode==8)h->rate++;return 0; }
static inline int snd_pcm_hw_params_get_access(const snd_pcm_hw_params_t *h,int *v) { *v=h->access;return 0; }
static inline int snd_pcm_hw_params_get_format(const snd_pcm_hw_params_t *h,int *v) { *v=h->format;return 0; }
static inline int snd_pcm_hw_params_get_channels(const snd_pcm_hw_params_t *h,unsigned *v) { *v=h->channels;return 0; }
static inline int snd_pcm_hw_params_get_rate(const snd_pcm_hw_params_t *h,unsigned *v,int *dir) { *v=h->rate;*dir=0;return 0; }
static inline int snd_pcm_hw_params_get_period_size(const snd_pcm_hw_params_t *h,snd_pcm_uframes_t *v,int *dir) { *v=h->period;*dir=0;return 0; }
static inline int snd_pcm_hw_params_get_buffer_size(const snd_pcm_hw_params_t *h,snd_pcm_uframes_t *v) { *v=h->buffer;return 0; }
static inline int snd_pcm_sw_params_current(snd_pcm_t *p,snd_pcm_sw_params_t *s) { (void)p;(void)s;return 0; }
static inline int snd_pcm_sw_params_get_boundary(const snd_pcm_sw_params_t *s,snd_pcm_uframes_t *v) { (void)s;*v=1000000;return 0; }
static inline int snd_pcm_sw_params_set_start_threshold(snd_pcm_t *p,snd_pcm_sw_params_t *s,snd_pcm_uframes_t v) { (void)p;(void)s;return v==1000000?0:-EINVAL; }
static inline int snd_pcm_sw_params_set_avail_min(snd_pcm_t *p,snd_pcm_sw_params_t *s,snd_pcm_uframes_t v) { (void)p;(void)s;return v?0:-EINVAL; }
static inline int snd_pcm_sw_params_set_tstamp_mode(snd_pcm_t *p,snd_pcm_sw_params_t *s,int v) { (void)p;(void)s;return v==1?0:-EINVAL; }
static inline int snd_pcm_sw_params_set_tstamp_type(snd_pcm_t *p,snd_pcm_sw_params_t *s,int v) { (void)p;(void)s;return v==1?0:-EINVAL; }
static inline int snd_pcm_sw_params(snd_pcm_t *p,snd_pcm_sw_params_t *s) { (void)p;(void)s;return 0; }
static inline int snd_pcm_poll_descriptors_count(snd_pcm_t *p) { (void)p;return 2; }
static inline int snd_pcm_poll_descriptors(snd_pcm_t *p,struct pollfd *fds,unsigned count) { (void)p;if(count!=2)return -EINVAL;fds[0]=(struct pollfd){.fd=201,.events=POLLIN};fds[1]=(struct pollfd){.fd=202,.events=POLLIN};return 2; }
static inline int snd_pcm_poll_descriptors_revents(snd_pcm_t *p,struct pollfd *fds,unsigned count,unsigned short *events) { (void)p;if(count!=2 || fds[1].fd!=202)return -EINVAL;*events=(unsigned short)(fds[0].revents|fds[1].revents);return 0; }
static inline int snd_pcm_prepare(snd_pcm_t *p) { (void)p;return 0; }
static inline int snd_pcm_start(snd_pcm_t *p) { (void)p;return pt_test_mode==11?-EPIPE:0; }
static inline int snd_pcm_drop(snd_pcm_t *p) { (void)p;pt_test_drops++;return 0; }
static inline int snd_pcm_close(snd_pcm_t *p) { free(p);pt_test_audio_closes++;return 0; }
static inline int snd_pcm_state(snd_pcm_t *p) { (void)p;return pt_test_mode==3?SND_PCM_STATE_SUSPENDED:pt_test_mode==4?SND_PCM_STATE_DISCONNECTED:SND_PCM_STATE_XRUN; }
static inline snd_pcm_sframes_t snd_pcm_readi(snd_pcm_t *p,void *dst,snd_pcm_uframes_t frames) {
    p->reads++;
    if((pt_test_mode==1 || pt_test_mode==47) && p->reads==1)return -EAGAIN;
    if(pt_test_mode==39 && p->reads==1)return -EINTR;
    if(pt_test_mode==2)return -EPIPE;
    if(pt_test_mode==3)return -ESTRPIPE;
    if(pt_test_mode==4)return -ENODEV;
    if(frames<2)return -EINVAL;
    memset(dst,(int)p->reads,2*p->channels*2);return 2;
}
static inline void snd_pcm_status_set_audio_htstamp_config(snd_pcm_status_t *s,snd_pcm_audio_tstamp_config_t *c) { (void)s;if(c->type_requested!=1 || c->report_delay!=1)abort(); }
static inline int snd_pcm_status(snd_pcm_t *p,snd_pcm_status_t *s) { (void)p;(void)s;return pt_test_mode==13?-EINVAL:0; }
static inline int snd_pcm_status_get_state(const snd_pcm_status_t *s) { (void)s;return pt_test_mode==12?SND_PCM_STATE_XRUN:SND_PCM_STATE_RUNNING; }
static inline snd_pcm_uframes_t snd_pcm_status_get_avail(const snd_pcm_status_t *s) { (void)s;return 3; }
static inline snd_pcm_sframes_t snd_pcm_status_get_delay(const snd_pcm_status_t *s) { (void)s;return 4; }
static inline void snd_pcm_status_get_htstamp(const snd_pcm_status_t *s,snd_htimestamp_t *t) { (void)s;*t=(snd_htimestamp_t){.tv_sec=1,.tv_nsec=2}; }
static inline void snd_pcm_status_get_trigger_htstamp(const snd_pcm_status_t *s,snd_htimestamp_t *t) { (void)s;*t=(snd_htimestamp_t){0}; }
static inline void snd_pcm_status_get_audio_htstamp_report(const snd_pcm_status_t *s,snd_pcm_audio_tstamp_report_t *r) { (void)s;*r=(snd_pcm_audio_tstamp_report_t){0};if(pt_test_mode==7){r->valid=1;r->actual_type=1;r->accuracy_report=1;} }
static inline void snd_pcm_status_get_audio_htstamp(const snd_pcm_status_t *s,snd_htimestamp_t *t) { (void)s;*t=(snd_htimestamp_t){0}; }
#endif
