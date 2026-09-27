#ifndef PT_FAKE_SYSTEM_H
#define PT_FAKE_SYSTEM_H
#ifndef PT_TEST_FAKE
#error "Injected systems are TEST-FAKE only"
#endif
#include <poll.h>
#include <time.h>
#include <stdint.h>
#ifndef ESTRPIPE
#define ESTRPIPE 86
#endif
#ifndef EBADFD
#define EBADFD 77
#endif
extern uint32_t pt_test_mode, pt_test_poll_count, pt_test_closes, pt_test_maps, pt_test_unmaps;
extern uint32_t pt_test_streamoffs, pt_test_releases, pt_test_audio_closes, pt_test_drops;
void pt_test_reset(uint32_t mode);
uint32_t pt_test_counter(uint32_t index);
int pt_test_poll(struct pollfd *, nfds_t, int);
int pt_test_clock_gettime(clockid_t, struct timespec *);
int pt_test_close(int);
#define poll pt_test_poll
#define clock_gettime pt_test_clock_gettime
#define close pt_test_close
#endif
