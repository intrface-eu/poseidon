#pragma once
#include "esp_err.h"
#include <cstdint>
struct FakeTimer;
using esp_timer_handle_t = FakeTimer*;
using esp_timer_cb_t = void (*)(void*);
enum esp_timer_dispatch_t { ESP_TIMER_TASK, ESP_TIMER_MAX };
struct esp_timer_create_args_t {
    esp_timer_cb_t callback;
    void* arg;
    esp_timer_dispatch_t dispatch_method;
    const char* name;
    bool skip_unhandled_events;
};
extern "C" {
esp_err_t esp_timer_create(const esp_timer_create_args_t*, esp_timer_handle_t*);
esp_err_t esp_timer_start_once(esp_timer_handle_t, std::uint64_t);
esp_err_t esp_timer_stop(esp_timer_handle_t);
esp_err_t esp_timer_delete(esp_timer_handle_t);
std::int64_t esp_timer_get_time();
}
