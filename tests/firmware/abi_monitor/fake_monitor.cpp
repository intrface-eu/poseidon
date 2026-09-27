#include "fake_monitor.hpp"
#include "esp_partition.h"
#include "nvs_flash.h"

#include <array>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <thread>

struct FakeTask { std::thread thread; std::uint32_t notifications = 0; bool deleted = false; };
struct FakeTimer { esp_timer_create_args_t args{}; bool active = false; bool delete_pending = false; };

namespace {
using namespace std::chrono_literals;
struct State {
    std::mutex mutex;
    std::condition_variable changed;
    fake_monitor::Settings settings;
    fake_monitor::Statistics stats;
    std::unique_ptr<FakeTask> task;
    std::unique_ptr<FakeTimer> timer;
    std::int64_t time = 0;
    bool nvs_initialized = false;
    bool nvs_open = false;
    nvs_open_mode_t mode = NVS_READONLY;
    std::array<std::uint8_t, 32> record{};
    esp_partition_t partition{ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_NVS,
        0x3f0000, 0x10000, "reef_state", false, false};
} state;
FakeTask main_context;
FakeTask timer_context;
thread_local TaskHandle_t current = &main_context;

void sdk() { ++state.stats.sdk_calls; state.changed.notify_all(); }
void nvs_call() {
    sdk(); ++state.stats.nvs_calls;
    if (current == &timer_context) ++state.stats.clock_or_nvs_in_callback;
    if (!state.task || current != state.task.get()) ++state.stats.wrong_nvs_owner;
}
bool text(const char* actual, const char* expected) { return actual && std::strcmp(actual, expected) == 0; }
std::array<std::uint8_t, 32> synthetic_record(std::uint64_t floor) {
    std::array<std::uint8_t, 32> bytes{};
    bytes[0] = 'R'; bytes[1] = 'N'; bytes[2] = 'V'; bytes[3] = 'S'; bytes[4] = 1; bytes[5] = 1;
    for (unsigned i = 0; i < 8; ++i) {
        bytes[8 + i] = static_cast<std::uint8_t>(floor >> (i * 8));
        bytes[16 + i] = static_cast<std::uint8_t>(~floor >> (i * 8));
    }
    std::uint32_t crc = UINT32_MAX;
    for (unsigned i = 0; i < 24; ++i) {
        crc ^= bytes[i];
        for (unsigned bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1U)));
    }
    crc = ~crc;
    for (unsigned i = 0; i < 4; ++i) bytes[24 + i] = static_cast<std::uint8_t>(crc >> (i * 8));
    return bytes;
}
template<class Predicate>
void require_wait(std::unique_lock<std::mutex>& lock, const Predicate& condition) {
    if (!state.changed.wait_for(lock, 2s, condition)) throw std::runtime_error("bounded fake ABI wait expired");
}
}

