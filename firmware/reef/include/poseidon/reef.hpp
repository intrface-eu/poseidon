#pragma once

#include "poseidon/telemetry.hpp"
#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>

namespace poseidon::reef {

// Reference storage contract: ordered durable byte replacement plus sync barriers.
// Not an implementation of ESP flash/NVS. One writer owns this backend.
class ByteStore {
public:
    virtual ~ByteStore() = default;
    virtual bool read(std::size_t offset, std::uint8_t& value) noexcept = 0;
    virtual bool write(std::size_t offset, std::uint8_t value) noexcept = 0;
    virtual bool sync() noexcept = 0;
};

enum class JournalError { none, unprovisioned, corrupt, io, exhausted, not_blank };
class BootIdentity {
public:
    virtual ~BootIdentity() = default;
    // Reserve and persist before publication; output is unchanged on failure.
    virtual JournalError allocate_boot(std::uint64_t& output) noexcept = 0;
};

class BootJournal : public BootIdentity {
public:
    static constexpr std::size_t slot_bytes = 32;
    static constexpr std::size_t storage_bytes = 2 * slot_bytes;
    explicit BootJournal(ByteStore& storage) noexcept : storage_(storage) {}
    // Explicit commissioning only. All 64 bytes must be erased (0xff).
    JournalError provision_blank() noexcept;
    JournalError current(std::uint64_t& boot_id) noexcept;
    // Commits a new boot ID before returning it. Output unchanged on error.
    JournalError allocate_boot(std::uint64_t& boot_id) noexcept override;
private:
    struct State { std::uint64_t id = 0; unsigned slot = 0; };
    JournalError inspect(State& state) noexcept;
    JournalError commit(unsigned slot, std::uint64_t id) noexcept;
    ByteStore& storage_;
};

struct SensorReading {
    telemetry::SensorKind kind = telemetry::SensorKind::none;
    std::optional<std::int32_t> value;
    telemetry::SensorQuality quality = telemetry::SensorQuality::invalid;
    std::optional<std::uint16_t> calibration_id;
};
class Sensor {
public:
    virtual ~Sensor() = default;
    // Raw counts stay raw. Only a caller with registry-backed calibration may
    // return calibrated units. Failed samples return quality=invalid, nulls.
    virtual SensorReading sample() noexcept = 0;
};
struct ClockReading {
    std::uint64_t monotonic_s = 0;
    telemetry::ClockQuality quality = telemetry::ClockQuality::unsynchronized;
    std::optional<std::uint32_t> unix_s;
};
struct PowerReading {
    std::optional<std::uint16_t> battery_mv;
    std::optional<std::uint16_t> solar_mv;
};
struct Config {
    // Synthetic example thresholds, NOT hardware cutoff or safety limits.
    std::uint16_t critical_enter_mv = 11800;
    std::uint16_t critical_exit_mv = 12200;
    std::uint16_t conserve_enter_mv = 12400;
    std::uint16_t conserve_exit_mv = 12800;
    std::uint32_t normal_interval_s = 60;
    std::uint32_t conserve_interval_s = 300;
    std::uint32_t critical_interval_s = 900;
    std::size_t queue_capacity = 8;
};
constexpr std::size_t max_queue_capacity = 16;
bool valid_config(const Config& config) noexcept;

class SequenceCounter {
public:
    explicit SequenceCounter(std::uint32_t first = 0) noexcept : next_(first) {}
    bool exhausted() const noexcept { return next_ > UINT32_MAX; }
    bool take(std::uint32_t& value) noexcept {
        if (exhausted()) return false;
        value = static_cast<std::uint32_t>(next_++);
        return true;
    }
private:
    std::uint64_t next_;
};

struct Statistics {
    std::uint64_t samples = 0;
    std::uint64_t dropped_newest = 0;
    std::uint64_t invalid_sensor_samples = 0;
    bool counters_saturated = false;
};
enum class RuntimeResult { ready, not_due, sampled, queue_full, invalid_config, invalid_clock, identity_failure, fault };

class Runtime {
public:
    Runtime(BootIdentity& journal, Sensor& sensor, Config config = {}) noexcept;
    Runtime(const Runtime&) = delete;
    Runtime& operator=(const Runtime&) = delete;
    Runtime(Runtime&&) = delete;
    Runtime& operator=(Runtime&&) = delete;
    // Call exactly once per object. Every process/restart must allocate a boot.
    RuntimeResult start(const ClockReading& clock) noexcept;
    RuntimeResult poll(const ClockReading& clock, const PowerReading& power) noexcept;
    bool configure(const Config& config) noexcept;
    // RAM queue: oldest-first; caller peeks until transport accepts, then pops.
    const telemetry::Frame* front() const noexcept;
    bool pop() noexcept;
    std::size_t queued() const noexcept { return count_; }
    const Statistics& statistics() const noexcept { return statistics_; }
    telemetry::PowerMode power_mode() const noexcept { return mode_; }
    std::uint32_t sleep_remaining_s(std::uint64_t monotonic_s) const noexcept;
    JournalError journal_error() const noexcept { return journal_error_; }
private:
    bool valid_clock(const ClockReading& clock) const noexcept;
    bool rotate_session(std::uint64_t now) noexcept;
    void update_power(const PowerReading& power) noexcept;
    std::uint32_t interval() const noexcept;
    void increment(std::uint64_t& counter) noexcept;

    BootIdentity& journal_;
    Sensor& sensor_;
    Config config_;
    std::array<telemetry::Frame, max_queue_capacity> queue_{};
    std::size_t head_ = 0;
    std::size_t count_ = 0;
    Statistics statistics_;
    telemetry::PowerMode mode_ = telemetry::PowerMode::critical;
    JournalError journal_error_ = JournalError::none;
    bool started_ = false;
    bool fault_ = false;
    bool have_sample_ = false;
    std::uint64_t boot_id_ = 0;
    SequenceCounter sequence_;
    std::uint64_t origin_s_ = 0;
    std::uint64_t last_clock_s_ = 0;
    std::uint64_t last_sample_s_ = 0;
};

} // namespace poseidon::reef
