#include "poseidon/telemetry.hpp"

#include <limits>

namespace poseidon::telemetry {
namespace {
struct Scalar {
    bool is_null = false;
    bool negative = false;
    std::uint64_t magnitude = 0; // CBOR argument; negative means -1-magnitude.
};

class Reader {
public:
    Reader(const std::uint8_t* data, std::size_t size) : data_(data), size_(size) {}
    Error scalar(Scalar& value) noexcept {
        if (pos_ >= size_) return Error::malformed;
        const auto initial = data_[pos_++];
        if (initial == 0xf6) { value.is_null = true; return Error::none; }
        const auto major = initial >> 5;
        const auto info = initial & 31;
        if (major > 1 || info > 27) return Error::malformed;
        value.negative = major == 1;
        if (info < 24) { value.magnitude = info; return Error::none; }
        const std::size_t count = std::size_t{1} << (info - 24);
        if (size_ - pos_ < count) return Error::malformed;
        for (std::size_t i = 0; i < count; ++i) value.magnitude = (value.magnitude << 8) | data_[pos_++];
        const std::uint64_t minimum[] = {24, 256, 65536, 4294967296ULL};
        if (value.magnitude < minimum[info - 24]) return Error::nonminimal;
        return Error::none;
    }
    bool begin() noexcept { return size_ != 0 && data_[pos_++] == 0x8d; }
    bool finished() const noexcept { return pos_ == size_; }
private:
    const std::uint8_t* data_;
    std::size_t size_;
    std::size_t pos_ = 0;
};

bool uint_value(const Scalar& scalar, std::uint64_t max) noexcept {
    return !scalar.is_null && !scalar.negative && scalar.magnitude <= max;
}
bool nullable_uint(const Scalar& scalar, std::uint64_t max) noexcept {
    return scalar.is_null || uint_value(scalar, max);
}

template<class T> std::optional<T> optional_value(const Scalar& scalar) noexcept {
    if (scalar.is_null) return std::nullopt;
    return static_cast<T>(scalar.magnitude);
}

class Writer {
public:
    Packet packet;
    void integer(std::uint64_t value, std::uint8_t major = 0) noexcept {
        if (value < 24) { put(static_cast<std::uint8_t>((major << 5) | value)); return; }
        const unsigned count = value <= 0xff ? 1 : value <= 0xffff ? 2 : value <= 0xffffffffULL ? 4 : 8;
        const unsigned info = count == 1 ? 24 : count == 2 ? 25 : count == 4 ? 26 : 27;
        put(static_cast<std::uint8_t>((major << 5) | info));
        for (unsigned i = count; i > 0; --i) put(static_cast<std::uint8_t>(value >> (8 * (i - 1))));
    }
    template<class T> void optional(const std::optional<T>& value) noexcept {
        if (!value) { put(0xf6); return; }
        if constexpr (std::numeric_limits<T>::is_signed) {
            if (*value < 0) { integer(static_cast<std::uint64_t>(-1 - static_cast<std::int64_t>(*value)), 1); return; }
        }
        integer(static_cast<std::uint64_t>(*value));
    }
    void put(std::uint8_t value) noexcept {
        if (packet.size < packet.bytes.size()) packet.bytes[packet.size++] = value;
        else overflow = true;
    }
    bool overflow = false;
};
} // namespace

const char* error_name(Error error) noexcept {
    switch (error) {
    case Error::none: return "none";
    case Error::size: return "size";
    case Error::malformed: return "malformed";
    case Error::nonminimal: return "nonminimal";
    case Error::range: return "range";
    case Error::version: return "version";
    case Error::quality: return "quality";
    case Error::trailing: return "trailing";
    }
    return "unknown";
}

Error validate(const Frame& f) noexcept {
    if (f.version != 1) return Error::version;
    if (f.boot_id == 0 || static_cast<unsigned>(f.clock_quality) > 2 ||
        static_cast<unsigned>(f.power_mode) > 2 || static_cast<unsigned>(f.sensor_kind) > 3 ||
        static_cast<unsigned>(f.sensor_quality) > 2) return Error::range;
    if ((f.clock_quality == ClockQuality::unsynchronized) != !f.observed_at_unix_s) return Error::quality;
    if (f.sensor_kind == SensorKind::none || f.sensor_quality == SensorQuality::invalid) {
        // "none" is only a missing/invalid sample, never raw or calibrated.
        if (f.sensor_value || f.calibration_id || f.sensor_quality != SensorQuality::invalid) return Error::quality;
    } else if (f.sensor_quality == SensorQuality::raw) {
        if (!f.sensor_value || f.calibration_id) return Error::quality;
    } else if (!f.sensor_value || !f.calibration_id || *f.calibration_id == 0) {
        return Error::quality;
    }
    return Error::none;
}

Error encode(const Frame& f, Packet& output) noexcept {
    const auto result = validate(f);
    if (result != Error::none) return result;
    Writer w;
    w.put(0x8d);
    w.integer(f.version); w.integer(f.boot_id); w.integer(f.sequence); w.integer(f.uptime_s);
    w.integer(static_cast<unsigned>(f.clock_quality)); w.optional(f.observed_at_unix_s);
    w.optional(f.battery_mv); w.optional(f.solar_mv); w.integer(static_cast<unsigned>(f.power_mode));
    w.integer(static_cast<unsigned>(f.sensor_kind)); w.optional(f.sensor_value);
    w.integer(static_cast<unsigned>(f.sensor_quality)); w.optional(f.calibration_id);
    if (w.overflow) return Error::size;
    output = w.packet;
    return Error::none;
}

Error decode(const std::uint8_t* data, std::size_t size, Frame& output) noexcept {
    if (!data || size == 0 || size > max_payload_bytes) return Error::size;
    Reader reader(data, size);
    if (!reader.begin()) return Error::malformed;
    std::array<Scalar, 13> a{};
    for (auto& scalar : a) {
        const auto error = reader.scalar(scalar);
        if (error != Error::none) return error;
    }
    if (!reader.finished()) return Error::trailing;
    constexpr auto u32 = std::numeric_limits<std::uint32_t>::max();
    constexpr auto u16 = std::numeric_limits<std::uint16_t>::max();
    if (!uint_value(a[0], 255) || !uint_value(a[1], UINT64_MAX) ||
        !uint_value(a[2], u32) || !uint_value(a[3], u32) || !uint_value(a[4], 2) ||
        !nullable_uint(a[5], u32) || !nullable_uint(a[6], u16) || !nullable_uint(a[7], u16) ||
        !uint_value(a[8], 2) || !uint_value(a[9], 3) || !uint_value(a[11], 2) ||
        !nullable_uint(a[12], u16)) return Error::range;
    if (!a[10].is_null && a[10].magnitude > INT32_MAX) return Error::range;
    Frame f;
    f.version = static_cast<std::uint8_t>(a[0].magnitude);
    f.boot_id = a[1].magnitude;
    f.sequence = static_cast<std::uint32_t>(a[2].magnitude);
    f.uptime_s = static_cast<std::uint32_t>(a[3].magnitude);
    f.clock_quality = static_cast<ClockQuality>(a[4].magnitude);
    f.observed_at_unix_s = optional_value<std::uint32_t>(a[5]);
    f.battery_mv = optional_value<std::uint16_t>(a[6]);
    f.solar_mv = optional_value<std::uint16_t>(a[7]);
    f.power_mode = static_cast<PowerMode>(a[8].magnitude);
    f.sensor_kind = static_cast<SensorKind>(a[9].magnitude);
    if (!a[10].is_null) f.sensor_value = static_cast<std::int32_t>(a[10].negative ?
        -1 - static_cast<std::int64_t>(a[10].magnitude) : static_cast<std::int64_t>(a[10].magnitude));
    f.sensor_quality = static_cast<SensorQuality>(a[11].magnitude);
    f.calibration_id = optional_value<std::uint16_t>(a[12]);
    const auto error = validate(f);
    if (error != Error::none) return error;
    output = f;
    return Error::none;
}
} // namespace poseidon::telemetry
