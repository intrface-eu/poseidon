#include "poseidon/monitor_task.hpp"
#include "fake_monitor.hpp"
#include "nvs.h"

#include <chrono>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>

extern "C" void app_main();

using namespace poseidon::reef;
namespace fake = fake_monitor;
namespace {
#define CHECK(condition) do { if (!(condition)) throw std::runtime_error(#condition); } while (false)
Config short_config(std::size_t capacity = 2) {
    Config config;
    config.normal_interval_s = 1; config.conserve_interval_s = 1; config.critical_interval_s = 1;
    config.queue_capacity = capacity;
    return config;
}
void join_clean() {
    fake::join_worker();
    const auto stats = fake::statistics();
    CHECK(stats.task_deletes == 1);
    CHECK(stats.external_task_deletes == 0);
    CHECK(stats.dangling_notifications == 0);
    CHECK(stats.clock_or_nvs_in_callback == 0);
    CHECK(stats.wrong_nvs_owner == 0);
    CHECK(stats.bad_waits == 0);
}
void stop_clean(MonitorTask& monitor) {
    monitor.request_stop();
    join_clean();
    CHECK(monitor.snapshot().phase == MonitorPhase::stopped);
    CHECK(!monitor.snapshot().retained_resources);
    CHECK(!monitor.snapshot().retained_worker);
}
void wait_retained(MonitorTask& monitor) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(1);
    while (std::chrono::steady_clock::now() < deadline) {
        if (monitor.snapshot().phase == MonitorPhase::retained_shutdown) return;
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    throw std::runtime_error("retained-shutdown state not published within host test deadline");
}
void disabled_zero_sdk() {
    fake::configure({});
    {
        MonitorTask monitor;
        Config invalid; invalid.normal_interval_s = 0;
        CHECK(monitor.start(invalid) == MonitorError::disabled);
        CHECK(monitor.start() == MonitorError::disabled);
        monitor.request_stop();
        CHECK(monitor.snapshot().phase == MonitorPhase::disabled);
        poseidon::telemetry::Frame frame; frame.boot_id = 99;
        CHECK(!monitor.peek_stopped(frame)); CHECK(frame.boot_id == 99);
    }
    CHECK(fake::statistics().sdk_calls == 0);
}
void target_disabled_zero_sdk() {
    fake::configure({}); app_main(); CHECK(fake::statistics().sdk_calls == 0);
}
void target_persisted_runs_actual_worker() {
    fake::Settings settings; settings.timer_start_error = ESP_FAIL; fake::configure(settings);
    app_main(); join_clean();
    CHECK(fake::statistics().task_creates == 1 && fake::statistics().timer_creates == 1);
    CHECK(fake::statistics().nvs_sets == 1 && fake::statistics().nvs_commits == 1 && fake::statistics().floor == 1);
    CHECK(fake::statistics().timer_starts == 1 && fake::statistics().nvs_deinits == 1);
}
void enabled_invalid_config_zero_sdk() {
    fake::configure({});
    { MonitorTask monitor(true); Config config; config.queue_capacity = 17;
      CHECK(monitor.start(config) == MonitorError::invalid_config);
      CHECK(monitor.snapshot().phase == MonitorPhase::rejected);
      monitor.request_stop(); }
    CHECK(fake::statistics().sdk_calls == 0);
}
void stop_before_start_zero_sdk() {
    fake::configure({});
    { MonitorTask monitor(true); monitor.request_stop();
      CHECK(monitor.start() == MonitorError::cancelled); }
    CHECK(fake::statistics().sdk_calls == 0);
}
void task_create_failure() {
    fake::Settings settings; settings.fail_task_create = true; fake::configure(settings);
    MonitorTask monitor(true);
    CHECK(monitor.start() == MonitorError::task_create);
    CHECK(monitor.snapshot().phase == MonitorPhase::faulted);
    CHECK(fake::statistics().sdk_calls == 1);
    CHECK(fake::statistics().nvs_calls == 0);
    monitor.request_stop();
    CHECK(fake::statistics().sdk_calls == 1);
}
void stop_races_task_create() {
    fake::Settings settings; settings.hold_task_entry = true; settings.hold_task_create_return = true; fake::configure(settings);
    MonitorTask monitor(true);
    MonitorError result = MonitorError::disabled;
    std::thread starter([&] { result = monitor.start(); });
    fake::wait_task_created();
    monitor.request_stop();
    fake::release_task_create(); starter.join();
    CHECK(result == MonitorError::none);
    fake::release_task_entry();
    join_clean();
    CHECK(monitor.snapshot().phase == MonitorPhase::stopped);
    CHECK(monitor.snapshot().error == MonitorError::cancelled);
    CHECK(fake::statistics().nvs_calls == 0);
    CHECK(fake::statistics().timer_creates == 0);
}
void second_facade_cannot_stop_owner() {
    fake::configure({}); MonitorTask owner(true), other(true);
    CHECK(owner.start(short_config()) == MonitorError::none); fake::wait_timer_starts(1);
    CHECK(other.start() == MonitorError::slot_used);
    other.request_stop();
    CHECK(!owner.snapshot().stop_requested);
    CHECK(owner.snapshot().phase == MonitorPhase::running);
    CHECK(fake::statistics().task_creates == 1);
    stop_clean(owner);
}
void restart_rejected_after_stop() {
    fake::configure({}); MonitorTask monitor(true);
    CHECK(monitor.start(short_config()) == MonitorError::none); fake::wait_timer_starts(1); stop_clean(monitor);
    const auto calls = fake::statistics().sdk_calls;
    CHECK(monitor.start() == MonitorError::already_started);
    MonitorTask later(true); CHECK(later.start() == MonitorError::slot_used);
    later.request_stop(); CHECK(fake::statistics().sdk_calls == calls);
}
void timer_create_failure_no_nvs() {
    fake::Settings settings; settings.timer_create_error = ESP_ERR_NO_MEM; fake::configure(settings);
    MonitorTask monitor(true); CHECK(monitor.start() == MonitorError::none); join_clean();
    CHECK(monitor.snapshot().error == MonitorError::timer_create);
    CHECK(monitor.snapshot().sdk_error == ESP_ERR_NO_MEM);
    CHECK(fake::statistics().nvs_calls == 0); CHECK(fake::statistics().timer_deletes == 0);
}
void missing_partition_no_fallback() {
    fake::Settings settings; settings.missing_partition = true; fake::configure(settings);
    MonitorTask monitor(true); CHECK(monitor.start() == MonitorError::none); join_clean();
    CHECK(monitor.snapshot().error == MonitorError::identity_open);
    CHECK(monitor.snapshot().journal_error == JournalError::unprovisioned);
    CHECK(monitor.snapshot().sdk_error == ESP_ERR_NOT_FOUND);
    CHECK(fake::statistics().nvs_sets == 0); CHECK(fake::statistics().nvs_deinits == 0);
    CHECK(monitor.snapshot().queued == 0);
}
void missing_record_no_baseline() {
    fake::Settings settings; settings.missing_record = true; fake::configure(settings);
    MonitorTask monitor(true); CHECK(monitor.start() == MonitorError::none); join_clean();
    CHECK(monitor.snapshot().error == MonitorError::identity_open);
    CHECK(monitor.snapshot().journal_error == JournalError::unprovisioned);
    CHECK(monitor.snapshot().sdk_error == ESP_ERR_NVS_NOT_FOUND);
    CHECK(fake::statistics().nvs_sets == 0); CHECK(fake::statistics().nvs_deinits == 1);
    CHECK(monitor.snapshot().queued == 0);
}
void erased_partition_no_init() {
    fake::Settings settings; settings.erased_partition = true; fake::configure(settings);
    MonitorTask monitor(true); CHECK(monitor.start() == MonitorError::none); join_clean();
    CHECK(monitor.snapshot().journal_error == JournalError::unprovisioned);
    CHECK(fake::statistics().nvs_calls == 257); // Exact partition + 256 bounded preflight reads.
    CHECK(fake::statistics().nvs_sets == 0); CHECK(fake::statistics().nvs_deinits == 0);
}
void negative_clock_no_identity() {
    fake::configure({}); fake::set_time(-1);
    MonitorTask monitor(true); CHECK(monitor.start() == MonitorError::none); join_clean();
    CHECK(monitor.snapshot().error == MonitorError::clock);
    CHECK(fake::statistics().nvs_calls == 0); CHECK(fake::statistics().timer_starts == 0);
    CHECK(fake::statistics().timer_deletes == 1);
}
void microsecond_regression_fault() {
    fake::configure({}); fake::set_time(10900000);
    MonitorTask monitor(true); CHECK(monitor.start(short_config()) == MonitorError::none); fake::wait_timer_starts(1);
    CHECK(fake::statistics().last_delay_us == 100000);
    fake::set_time(10100000); // Same whole second; wrapper must detect subsecond regression.
    fake::fire(); join_clean();
    CHECK(monitor.snapshot().error == MonitorError::clock);
    CHECK(monitor.snapshot().samples == 1); CHECK(fake::statistics().floor == 1);
}
void clock_output_atomicity() {
    fake::configure({}); EspMonotonicClock clock;
    ClockReading output; output.monotonic_s = 99; output.quality = poseidon::telemetry::ClockQuality::network; output.unix_s = 123;
    std::int64_t microseconds = 99;
    fake::set_time(-5); CHECK(!clock.read(output, microseconds));
    CHECK(output.monotonic_s == 99 && output.unix_s == 123 && microseconds == 99);
    fake::set_time(1234567); CHECK(clock.read(output, microseconds));
    CHECK(output.monotonic_s == 1 && !output.unix_s && microseconds == 1234567);
    CHECK(output.quality == poseidon::telemetry::ClockQuality::unsynchronized);
    fake::set_time(1234566); CHECK(!clock.read(output, microseconds)); CHECK(microseconds == 1234567);
}
void delay_overflow_atomicity() {
    std::uint64_t output = 77;
    CHECK(!checked_monitor_delay_us(-1, 1, output)); CHECK(output == 77);
    CHECK(!checked_monitor_delay_us(0, UINT64_MAX, output)); CHECK(output == 77);
    CHECK(!checked_monitor_delay_us(INT64_MAX, 0, output)); CHECK(output == 77);
    CHECK(!checked_monitor_delay_us(INT64_MAX - 1, 1, output)); CHECK(output == 77);
    CHECK(checked_monitor_delay_us(0, UINT32_MAX, output)); CHECK(output == UINT64_C(4294967295000000));
    CHECK(checked_monitor_delay_us(1999999, 1, output)); CHECK(output == 1);
}
void long_interval_checked() {
    fake::configure({}); Config config; config.critical_interval_s = UINT32_MAX;
    MonitorTask monitor(true); CHECK(monitor.start(config) == MonitorError::none); fake::wait_timer_starts(1);
    CHECK(fake::statistics().last_delay_us == UINT64_C(4294967295000000));
    stop_clean(monitor);
}
void timer_absolute_overflow_fault() {
    fake::configure({}); fake::set_time(INT64_MAX - 500);
    MonitorTask monitor(true); CHECK(monitor.start(short_config()) == MonitorError::none); join_clean();
    CHECK(monitor.snapshot().error == MonitorError::clock);
    CHECK(fake::statistics().timer_starts == 0);
}
void delayed_wake_coalesces() {
    fake::Settings settings; settings.hold_notification_take = true; fake::configure(settings);
    MonitorTask monitor(true); CHECK(monitor.start(short_config(4)) == MonitorError::none); fake::wait_timer_starts(1);
    fake::seed_notifications(4); fake::set_time(UINT64_C(10000000000)); fake::fire();
    fake::release_notification_take(); fake::wait_timer_starts(2);
    CHECK(monitor.snapshot().samples == 2); CHECK(monitor.snapshot().coalesced_notifications == 4);
    CHECK(monitor.snapshot().queued == 2); stop_clean(monitor);
}
void queue_full_no_delivery_nulls() {
    fake::configure({}); MonitorTask monitor(true);
    CHECK(monitor.start(short_config(1)) == MonitorError::none); fake::wait_timer_starts(1);
    poseidon::telemetry::Frame frame; frame.boot_id = 99;
    CHECK(!monitor.peek_stopped(frame)); CHECK(frame.boot_id == 99);
    fake::set_time(9000000000); fake::fire(); fake::wait_timer_starts(2); stop_clean(monitor);
    const auto snapshot = monitor.snapshot();
    CHECK(snapshot.samples == 2 && snapshot.dropped_newest == 1 && snapshot.queued == 1);
    CHECK(snapshot.invalid_sensor_samples == 2 && snapshot.delivered == 0);
    CHECK(!snapshot.sensor_provider && !snapshot.power_provider);
    CHECK(monitor.peek_stopped(frame));
    CHECK(frame.boot_id == 1 && frame.sequence == 0 && frame.uptime_s == 0);
    CHECK(frame.sensor_kind == poseidon::telemetry::SensorKind::none);
    CHECK(frame.sensor_quality == poseidon::telemetry::SensorQuality::invalid);
    CHECK(!frame.sensor_value && !frame.calibration_id && !frame.battery_mv && !frame.solar_mv);
    CHECK(!frame.observed_at_unix_s && frame.clock_quality == poseidon::telemetry::ClockQuality::unsynchronized);
    CHECK(frame.power_mode == poseidon::telemetry::PowerMode::critical);
    CHECK(poseidon::telemetry::validate(frame) == poseidon::telemetry::Error::none);
}
void timer_start_failure() {
    fake::Settings settings; settings.timer_start_error = ESP_FAIL; fake::configure(settings);
    MonitorTask monitor(true); CHECK(monitor.start(short_config()) == MonitorError::none); join_clean();
    CHECK(monitor.snapshot().error == MonitorError::timer_start);
    CHECK(fake::statistics().nvs_commits == 1 && fake::statistics().nvs_deinits == 1);
    CHECK(monitor.snapshot().queued == 1 && monitor.snapshot().delivered == 0);
}
void timer_stop_failure_retains() {
    fake::Settings settings; settings.timer_stop_error = ESP_FAIL; fake::configure(settings);
    MonitorTask monitor(true); CHECK(monitor.start(short_config()) == MonitorError::none); fake::wait_timer_starts(1);
    monitor.request_stop(); join_clean();
    CHECK(monitor.snapshot().phase == MonitorPhase::retained_fault);
    CHECK(monitor.snapshot().error == MonitorError::timer_stop && monitor.snapshot().retained_resources);
    CHECK(fake::statistics().timer_deletes == 0 && fake::statistics().nvs_deinits == 1);
    const auto calls = fake::statistics().sdk_calls; fake::fire(); CHECK(fake::statistics().sdk_calls == calls);
}
void timer_delete_failure_retains() {
    fake::Settings settings; settings.timer_delete_error = ESP_FAIL; fake::configure(settings);
    MonitorTask monitor(true); CHECK(monitor.start(short_config()) == MonitorError::none); fake::wait_timer_starts(1);
    const auto selected = fake::select_expired_callback(); monitor.request_stop(); join_clean();
    CHECK(monitor.snapshot().phase == MonitorPhase::retained_fault);
    CHECK(monitor.snapshot().error == MonitorError::timer_delete && monitor.snapshot().retained_resources);
    const auto calls = fake::statistics().sdk_calls; fake::invoke(selected); CHECK(fake::statistics().sdk_calls == calls);
}
void nvs_commit_failure_preserves_error() {
    fake::Settings settings; settings.nvs_commit_error = ESP_ERR_NO_MEM; settings.nvs_deinit_error = ESP_FAIL; fake::configure(settings);
    MonitorTask monitor(true); CHECK(monitor.start(short_config()) == MonitorError::none); join_clean();
    const auto snapshot = monitor.snapshot();
    CHECK(snapshot.error == MonitorError::runtime_start && snapshot.sdk_error == ESP_ERR_NO_MEM);
    CHECK(snapshot.journal_error == JournalError::io && snapshot.cleanup_journal_error == JournalError::io);
    CHECK(snapshot.cleanup_error == ESP_FAIL && snapshot.retained_resources);
    CHECK(snapshot.queued == 0 && snapshot.samples == 0 && snapshot.delivered == 0);
    CHECK(fake::statistics().floor == 1); // Early uncertain write was not rolled back/reused.
}
void nvs_cleanup_failure_retains() {
    fake::Settings settings; settings.nvs_deinit_error = ESP_FAIL; fake::configure(settings);
    MonitorTask monitor(true); CHECK(monitor.start(short_config()) == MonitorError::none); fake::wait_timer_starts(1);
    monitor.request_stop(); join_clean();
    CHECK(monitor.snapshot().error == MonitorError::identity_close);
    CHECK(monitor.snapshot().phase == MonitorPhase::retained_fault);
    CHECK(monitor.snapshot().retained_resources && fake::statistics().nvs_deinits == 1);
}
void inflight_callback_retains_worker() {
    fake::Settings settings; settings.hold_notification = true; fake::configure(settings);
    MonitorTask monitor(true); CHECK(monitor.start(short_config()) == MonitorError::none); fake::wait_timer_starts(1);
    const auto selected = fake::select_expired_callback();
    std::thread callback([&] { fake::invoke(selected); }); fake::wait_notify_entries(1);
    monitor.request_stop(); wait_retained(monitor);
    CHECK(monitor.snapshot().retained_worker);
    CHECK(fake::statistics().task_deletes == 0 && fake::statistics().timer_deletes == 0);
    CHECK(fake::statistics().nvs_deinits == 0);
    fake::release_notification(); callback.join(); join_clean();
    CHECK(monitor.snapshot().phase == MonitorPhase::stopped && !monitor.snapshot().retained_worker);
    CHECK(fake::statistics().dangling_notifications == 0);
}
void selected_late_callback_no_notify() {
    fake::configure({}); MonitorTask monitor(true);
    CHECK(monitor.start(short_config()) == MonitorError::none); fake::wait_timer_starts(1);
    const auto selected = fake::select_expired_callback();
    stop_clean(monitor); CHECK(fake::statistics().timer_delete_pending);
    const auto calls = fake::statistics().sdk_calls;
    fake::invoke(selected); // Selected before stop, callback enters after worker is gone.
    CHECK(fake::statistics().sdk_calls == calls && fake::statistics().dangling_notifications == 0);
}
void handle_destruction_safe() {
    fake::configure({}); auto monitor = std::make_unique<MonitorTask>(true);
    CHECK(monitor->start(short_config()) == MonitorError::none); fake::wait_timer_starts(1);
    const auto selected = fake::select_expired_callback();
    monitor.reset(); // Worker/provider/arg storage is not in this destroyed handle.
    join_clean();
    const auto calls = fake::statistics().sdk_calls; fake::invoke(selected); CHECK(fake::statistics().sdk_calls == calls);
}
void notification_failure_cleanup() {
    fake::Settings settings; settings.fail_notification = true; fake::configure(settings);
    MonitorTask monitor(true); CHECK(monitor.start(short_config()) == MonitorError::none); fake::wait_timer_starts(1);
    fake::set_time(1000000); fake::fire(); join_clean();
    CHECK(monitor.snapshot().error == MonitorError::notification);
    CHECK(fake::statistics().nvs_deinits == 1);
}
void stop_races_timer_arming() {
    fake::Settings settings; settings.hold_timer_start = true; fake::configure(settings);
    MonitorTask monitor(true); CHECK(monitor.start(short_config()) == MonitorError::none); fake::wait_timer_starts(1);
    monitor.request_stop(); fake::release_timer_start(); join_clean();
    CHECK(monitor.snapshot().phase == MonitorPhase::stopped);
    CHECK(!fake::statistics().timer_active && fake::statistics().timer_stops == 1);
}

using Case = void (*)();
struct NamedCase { const char* name; Case run; };
const NamedCase cases[] = {
#define ENTRY(name) {#name, &name}
    ENTRY(disabled_zero_sdk), ENTRY(target_disabled_zero_sdk), ENTRY(target_persisted_runs_actual_worker),
    ENTRY(enabled_invalid_config_zero_sdk), ENTRY(stop_before_start_zero_sdk),
    ENTRY(task_create_failure), ENTRY(stop_races_task_create), ENTRY(second_facade_cannot_stop_owner),
    ENTRY(restart_rejected_after_stop), ENTRY(timer_create_failure_no_nvs), ENTRY(missing_partition_no_fallback),
    ENTRY(missing_record_no_baseline), ENTRY(erased_partition_no_init), ENTRY(negative_clock_no_identity),
    ENTRY(microsecond_regression_fault), ENTRY(clock_output_atomicity), ENTRY(delay_overflow_atomicity),
    ENTRY(long_interval_checked), ENTRY(timer_absolute_overflow_fault), ENTRY(delayed_wake_coalesces),
    ENTRY(queue_full_no_delivery_nulls), ENTRY(timer_start_failure), ENTRY(timer_stop_failure_retains),
    ENTRY(timer_delete_failure_retains), ENTRY(nvs_commit_failure_preserves_error), ENTRY(nvs_cleanup_failure_retains),
    ENTRY(inflight_callback_retains_worker), ENTRY(selected_late_callback_no_notify), ENTRY(handle_destruction_safe),
    ENTRY(notification_failure_cleanup), ENTRY(stop_races_timer_arming),
#undef ENTRY
};
}
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    try {
        for (const auto& item : cases) if (std::string(argv[1]) == item.name) {
            item.run(); std::cout << item.name << " passed (host fake ABI, no hardware)\n"; return 0;
        }
        return 2;
    } catch (const std::exception& error) {
        std::cerr << argv[1] << ": " << error.what() << '\n';
        std::_Exit(1); // Test failure cannot leak a blocked owned fake worker process.
    }
}
