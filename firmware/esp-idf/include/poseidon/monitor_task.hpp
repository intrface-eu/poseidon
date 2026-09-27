#pragma once

#include "poseidon/reef.hpp"
#include "esp_err.h"
#include <atomic>
#include <cstdint>

namespace poseidon::reef {

class NoProviderSensor final : public Sensor {
public:
    SensorReading sample() noexcept override { return {}; }
};

// Only the worker calls read(). A device clock enum is never UTC evidence.
class EspMonotonicClock final {
public:
    bool read(ClockReading& output, std::int64_t& microseconds) noexcept;
private:
    bool have_read_ = false;
    std::int64_t last_us_ = 0;
};

// Pure checked arithmetic; output is unchanged on failure. Zero seconds means
// an immediate 1us one-shot, not a backlog of inferred historical samples.
bool checked_monitor_delay_us(std::int64_t now_us, std::uint64_t remaining_s,
                              std::uint64_t& output) noexcept;

enum class MonitorPhase : std::uint32_t {
    disabled, idle, starting, running, stopping, retained_shutdown,
    stopped, faulted, retained_fault, rejected
};
enum class MonitorError : std::uint32_t {
    none, disabled, invalid_config, already_started, slot_used, cancelled,
    task_create, task_identity, timer_create, identity_open, clock,
    runtime_start, runtime_poll, timer_start, timer_stop, timer_delete,
    identity_close, notification
};

struct MonitorSnapshot {
    MonitorPhase phase = MonitorPhase::disabled;
    MonitorError error = MonitorError::none;
    RuntimeResult runtime_result = RuntimeResult::not_due;
    JournalError journal_error = JournalError::none;
    JournalError cleanup_journal_error = JournalError::none;
    esp_err_t sdk_error = ESP_OK;
    esp_err_t cleanup_error = ESP_OK;
    // Atomic 32-bit diagnostic mirrors saturate independently of Runtime's
    // existing 64-bit counters. diagnostic_saturated says information was clipped.
    std::uint32_t samples = 0;
    std::uint32_t dropped_newest = 0;
    std::uint32_t invalid_sensor_samples = 0;
    std::uint32_t coalesced_notifications = 0;
    std::uint32_t queued = 0;
    bool diagnostic_saturated = false;
    bool retained_resources = false;
    bool retained_worker = false;
    bool stop_requested = false;
    bool io_enabled = false;
    // No sensor/power/transport provider exists in this slice.
    bool sensor_provider = false;
    bool power_provider = false;
    std::uint32_t delivered = 0;
};

struct MonitorControl;

// Handle only: SDK callbacks/task never retain this object's address. The one
// enabled monitor owns a bounded process-lifetime control slot. Restart/reuse is
// rejected even after clean stop; a new boot/process is required. No heap context
// or caller-owned provider can be destroyed under a worker or a late callback.
class MonitorTask final {
public:
    explicit MonitorTask(bool enabled = false) noexcept : enabled_(enabled) {}
    ~MonitorTask(); // Requests stop with atomics only; does not wait or call SDK.
    MonitorTask(const MonitorTask&) = delete;
    MonitorTask& operator=(const MonitorTask&) = delete;
    MonitorTask(MonitorTask&&) = delete;
    MonitorTask& operator=(MonitorTask&&) = delete;

    // none means worker creation accepted, not that NVS/startup succeeded.
    MonitorError start(Config config = {}) noexcept;
    // Nonblocking stop request. Inspect snapshot; never free/delete a worker
    // after a caller timeout. An in-flight notifier may retain the worker safely.
    void request_stop() noexcept;
    MonitorSnapshot snapshot() const noexcept;
    // Diagnostic copy only after the worker published terminal state. No pop,
    // encoding-as-delivery claim, transport, or mutable queue access is exposed.
    bool peek_stopped(telemetry::Frame& output) const noexcept;
private:
    const bool enabled_;
    std::atomic<bool> attempted_{false};
    std::atomic<bool> stop_{false};
    std::atomic<MonitorControl*> control_{nullptr};
    std::atomic<MonitorError> local_error_{MonitorError::none};
};

} // namespace poseidon::reef
