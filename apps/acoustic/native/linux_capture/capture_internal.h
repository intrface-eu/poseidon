#ifndef PT_CAPTURE_INTERNAL_H
#define PT_CAPTURE_INTERNAL_H
#if !defined(__linux__) && !defined(PT_TEST_FAKE)
#error "This implementation requires Linux or explicit injected TEST-FAKE headers"
#endif
#include "capture_abi.h"
#include <errno.h>
#include <limits.h>
#include <poll.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#ifdef PT_TEST_FAKE
#include "fake_system.h"
#endif
#define PT_INIT(p) do { memset((p), 0, sizeof(*(p))); (p)->abi_version = PT_ABI_VERSION; (p)->struct_size = sizeof(*(p)); } while (0)
#define PT_HEADER(p) ((p) && (p)->abi_version == PT_ABI_VERSION && (p)->struct_size == sizeof(*(p)))
static inline int32_t pt_fail(pt_error *e, uint32_t domain, int32_t code) {
    if (e) { PT_INIT(e); e->domain = domain; e->code = code; }
    return PT_FAULT;
}
static inline void pt_clear_error(pt_error *e) { if (e) PT_INIT(e); }
static inline int64_t pt_now(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t) < 0) return -1;
    if (t.tv_sec < 0 || t.tv_nsec < 0 || t.tv_nsec >= 1000000000 ||
        (uint64_t)t.tv_sec > ((uint64_t)INT64_MAX - (uint64_t)t.tv_nsec) / UINT64_C(1000000000)) {
        errno = EOVERFLOW; return -1;
    }
    return (int64_t)t.tv_sec * INT64_C(1000000000) + (int64_t)t.tv_nsec;
}
static inline int32_t pt_make_deadline(int64_t before, uint32_t timeout_ms, int64_t *out, pt_error *e) {
    int64_t delta = (int64_t)timeout_ms * INT64_C(1000000);
    if (!out || before < 0 || !timeout_ms || timeout_ms > 60000 || before > INT64_MAX - delta)
        return pt_fail(e, PT_DOMAIN_CONTRACT, EOVERFLOW);
    *out = before + delta;
    return PT_OK;
}
/* No retry resets the deadline. last_seen spans EAGAIN/EINTR and repeated waits. */
static inline int32_t pt_wait(struct pollfd *fds, uint32_t count, int32_t cancel_fd,
                              int64_t *last_seen, int64_t deadline, pt_error *e) {
    if (cancel_fd < 0 || !count || count > 64 || !last_seen || *last_seen < 0 || deadline < 0)
        return pt_fail(e, PT_DOMAIN_CONTRACT, EINVAL);
    fds[count] = (struct pollfd){.fd=cancel_fd, .events=POLLIN};
    for (;;) {
        int64_t now = pt_now();
        if (now < 0) return pt_fail(e, PT_DOMAIN_ERRNO, errno);
        if (now < *last_seen) return pt_fail(e, PT_DOMAIN_CONTRACT, EIO);
        *last_seen = now;
        if (now >= deadline) return PT_AGAIN;
        int64_t difference = deadline - now;
        int64_t rounded_ms = difference / 1000000 + (difference % 1000000 != 0);
        int remaining = rounded_ms > INT_MAX ? INT_MAX : (int)rounded_ms;
        for (uint32_t i=0; i<=count; i++) fds[i].revents = 0;
        int rc = poll(fds, count + 1, remaining);
        if (rc < 0) { if (errno == EINTR) continue; return pt_fail(e, PT_DOMAIN_ERRNO, errno); }
        if (rc == 0) return PT_AGAIN;
        if (fds[count].revents & (POLLIN | POLLHUP)) return PT_CANCELLED;
        if (fds[count].revents) return pt_fail(e, PT_DOMAIN_ERRNO, EBADF);
        return PT_OK;
    }
}
static inline int pt_literal(const char *s, size_t capacity) {
    return s && s[0] && memchr(s, 0, capacity) != NULL;
}
#endif
