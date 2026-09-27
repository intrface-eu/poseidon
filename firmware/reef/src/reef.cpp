#include "poseidon/reef.hpp"

#include <algorithm>
#include <limits>

namespace poseidon::reef {
namespace {
using Slot = std::array<std::uint8_t, BootJournal::slot_bytes>;
constexpr std::uint8_t committed = 0xa5;
std::uint32_t crc32(const std::uint8_t* bytes, std::size_t count) noexcept {
    std::uint32_t crc = 0xffffffff;
    for (std::size_t i = 0; i < count; ++i) {
        crc ^= bytes[i];
        for (unsigned bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1U)));
    }
    return ~crc;
}
void put64(Slot& slot, std::size_t offset, std::uint64_t value) noexcept {
    for (unsigned i = 0; i < 8; ++i) slot[offset + i] = static_cast<std::uint8_t>(value >> (8 * i));
}
std::uint64_t get64(const Slot& slot, std::size_t offset) noexcept {
    std::uint64_t value = 0;
    for (unsigned i = 0; i < 8; ++i) value |= static_cast<std::uint64_t>(slot[offset + i]) << (8 * i);
    return value;
}
Slot serialize(std::uint64_t id) noexcept {
    Slot slot{};
    slot[0] = 'R'; slot[1] = 'E'; slot[2] = 'E'; slot[3] = 'F'; slot[4] = 1;
    put64(slot, 8, id); put64(slot, 16, ~id);
    const auto checksum = crc32(slot.data(), 24);
    for (unsigned i = 0; i < 4; ++i) slot[24 + i] = static_cast<std::uint8_t>(checksum >> (8 * i));
    slot[31] = committed;
    return slot;
}
bool valid(const Slot& slot) noexcept { return slot == serialize(get64(slot, 8)); }
bool blank(const Slot& slot) noexcept {
    return std::all_of(slot.begin(), slot.end(), [](std::uint8_t byte) { return byte == 0xff; });
}
} // namespace

JournalError BootJournal::inspect(State& state) noexcept {
    std::array<Slot, 2> slots{};
    bool present[2] = {false, false};
    for (unsigned index = 0; index < 2; ++index) {
        for (std::size_t byte = 0; byte < slot_bytes; ++byte)
            if (!storage_.read(index * slot_bytes + byte, slots[index][byte])) return JournalError::io;
        if (slots[index][31] == committed) {
            if (!valid(slots[index])) return JournalError::corrupt;
            present[index] = true;
        } else if (slots[index][31] != 0 && !blank(slots[index])) {
            // Only invalidated (0) or entirely erased slots are known states.
            return JournalError::corrupt;
        }
    }
    if (!present[0] && !present[1]) return blank(slots[0]) && blank(slots[1]) ? JournalError::unprovisioned : JournalError::corrupt;
    const auto a = get64(slots[0], 8), b = get64(slots[1], 8);
    if (present[0] && present[1]) {
        const auto low = std::min(a, b), high = std::max(a, b);
        if (high == low || high - low != 1) return JournalError::corrupt;
    }
    state.slot = !present[0] || (present[1] && b > a) ? 1 : 0;
    state.id = get64(slots[state.slot], 8);
    return JournalError::none;
}

JournalError BootJournal::commit(unsigned slot, std::uint64_t id) noexcept {
    const auto bytes = serialize(id);
    const std::size_t base = slot * slot_bytes;
    // Invalidate the older slot before replacing any bytes; preserve the active slot.
    if (!storage_.write(base + 31, 0) || !storage_.sync()) return JournalError::io;
    for (std::size_t i = 0; i < 31; ++i)
        if (!storage_.write(base + i, bytes[i])) return JournalError::io;
    if (!storage_.sync() || !storage_.write(base + 31, committed) || !storage_.sync()) return JournalError::io;
    Slot verified{};
    for (std::size_t i = 0; i < slot_bytes; ++i)
        if (!storage_.read(base + i, verified[i])) return JournalError::io;
    return verified == bytes ? JournalError::none : JournalError::corrupt;
}

JournalError BootJournal::provision_blank() noexcept {
    State state;
    const auto status = inspect(state);
    if (status != JournalError::unprovisioned) return status == JournalError::io ? status : JournalError::not_blank;
    return commit(0, 0); // Commissioned baseline only; zero is never a wire boot ID.
}
JournalError BootJournal::current(std::uint64_t& boot_id) noexcept {
    State state;
    const auto status = inspect(state);
    if (status == JournalError::none) boot_id = state.id;
    return status;
}
JournalError BootJournal::allocate_boot(std::uint64_t& boot_id) noexcept {
    State state;
    const auto status = inspect(state);
    if (status != JournalError::none) return status;
    if (state.id == UINT64_MAX) return JournalError::exhausted;
    const auto written = commit(1 - state.slot, state.id + 1);
    if (written == JournalError::none) boot_id = state.id + 1;
    return written;
}

