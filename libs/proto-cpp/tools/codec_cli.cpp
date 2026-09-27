#include "poseidon/telemetry.hpp"

#include <charconv>
#include <iostream>
#include <limits>
#include <string>
#include <string_view>

using namespace poseidon::telemetry;
namespace {
template<class T> bool number(std::string_view text, T& out) {
    if (text.empty() || text.front() == '+' || (text.size() > 1 && text.front() == '0') || text == "-0") return false;
    T value{};
    const auto parsed = std::from_chars(text.data(), text.data() + text.size(), value);
    if (parsed.ec != std::errc{} || parsed.ptr != text.data() + text.size()) return false;
    out = value;
    return true;
}
template<class T> bool optional_number(std::string_view text, std::optional<T>& out) {
    if (text == "null") { out.reset(); return true; }
    T value{};
    if (!number(text, value)) return false;
    out = value;
    return true;
}
template<class T> void print_optional(const std::optional<T>& value) {
    if (value) std::cout << +*value;
    else std::cout << "null";
}
void print_frame(const Frame& f) {
    std::cout << '[' << +f.version << ",\"" << f.boot_id << "\"," << f.sequence << ',' << f.uptime_s << ',' << static_cast<unsigned>(f.clock_quality) << ',';
    print_optional(f.observed_at_unix_s); std::cout << ',';
    print_optional(f.battery_mv); std::cout << ','; print_optional(f.solar_mv); std::cout << ',';
    std::cout << static_cast<unsigned>(f.power_mode) << ',' << static_cast<unsigned>(f.sensor_kind) << ',';
    print_optional(f.sensor_value); std::cout << ',' << static_cast<unsigned>(f.sensor_quality) << ',';
    print_optional(f.calibration_id); std::cout << "]\n";
}
int hex_digit(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}
int fail(const char* reason) { std::cerr << reason << '\n'; return 2; }
} // namespace

int main(int argc, char** argv) {
    if (argc == 3 && std::string_view(argv[1]) == "decode") {
        const std::string_view hex(argv[2]);
        if (hex.empty() || hex.size() % 2 || hex.size() > max_payload_bytes * 2) return fail("size");
        Packet packet;
        for (std::size_t i = 0; i < hex.size(); i += 2) {
            const int high = hex_digit(hex[i]), low = hex_digit(hex[i + 1]);
            if (high < 0 || low < 0) return fail("hex");
            packet.bytes[packet.size++] = static_cast<std::uint8_t>((high << 4) | low);
        }
        Frame frame;
        const auto result = decode(packet.bytes.data(), packet.size, frame);
        if (result != Error::none) return fail(error_name(result));
        print_frame(frame);
        return 0;
    }
    if (argc == 15 && std::string_view(argv[1]) == "encode") {
        Frame f;
        unsigned clock = 0, power = 0, kind = 0, quality = 0;
        if (!number(argv[2], f.version) || !number(argv[3], f.boot_id) || !number(argv[4], f.sequence) ||
            !number(argv[5], f.uptime_s) || !number(argv[6], clock) || clock > 2 ||
            !optional_number(argv[7], f.observed_at_unix_s) || !optional_number(argv[8], f.battery_mv) ||
            !optional_number(argv[9], f.solar_mv) || !number(argv[10], power) || power > 2 ||
            !number(argv[11], kind) || kind > 3 || !optional_number(argv[12], f.sensor_value) ||
            !number(argv[13], quality) || quality > 2 || !optional_number(argv[14], f.calibration_id)) return fail("range");
        f.clock_quality = static_cast<ClockQuality>(clock); f.power_mode = static_cast<PowerMode>(power);
        f.sensor_kind = static_cast<SensorKind>(kind); f.sensor_quality = static_cast<SensorQuality>(quality);
        Packet packet;
        const auto result = encode(f, packet);
        if (result != Error::none) return fail(error_name(result));
        constexpr char digits[] = "0123456789abcdef";
        for (std::size_t i = 0; i < packet.size; ++i) std::cout << digits[packet.bytes[i] >> 4] << digits[packet.bytes[i] & 15];
        std::cout << '\n';
        return 0;
    }
    return fail("usage: codec_cli decode HEX | encode <13 decimal-or-null scalar fields>");
}