namespace fake_monitor {
void configure(Settings settings) {
    std::lock_guard<std::mutex> lock(state.mutex);
    state.settings = settings;
    state.record = synthetic_record(0); // Explicit synthetic pre-existing RNVS test state.
}
void set_time(std::int64_t microseconds) { std::lock_guard<std::mutex> lock(state.mutex); state.time = microseconds; }
void release_task_entry() { std::lock_guard<std::mutex> lock(state.mutex); state.settings.hold_task_entry = false; state.changed.notify_all(); }
void release_task_create() { std::lock_guard<std::mutex> lock(state.mutex); state.settings.hold_task_create_return = false; state.changed.notify_all(); }
void release_notification() { std::lock_guard<std::mutex> lock(state.mutex); state.settings.hold_notification = false; state.changed.notify_all(); }
void release_notification_take() { std::lock_guard<std::mutex> lock(state.mutex); state.settings.hold_notification_take = false; state.changed.notify_all(); }
void release_timer_start() { std::lock_guard<std::mutex> lock(state.mutex); state.settings.hold_timer_start = false; state.changed.notify_all(); }
void seed_notifications(std::uint32_t count) { std::lock_guard<std::mutex> lock(state.mutex); state.task->notifications = count; state.changed.notify_all(); }
Statistics statistics() {
    std::lock_guard<std::mutex> lock(state.mutex);
    auto result = state.stats;
    result.timer_active = state.timer && state.timer->active;
    result.timer_delete_pending = state.timer && state.timer->delete_pending;
    return result;
}
SelectedCallback select_expired_callback() {
    std::lock_guard<std::mutex> lock(state.mutex);
    if (!state.timer || !state.timer->active) throw std::runtime_error("no armed fake one-shot to expire");
    state.timer->active = false;
    return {state.timer->args.callback, state.timer->args.arg};
}
void invoke(SelectedCallback callback) {
    const auto saved = current;
    current = &timer_context;
    callback.callback(callback.argument);
    current = saved;
}
void fire() { invoke(select_expired_callback()); }
void wait_timer_starts(unsigned count) {
    std::unique_lock<std::mutex> lock(state.mutex);
    require_wait(lock, [&] { return state.stats.timer_starts >= count; });
}
void wait_notify_entries(unsigned count) {
    std::unique_lock<std::mutex> lock(state.mutex);
    require_wait(lock, [&] { return state.stats.notify_entries >= count; });
}
void wait_task_created() {
    std::unique_lock<std::mutex> lock(state.mutex);
    require_wait(lock, [&] { return state.stats.task_creates > 0; });
}
void join_worker() {
    {
        std::unique_lock<std::mutex> lock(state.mutex);
        require_wait(lock, [&] { return state.stats.worker_finished; });
    }
    if (state.task && state.task->thread.joinable()) state.task->thread.join();
}
}

