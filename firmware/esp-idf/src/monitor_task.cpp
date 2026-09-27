#include "poseidon/monitor_task.hpp"
#include "poseidon/nvs_boot_identity.hpp"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include <cstddef>
#include <limits>
#include <new>

namespace poseidon::reef {

bool EspMonotonicClock::read(ClockReading& output, std::int64_t& microseconds) noexcept {
    const auto now = esp_timer_get_time();
    if (now < 0 || (have_read_ && now < last_us_)) return false;
    ClockReading next;
    next.monotonic_s = static_cast<std::uint64_t>(now) / 1000000ULL;
    next.quality = telemetry::ClockQuality::unsynchronized;
    next.unix_s.reset();
    last_us_ = now;
    have_read_ = true;
    output = next;
    microseconds = now;
    return true;
}

bool checked_monitor_delay_us(std::int64_t now_us, std::uint64_t remaining_s,
                              std::uint64_t& output) noexcept {
    if (now_us < 0 || remaining_s > UINT64_MAX / 1000000ULL) return false;
    const auto fraction = static_cast<std::uint64_t>(now_us) % 1000000ULL;
    const auto delay = remaining_s ? remaining_s * 1000000ULL - fraction : 1ULL;
    if (delay == 0 || delay > static_cast<std::uint64_t>(INT64_MAX - now_us)) return false;
    output = delay;
    return true;
}

struct MonitorControl {
    explicit MonitorControl(Config config) noexcept : identity(true), runtime(identity, sensor, config) {}
    NvsBootIdentity identity;
    NoProviderSensor sensor;
    Runtime runtime;
    EspMonotonicClock clock;
    std::atomic<TaskHandle_t> worker{nullptr};
    std::atomic<bool> notify_enabled{false};
    std::atomic<std::uint32_t> notifiers{0};
    std::atomic<bool> notify_failed{false};
    std::atomic<bool> stop{false};
    std::atomic<MonitorPhase> phase{MonitorPhase::starting};
    std::atomic<MonitorError> error{MonitorError::none};
    std::atomic<RuntimeResult> runtime_result{RuntimeResult::not_due};
    std::atomic<JournalError> journal_error{JournalError::none};
    std::atomic<JournalError> cleanup_journal_error{JournalError::none};
    std::atomic<esp_err_t> sdk_error{ESP_OK};
    std::atomic<esp_err_t> cleanup_error{ESP_OK};
    std::atomic<std::uint32_t> samples{0}, dropped{0}, invalid{0}, coalesced{0}, queued{0};
    std::atomic<bool> saturated{false}, retained_resources{false}, retained_worker{false};
    // Timer handle and actual Runtime/identity are touched only by their worker.
    esp_timer_handle_t timer = nullptr;
    bool identity_touched = false;
};

namespace {
constexpr std::uint32_t worker_stack_bytes = 6144;
constexpr UBaseType_t worker_priority = 4;
static_assert(configTICK_RATE_HZ > 0, "worker waits need a positive tick rate");
static_assert(configTICK_RATE_HZ < portMAX_DELAY, "bounded wait must not mean forever");
constexpr TickType_t bounded_wait = static_cast<TickType_t>(configTICK_RATE_HZ);
constexpr unsigned shutdown_grace_iterations = 8;

// Deliberately no global NVS object/destructor: disabled paths never even
// construct the enabled allocator. The one placement-constructed control has
// process lifetime and is never freed or reused under queued/in-flight callbacks.
std::atomic<bool> slot_claimed{false};
alignas(MonitorControl) std::byte control_storage[sizeof(MonitorControl)];

bool terminal(MonitorPhase phase) noexcept {
    return phase == MonitorPhase::stopped || phase == MonitorPhase::faulted || phase == MonitorPhase::retained_fault;
}
void fail(MonitorControl& control, MonitorError error, esp_err_t sdk = ESP_OK) noexcept {
    auto expected = MonitorError::none;
    if (control.error.compare_exchange_strong(expected, error)) control.sdk_error.store(sdk);
}
void cleanup_failure(MonitorControl& control, MonitorError error, esp_err_t sdk) noexcept {
    control.cleanup_error.store(sdk);
    control.retained_resources.store(true);
    fail(control, error, sdk);
}
std::uint32_t mirror(std::uint64_t value, MonitorControl& control) noexcept {
    if (value > UINT32_MAX) { control.saturated.store(true); return UINT32_MAX; }
    return static_cast<std::uint32_t>(value);
}
void publish_runtime(MonitorControl& control) noexcept {
    const auto& statistics = control.runtime.statistics();
    control.samples.store(mirror(statistics.samples, control));
    control.dropped.store(mirror(statistics.dropped_newest, control));
    control.invalid.store(mirror(statistics.invalid_sensor_samples, control));
    control.queued.store(static_cast<std::uint32_t>(control.runtime.queued()));
    if (statistics.counters_saturated) control.saturated.store(true);
    control.journal_error.store(control.runtime.journal_error());
}

// Registration precedes the final gate check. After closing the gate, a worker
// waits for all registered gate-open callers before deleting its own task. A
// callback arriving later only reads this immortal control and cannot notify a
// stale TaskHandle_t. Bounded CAS retries keep ESP_TIMER_TASK callbacks short.
void notify_worker(MonitorControl& control) noexcept {
    auto count = control.notifiers.load();
    for (unsigned attempt = 0; attempt < 8; ++attempt) {
        if (count >= 64) break;
        if (control.notifiers.compare_exchange_weak(count, count + 1)) {
            if (control.notify_enabled.load()) {
                const auto worker = control.worker.load();
                if (!worker || xTaskNotifyGive(worker) != pdPASS) control.notify_failed.store(true);
            }
            control.notifiers.fetch_sub(1);
            return;
        }
    }
    control.notify_failed.store(true);
}
void timer_callback(void* argument) noexcept {
    // No clock, allocation, NVS, sampling, encoding, logging, or queue mutation.
    notify_worker(*static_cast<MonitorControl*>(argument));
}

void shutdown(MonitorControl& control) noexcept {
    control.phase.store(MonitorPhase::stopping);
    control.notify_enabled.store(false);
    bool can_delete_timer = control.timer != nullptr;
    if (control.timer) {
        const auto stopped = esp_timer_stop(control.timer);
        if (stopped != ESP_OK && stopped != ESP_ERR_INVALID_STATE) {
            cleanup_failure(control, MonitorError::timer_stop, stopped);
            can_delete_timer = false; // Uncertain armed state; never free callback storage.
        }
    }
    unsigned waited = 0;
    while (control.notifiers.load() != 0) {
        if (++waited >= shutdown_grace_iterations) {
            control.retained_worker.store(true);
            control.phase.store(MonitorPhase::retained_shutdown);
            // Explicit fail-closed retention: one worker and one static control.
            // Never delete a task still referenced by an in-flight notification.
            vTaskDelay(bounded_wait);
        } else {
            vTaskDelay(1);
        }
    }
    control.retained_worker.store(false);
    if (can_delete_timer) {
        // IDF5.3.1 esp_timer_delete queues EVENT_ID_DELETE_TIMER. It does not
        // join callbacks. Our gate/ref handshake and immortal arg provide that
        // application lifetime guarantee independently of deferred SDK deletion.
        const auto deleted = esp_timer_delete(control.timer);
        if (deleted != ESP_OK) cleanup_failure(control, MonitorError::timer_delete, deleted);
        else control.timer = nullptr;
    }
    if (control.identity_touched) {
        const auto closed = control.identity.close(); // Same worker that opened/allocated.
        if (closed != JournalError::none) {
            control.cleanup_journal_error.store(closed);
            cleanup_failure(control, MonitorError::identity_close, control.identity.last_esp_error());
        }
    }
    control.worker.store(nullptr);
    const auto error = control.error.load();
    control.phase.store(control.retained_resources.load() ? MonitorPhase::retained_fault :
        (error == MonitorError::none || error == MonitorError::cancelled ? MonitorPhase::stopped : MonitorPhase::faulted));
}

bool arm_next(MonitorControl& control) noexcept {
    ClockReading clock;
    std::int64_t now_us = 0;
    if (!control.clock.read(clock, now_us)) { fail(control, MonitorError::clock); return false; }
    std::uint64_t delay = 0;
    if (!checked_monitor_delay_us(now_us, control.runtime.sleep_remaining_s(clock.monotonic_s), delay)) {
        fail(control, MonitorError::clock); return false;
    }
    const auto started = esp_timer_start_once(control.timer, delay);
    if (started != ESP_OK) { fail(control, MonitorError::timer_start, started); return false; }
    return true;
}

void run_worker(MonitorControl& control) noexcept {
    if (control.stop.load()) { fail(control, MonitorError::cancelled); return; }
    control.worker.store(xTaskGetCurrentTaskHandle());
    if (!control.worker.load()) { fail(control, MonitorError::task_identity); return; }
    esp_timer_create_args_t args{};
    args.callback = &timer_callback;
    args.arg = &control;
    args.dispatch_method = ESP_TIMER_TASK;
    args.name = "reef_monitor_once";
    args.skip_unhandled_events = true;
    const auto created = esp_timer_create(&args, &control.timer);
    if (created != ESP_OK) { control.timer = nullptr; fail(control, MonitorError::timer_create, created); return; }
    if (control.stop.load()) { fail(control, MonitorError::cancelled); return; }
    ClockReading clock;
    std::int64_t now_us = 0;
    if (!control.clock.read(clock, now_us)) { fail(control, MonitorError::clock); return; }
    control.identity_touched = true;
    const auto opened = control.identity.open_existing();
    control.journal_error.store(opened);
    if (opened != JournalError::none) { fail(control, MonitorError::identity_open, control.identity.last_esp_error()); return; }
    if (control.stop.load()) { fail(control, MonitorError::cancelled); return; }
    if (!control.clock.read(clock, now_us)) { fail(control, MonitorError::clock); return; }
    const auto started = control.runtime.start(clock);
    control.runtime_result.store(started);
    control.journal_error.store(control.runtime.journal_error());
    if (started != RuntimeResult::ready) { fail(control, MonitorError::runtime_start, control.identity.last_esp_error()); return; }
    if (control.stop.load()) { fail(control, MonitorError::cancelled); return; }
    control.notify_enabled.store(true);
    control.phase.store(MonitorPhase::running);
    while (!control.stop.load()) {
        if (control.notify_failed.load()) { fail(control, MonitorError::notification); return; }
        if (!control.clock.read(clock, now_us)) { fail(control, MonitorError::clock); return; }
        const auto polled = control.runtime.poll(clock, PowerReading{});
        control.runtime_result.store(polled);
        publish_runtime(control);
        if (polled != RuntimeResult::sampled && polled != RuntimeResult::queue_full && polled != RuntimeResult::not_due) {
            fail(control, MonitorError::runtime_poll, control.identity.last_esp_error()); return;
        }
        if (control.stop.load()) break;
        if (!arm_next(control)) return;
        std::uint32_t notifications = 0;
        while (!control.stop.load() && !control.notify_failed.load() && notifications == 0)
            notifications = ulTaskNotifyTake(pdTRUE, bounded_wait);
        if (notifications > 1) {
            const auto old = control.coalesced.load();
            const auto extra = notifications - 1;
            if (extra > UINT32_MAX - old) { control.coalesced.store(UINT32_MAX); control.saturated.store(true); }
            else control.coalesced.store(old + extra);
        }
    }
}
void worker_entry(void* argument) noexcept {
    auto& control = *static_cast<MonitorControl*>(argument);
    run_worker(control);
    shutdown(control);
    vTaskDelete(nullptr); // Self-delete only, after gate/ref and owned cleanup.
}
} // namespace

MonitorTask::~MonitorTask() {
    if (!enabled_) return;
    stop_.store(true);
    if (auto* control = control_.load()) control->stop.store(true);
    // No notification/SDK call from a destructor. Bounded worker waits observe
    // this request; the worker's state/providers are not members of this handle.
}
MonitorError MonitorTask::start(Config config) noexcept {
    if (!enabled_) return MonitorError::disabled;
    bool expected = false;
    if (!attempted_.compare_exchange_strong(expected, true)) return MonitorError::already_started;
    if (stop_.load()) { local_error_.store(MonitorError::cancelled); return MonitorError::cancelled; }
    if (!valid_config(config)) { local_error_.store(MonitorError::invalid_config); return MonitorError::invalid_config; }
    expected = false;
    if (!slot_claimed.compare_exchange_strong(expected, true)) { local_error_.store(MonitorError::slot_used); return MonitorError::slot_used; }
    auto* control = new (control_storage) MonitorControl(config);
    control_.store(control);
    if (stop_.load()) control->stop.store(true);
    const auto created = xTaskCreate(&worker_entry, "reef_monitor", worker_stack_bytes,
                                    control, worker_priority, nullptr);
    if (created != pdPASS) {
        fail(*control, MonitorError::task_create, ESP_ERR_NO_MEM);
        control->phase.store(MonitorPhase::faulted);
        return MonitorError::task_create;
    }
    return MonitorError::none;
}
void MonitorTask::request_stop() noexcept {
    if (!enabled_) return;
    stop_.store(true);
    if (auto* control = control_.load()) control->stop.store(true);
    // Pure atomic request: no caller can block in or race a task-notify SDK
    // call. The worker's fixed one-second maximum wait observes the stop flag.
}
MonitorSnapshot MonitorTask::snapshot() const noexcept {
    MonitorSnapshot result;
    if (!enabled_) { result.error = MonitorError::disabled; return result; }
    result.io_enabled = true;
    result.stop_requested = stop_.load();
    auto* control = control_.load();
    if (!control) {
        result.error = local_error_.load();
        result.phase = result.error == MonitorError::none ? MonitorPhase::idle : MonitorPhase::rejected;
        return result;
    }
    result.phase = control->phase.load();
    result.error = control->error.load();
    result.runtime_result = control->runtime_result.load();
    result.journal_error = control->journal_error.load();
    result.cleanup_journal_error = control->cleanup_journal_error.load();
    result.sdk_error = control->sdk_error.load();
    result.cleanup_error = control->cleanup_error.load();
    result.samples = control->samples.load(); result.dropped_newest = control->dropped.load();
    result.invalid_sensor_samples = control->invalid.load(); result.coalesced_notifications = control->coalesced.load();
    result.queued = control->queued.load(); result.diagnostic_saturated = control->saturated.load();
    result.retained_resources = control->retained_resources.load(); result.retained_worker = control->retained_worker.load();
    result.stop_requested = control->stop.load();
    return result;
}
bool MonitorTask::peek_stopped(telemetry::Frame& output) const noexcept {
    if (!enabled_) return false;
    const auto* control = control_.load();
    if (!control || !terminal(control->phase.load())) return false;
    const auto* frame = control->runtime.front();
    if (!frame) return false;
    output = *frame;
    return true;
}

} // namespace poseidon::reef