bool valid_config(const Config& c) noexcept {
    return c.critical_enter_mv > 0 && c.critical_enter_mv < c.critical_exit_mv &&
        c.critical_exit_mv < c.conserve_enter_mv && c.conserve_enter_mv < c.conserve_exit_mv &&
        c.normal_interval_s > 0 && c.normal_interval_s <= c.conserve_interval_s &&
        c.conserve_interval_s <= c.critical_interval_s && c.queue_capacity > 0 && c.queue_capacity <= max_queue_capacity;
}
Runtime::Runtime(BootIdentity& journal, Sensor& sensor, Config config) noexcept : journal_(journal), sensor_(sensor), config_(config) {}
bool Runtime::valid_clock(const ClockReading& clock) const noexcept {
    return static_cast<unsigned>(clock.quality) <= 2 &&
        ((clock.quality == telemetry::ClockQuality::unsynchronized) == !clock.unix_s);
}
bool Runtime::rotate_session(std::uint64_t now) noexcept {
    journal_error_ = journal_.allocate_boot(boot_id_);
    if (journal_error_ != JournalError::none) { fault_ = true; return false; }
    sequence_ = SequenceCounter{};
    origin_s_ = now;
    return true;
}
RuntimeResult Runtime::start(const ClockReading& clock) noexcept {
    if (started_ || fault_) return RuntimeResult::fault;
    if (!valid_config(config_)) return RuntimeResult::invalid_config;
    if (!valid_clock(clock)) return RuntimeResult::invalid_clock;
    if (!rotate_session(clock.monotonic_s)) return RuntimeResult::identity_failure;
    last_clock_s_ = clock.monotonic_s;
    started_ = true;
    return RuntimeResult::ready;
}
bool Runtime::configure(const Config& config) noexcept {
    if (!valid_config(config) || config.queue_capacity < count_ || fault_) return false;
    config_ = config;
    return true;
}
void Runtime::update_power(const PowerReading& power) noexcept {
    using telemetry::PowerMode;
    if (!power.battery_mv || *power.battery_mv <= config_.critical_enter_mv) { mode_ = PowerMode::critical; return; }
    const auto mv = *power.battery_mv;
    if (mv >= config_.conserve_exit_mv) { mode_ = PowerMode::normal; return; }
    if (mode_ == PowerMode::critical) {
        if (mv >= config_.critical_exit_mv) mode_ = PowerMode::conserve;
    } else if (mode_ == PowerMode::normal && mv <= config_.conserve_enter_mv) {
        mode_ = PowerMode::conserve;
    }
}
std::uint32_t Runtime::interval() const noexcept {
    if (mode_ == telemetry::PowerMode::normal) return config_.normal_interval_s;
    if (mode_ == telemetry::PowerMode::conserve) return config_.conserve_interval_s;
    return config_.critical_interval_s;
}
void Runtime::increment(std::uint64_t& counter) noexcept {
    if (counter == UINT64_MAX) statistics_.counters_saturated = true;
    else ++counter;
}
std::uint32_t Runtime::sleep_remaining_s(std::uint64_t now) const noexcept {
    if (!started_ || fault_ || !have_sample_ || now < last_clock_s_) return 0;
    const auto elapsed = now - last_sample_s_;
    return elapsed >= interval() ? 0 : static_cast<std::uint32_t>(interval() - elapsed);
}
RuntimeResult Runtime::poll(const ClockReading& clock, const PowerReading& power) noexcept {
    if (!started_ || fault_) return RuntimeResult::fault;
    if (!valid_clock(clock) || clock.monotonic_s < last_clock_s_) { fault_ = true; return RuntimeResult::invalid_clock; }
    last_clock_s_ = clock.monotonic_s;
    // Power is an explicit input on every poll, including when a probe is not due.
    update_power(power);
    if (sleep_remaining_s(clock.monotonic_s) != 0) return RuntimeResult::not_due;
    if (sequence_.exhausted() || clock.monotonic_s - origin_s_ > UINT32_MAX)
        if (!rotate_session(clock.monotonic_s)) return RuntimeResult::identity_failure;
    telemetry::Frame frame;
    frame.boot_id = boot_id_;
    if (!sequence_.take(frame.sequence)) { fault_ = true; return RuntimeResult::identity_failure; }
    frame.uptime_s = static_cast<std::uint32_t>(clock.monotonic_s - origin_s_);
    frame.clock_quality = clock.quality; frame.observed_at_unix_s = clock.unix_s;
    frame.battery_mv = power.battery_mv; frame.solar_mv = power.solar_mv; frame.power_mode = mode_;
    const auto reading = sensor_.sample();
    frame.sensor_kind = reading.kind; frame.sensor_value = reading.value;
    frame.sensor_quality = reading.quality; frame.calibration_id = reading.calibration_id;
    if (telemetry::validate(frame) != telemetry::Error::none) {
        if (static_cast<unsigned>(frame.sensor_kind) > 3) frame.sensor_kind = telemetry::SensorKind::none;
        frame.sensor_value.reset(); frame.sensor_quality = telemetry::SensorQuality::invalid; frame.calibration_id.reset();
    }
    if (frame.sensor_quality == telemetry::SensorQuality::invalid) increment(statistics_.invalid_sensor_samples);
    increment(statistics_.samples);
    have_sample_ = true; last_sample_s_ = clock.monotonic_s;
    if (count_ == config_.queue_capacity) {
        increment(statistics_.dropped_newest);
        return RuntimeResult::queue_full;
    }
    queue_[(head_ + count_) % max_queue_capacity] = frame;
    ++count_;
    return RuntimeResult::sampled;
}
const telemetry::Frame* Runtime::front() const noexcept { return count_ == 0 ? nullptr : &queue_[head_]; }
bool Runtime::pop() noexcept {
    if (count_ == 0) return false;
    head_ = (head_ + 1) % max_queue_capacity;
    --count_;
    return true;
}
} // namespace poseidon::reef
