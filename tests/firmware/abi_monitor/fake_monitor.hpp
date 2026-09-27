#pragma once
#include "esp_timer.h"
#include "freertos/task.h"
#include <cstdint>

namespace fake_monitor {
struct Settings {
    bool fail_task_create = false;
    bool hold_task_entry = false;
    bool hold_task_create_return = false;
    bool hold_notification = false;
    bool hold_notification_take = false;
    bool hold_timer_start = false;
    bool fail_notification = false;
    bool missing_partition = false;
    bool missing_record = false;
    bool erased_partition = false;
    esp_err_t timer_create_error = ESP_OK;
    esp_err_t timer_start_error = ESP_OK;
    esp_err_t timer_stop_error = ESP_OK;
    esp_err_t timer_delete_error = ESP_OK;
    esp_err_t nvs_init_error = ESP_OK;
    esp_err_t nvs_set_error = ESP_OK;
    esp_err_t nvs_commit_error = ESP_OK;
    esp_err_t nvs_deinit_error = ESP_OK;
};
struct Statistics {
    unsigned sdk_calls = 0;
    unsigned task_creates = 0;
    unsigned task_deletes = 0;
    unsigned external_task_deletes = 0;
    unsigned timer_creates = 0;
    unsigned timer_starts = 0;
    unsigned timer_stops = 0;
    unsigned timer_deletes = 0;
    unsigned time_reads = 0;
    unsigned notifications = 0;
    unsigned notify_entries = 0;
    unsigned dangling_notifications = 0;
    unsigned clock_or_nvs_in_callback = 0;
    unsigned nvs_calls = 0;
    unsigned nvs_sets = 0;
    unsigned nvs_commits = 0;
    unsigned nvs_closes = 0;
    unsigned nvs_deinits = 0;
    unsigned wrong_nvs_owner = 0;
    unsigned bad_waits = 0;
    std::uint64_t last_delay_us = 0;
    std::uint64_t floor = 0;
    bool timer_active = false;
    bool worker_finished = false;
    bool timer_delete_pending = false;
};
struct SelectedCallback { esp_timer_cb_t callback = nullptr; void* argument = nullptr; };
void configure(Settings settings);
void set_time(std::int64_t microseconds);
void release_task_entry();
void release_task_create();
void release_notification();
void release_notification_take();
void release_timer_start();
void seed_notifications(std::uint32_t count);
Statistics statistics();
SelectedCallback select_expired_callback();
void invoke(SelectedCallback callback);
void fire();
void wait_timer_starts(unsigned count);
void wait_notify_entries(unsigned count);
void wait_task_created();
void join_worker();
}
