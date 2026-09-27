#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>

namespace poseidon::telemetry {

// Private reference for reef-telemetry-cbor-v1-proposal, not a reviewed contract.
constexpr std::size_t max_payload_bytes = 64;
constexpr std::uint8_t fport = 10;
enum class ClockQuality : std::uint8_t { unsynchronized = 0, rtc = 1, network = 2 };
enum class PowerMode : std::uint8_t { normal = 0, conserve = 1, critical = 2 };
enum class SensorKind : std::uint8_t { none = 0, temperature = 1, salinity = 2, dissolved_oxygen = 3 };
enum class SensorQuality : std::uint8_t { raw = 0, calibrated = 1, invalid = 2 };

struct Frame {
    std::uint8_t version = 1;
    std::uint64_t boot_id = 0;
    std::uint32_t sequence = 0;
    std::uint32_t uptime_s = 0;
    ClockQuality clock_quality = ClockQuality::unsynchronized;
    std::optional<std::uint32_t> observed_at_unix_s;
    std::optional<std::uint16_t> battery_mv;
    std::optional<std::uint16_t> solar_mv;
    PowerMode power_mode = PowerMode::normal;
    SensorKind sensor_kind = SensorKind::none;
    std::optional<std::int32_t> sensor_value;
    SensorQuality sensor_quality = SensorQuality::invalid;
    std::optional<std::uint16_t> calibration_id;
};

struct Packet {
    std::array<std::uint8_t, max_payload_bytes> bytes{};
    std::size_t size = 0;
};

enum class Error { none, size, malformed, nonminimal, range, version, quality, trailing };
const char* error_name(Error error) noexcept;
Error validate(const Frame& frame) noexcept;
// On failure, output arguments are unchanged. No heap allocation or exceptions.
Error encode(const Frame& frame, Packet& output) noexcept;
Error decode(const std::uint8_t* data, std::size_t size, Frame& output) noexcept;

} // namespace poseidon::telemetry