extern "C" {
BaseType_t xTaskCreate(TaskFunction_t entry, const char* name, std::uint32_t stack,
                       void* argument, UBaseType_t priority, TaskHandle_t* output) {
    std::unique_lock<std::mutex> lock(state.mutex);
    sdk(); ++state.stats.task_creates;
    if (!text(name, "reef_monitor") || stack != 6144 || priority != 4 || state.task || state.settings.fail_task_create) return pdFAIL;
    state.task = std::make_unique<FakeTask>();
    auto* task = state.task.get();
    if (output) *output = task;
    task->thread = std::thread([task, entry, argument] {
        current = task;
        {
            std::unique_lock<std::mutex> held(state.mutex);
            require_wait(held, [] { return !state.settings.hold_task_entry; });
        }
        entry(argument); // ACTUAL MonitorTask worker implementation.
        std::lock_guard<std::mutex> held(state.mutex);
        state.stats.worker_finished = true;
        state.changed.notify_all();
    });
    state.changed.notify_all();
    require_wait(lock, [] { return !state.settings.hold_task_create_return; });
    return pdPASS;
}
TaskHandle_t xTaskGetCurrentTaskHandle() { std::lock_guard<std::mutex> lock(state.mutex); sdk(); return current; }
BaseType_t xTaskGenericNotify(TaskHandle_t task, UBaseType_t index, std::uint32_t value,
                              eNotifyAction action, std::uint32_t* previous) {
    std::unique_lock<std::mutex> lock(state.mutex);
    sdk(); ++state.stats.notify_entries; state.changed.notify_all();
    require_wait(lock, [] { return !state.settings.hold_notification; });
    if (!task || !state.task || task != state.task.get() || task->deleted) {
        ++state.stats.dangling_notifications; return pdFAIL;
    }
    if (index || value || action != eIncrement || previous || state.settings.fail_notification) return pdFAIL;
    if (task->notifications != UINT32_MAX) ++task->notifications;
    ++state.stats.notifications;
    state.changed.notify_all();
    return pdPASS;
}
std::uint32_t ulTaskGenericNotifyTake(UBaseType_t index, BaseType_t clear, TickType_t ticks) {
    std::unique_lock<std::mutex> lock(state.mutex);
    sdk();
    if (index || clear != pdTRUE || ticks == 0 || ticks > configTICK_RATE_HZ || current != state.task.get()) ++state.stats.bad_waits;
    state.changed.wait_for(lock, 2ms, [] { return !state.settings.hold_notification_take && state.task->notifications > 0; });
    if (state.settings.hold_notification_take) return 0;
    const auto result = state.task->notifications;
    if (clear) state.task->notifications = 0;
    return result;
}
void vTaskDelay(TickType_t ticks) {
    std::unique_lock<std::mutex> lock(state.mutex);
    sdk();
    if (ticks == 0 || ticks > configTICK_RATE_HZ) ++state.stats.bad_waits;
    state.changed.wait_for(lock, 1ms); // Deterministic scheduling barrier, not target timing evidence.
}
void vTaskDelete(TaskHandle_t task) {
    std::lock_guard<std::mutex> lock(state.mutex);
    sdk(); ++state.stats.task_deletes;
    if (task != nullptr || current != state.task.get()) ++state.stats.external_task_deletes;
    else state.task->deleted = true;
    state.changed.notify_all();
}

esp_err_t esp_timer_create(const esp_timer_create_args_t* args, esp_timer_handle_t* output) {
    std::lock_guard<std::mutex> lock(state.mutex);
    sdk(); ++state.stats.timer_creates;
    if (state.settings.timer_create_error != ESP_OK) return state.settings.timer_create_error;
    if (!args || !output || !args->callback || !args->arg || args->dispatch_method != ESP_TIMER_TASK || !args->skip_unhandled_events || state.timer) return ESP_ERR_INVALID_ARG;
    state.timer = std::make_unique<FakeTimer>();
    state.timer->args = *args;
    *output = state.timer.get();
    return ESP_OK;
}
esp_err_t esp_timer_start_once(esp_timer_handle_t timer, std::uint64_t delay) {
    std::unique_lock<std::mutex> lock(state.mutex);
    sdk(); ++state.stats.timer_starts;
    state.stats.last_delay_us = delay;
    state.changed.notify_all();
    require_wait(lock, [] { return !state.settings.hold_timer_start; });
    if (state.settings.timer_start_error != ESP_OK) return state.settings.timer_start_error;
    if (!timer || timer != state.timer.get() || timer->active || timer->delete_pending || delay == 0) return ESP_ERR_INVALID_STATE;
    timer->active = true;
    return ESP_OK;
}
esp_err_t esp_timer_stop(esp_timer_handle_t timer) {
    std::lock_guard<std::mutex> lock(state.mutex);
    sdk(); ++state.stats.timer_stops;
    if (state.settings.timer_stop_error != ESP_OK) return state.settings.timer_stop_error;
    if (!timer || timer != state.timer.get() || !timer->active) return ESP_ERR_INVALID_STATE;
    timer->active = false;
    return ESP_OK;
}
esp_err_t esp_timer_delete(esp_timer_handle_t timer) {
    std::lock_guard<std::mutex> lock(state.mutex);
    sdk(); ++state.stats.timer_deletes;
    if (state.settings.timer_delete_error != ESP_OK) return state.settings.timer_delete_error;
    if (!timer || timer != state.timer.get() || timer->active) return ESP_ERR_INVALID_STATE;
    timer->delete_pending = true; // Deliberately NOT a callback join/free barrier.
    return ESP_OK;
}
std::int64_t esp_timer_get_time() {
    std::lock_guard<std::mutex> lock(state.mutex);
    sdk(); ++state.stats.time_reads;
    if (current == &timer_context) ++state.stats.clock_or_nvs_in_callback;
    return state.time;
}

const esp_partition_t* esp_partition_find_first(esp_partition_type_t type, esp_partition_subtype_t subtype, const char* label) {
    std::lock_guard<std::mutex> lock(state.mutex);
    nvs_call();
    if (state.settings.missing_partition || type != ESP_PARTITION_TYPE_DATA || subtype != ESP_PARTITION_SUBTYPE_DATA_NVS || !text(label, "reef_state")) return nullptr;
    return &state.partition;
}
esp_err_t esp_partition_read(const esp_partition_t* partition, std::size_t offset, void* output, std::size_t length) {
    std::lock_guard<std::mutex> lock(state.mutex);
    nvs_call();
    if (partition != &state.partition || !output || length > 256 || offset + length > partition->size) return ESP_ERR_INVALID_ARG;
    std::memset(output, 0xff, length);
    if (!state.settings.erased_partition && offset == 0 && length) static_cast<std::uint8_t*>(output)[0] = 0x42;
    return ESP_OK;
}
esp_err_t nvs_get_stats(const char* label, nvs_stats_t*) {
    std::lock_guard<std::mutex> lock(state.mutex);
    nvs_call();
    if (!text(label, "reef_state")) return ESP_ERR_NVS_PART_NOT_FOUND;
    return state.nvs_initialized ? ESP_OK : ESP_ERR_NVS_NOT_INITIALIZED;
}
esp_err_t nvs_flash_init_partition(const char* label) {
    std::lock_guard<std::mutex> lock(state.mutex);
    nvs_call();
    if (!text(label, "reef_state")) return ESP_ERR_NVS_PART_NOT_FOUND;
    if (state.settings.nvs_init_error != ESP_OK) return state.settings.nvs_init_error;
    state.nvs_initialized = true;
    return ESP_OK;
}
esp_err_t nvs_open_from_partition(const char* label, const char* name, nvs_open_mode_t mode, nvs_handle_t* output) {
    std::lock_guard<std::mutex> lock(state.mutex);
    nvs_call();
    if (!text(label, "reef_state") || !text(name, "reef_boot") || !state.nvs_initialized || !output) return ESP_ERR_INVALID_ARG;
    state.mode = mode; state.nvs_open = true; *output = 7;
    return ESP_OK;
}
esp_err_t nvs_get_blob(nvs_handle_t handle, const char* key, void* output, std::size_t* length) {
    std::lock_guard<std::mutex> lock(state.mutex);
    nvs_call();
    if (handle != 7 || !state.nvs_open || !text(key, "identity_v1") || !length) return ESP_ERR_INVALID_ARG;
    if (state.settings.missing_record) return ESP_ERR_NVS_NOT_FOUND;
    if (!output) { *length = state.record.size(); return ESP_OK; }
    if (*length < state.record.size()) return ESP_ERR_NVS_INVALID_LENGTH;
    std::memcpy(output, state.record.data(), state.record.size()); *length = state.record.size();
    return ESP_OK;
}
esp_err_t nvs_set_blob(nvs_handle_t handle, const char* key, const void* input, std::size_t length) {
    std::lock_guard<std::mutex> lock(state.mutex);
    nvs_call(); ++state.stats.nvs_sets;
    if (handle != 7 || !state.nvs_open || state.mode != NVS_READWRITE || !text(key, "identity_v1") || !input || length != 32) return ESP_ERR_INVALID_ARG;
    std::memcpy(state.record.data(), input, length); // Models possible early writes.
    state.stats.floor = 0;
    for (unsigned i = 0; i < 8; ++i) state.stats.floor |= static_cast<std::uint64_t>(state.record[8 + i]) << (8 * i);
    return state.settings.nvs_set_error;
}
esp_err_t nvs_commit(nvs_handle_t handle) {
    std::lock_guard<std::mutex> lock(state.mutex);
    nvs_call(); ++state.stats.nvs_commits;
    return handle == 7 && state.nvs_open ? state.settings.nvs_commit_error : ESP_ERR_INVALID_ARG;
}
void nvs_close(nvs_handle_t handle) {
    std::lock_guard<std::mutex> lock(state.mutex);
    nvs_call(); ++state.stats.nvs_closes;
    if (handle != 7 || !state.nvs_open) ++state.stats.wrong_nvs_owner;
    state.nvs_open = false;
}
esp_err_t nvs_flash_deinit_partition(const char* label) {
    std::lock_guard<std::mutex> lock(state.mutex);
    nvs_call(); ++state.stats.nvs_deinits;
    if (!text(label, "reef_state")) return ESP_ERR_INVALID_ARG;
    if (state.settings.nvs_deinit_error != ESP_OK) return state.settings.nvs_deinit_error;
    state.nvs_initialized = false;
    return ESP_OK;
}
}
