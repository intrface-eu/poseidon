#include "poseidon/reef.hpp"

#include <algorithm>
#include <array>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <type_traits>

static_assert(!std::is_copy_constructible<poseidon::reef::Runtime>::value, "runtime identities must not be cloned");
static_assert(!std::is_move_constructible<poseidon::reef::Runtime>::value, "runtime identity ownership is fixed");

using namespace poseidon;
namespace {
void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message); // Active with -DNDEBUG.
}
struct MemoryStore : reef::ByteStore {
    std::array<std::uint8_t, reef::BootJournal::storage_bytes> bytes;
    std::size_t writes = 0, reads = 0, syncs = 0;
    std::size_t write_limit = SIZE_MAX, read_limit = SIZE_MAX, sync_limit = SIZE_MAX;
    MemoryStore() { bytes.fill(0xff); }
    bool read(std::size_t offset, std::uint8_t& value) noexcept override {
        if (offset >= bytes.size() || reads++ >= read_limit) return false;
        value = bytes[offset]; return true;
    }
    bool write(std::size_t offset, std::uint8_t value) noexcept override {
        if (offset >= bytes.size() || writes++ >= write_limit) return false;
        bytes[offset] = value; return true;
    }
    bool sync() noexcept override { return syncs++ < sync_limit; }
    void reset_faults() {
        writes = reads = syncs = 0;
        write_limit = read_limit = sync_limit = SIZE_MAX;
    }
};
struct SyntheticSensor : reef::Sensor {
    reef::SensorReading reading{telemetry::SensorKind::temperature, 123, telemetry::SensorQuality::raw, std::nullopt};
    unsigned calls = 0;
    reef::SensorReading sample() noexcept override { ++calls; return reading; }
};
reef::Config fast_config(std::size_t capacity = 8) {
    reef::Config config;
    config.normal_interval_s = config.conserve_interval_s = config.critical_interval_s = 1;
    config.queue_capacity = capacity;
    return config;
}
reef::ClockReading clock_at(std::uint64_t now) { return {now, telemetry::ClockQuality::unsynchronized, std::nullopt}; }
reef::PowerReading power_at(std::uint16_t battery = 13000) { return {battery, 19000}; }
void provision(MemoryStore& store) {
    reef::BootJournal journal(store);
    require(journal.provision_blank() == reef::JournalError::none, "blank provision");
}
void seed_slot(MemoryStore& store, unsigned index, std::uint64_t id) {
    // Test-only serialized record constructor; never a runtime reprovision API.
    const std::size_t base = index * 32;
    std::fill(store.bytes.begin() + base, store.bytes.begin() + base + 32, 0);
    store.bytes[base] = 'R'; store.bytes[base + 1] = 'E'; store.bytes[base + 2] = 'E'; store.bytes[base + 3] = 'F'; store.bytes[base + 4] = 1;
    for (unsigned i = 0; i < 8; ++i) {
        store.bytes[base + 8 + i] = static_cast<std::uint8_t>(id >> (8 * i));
        store.bytes[base + 16 + i] = static_cast<std::uint8_t>(~id >> (8 * i));
    }
    std::uint32_t crc = UINT32_MAX;
    for (unsigned i = 0; i < 24; ++i) {
        crc ^= store.bytes[base + i];
        for (unsigned bit = 0; bit < 8; ++bit) crc = (crc & 1) ? (crc >> 1) ^ 0xedb88320U : crc >> 1;
    }
    crc = ~crc;
    for (unsigned i = 0; i < 4; ++i) store.bytes[base + 24 + i] = static_cast<std::uint8_t>(crc >> (8 * i));
    store.bytes[base + 31] = 0xa5;
}
void codec_output_atomicity() {
    telemetry::Frame input; input.boot_id = UINT64_MAX;
    telemetry::Packet packet; packet.size = 7; packet.bytes.fill(0x55);
    input.sensor_quality = telemetry::SensorQuality::raw;
    require(telemetry::encode(input, packet) == telemetry::Error::quality, "encoder rejects invalid semantic combination");
    require(packet.size == 7 && packet.bytes[0] == 0x55, "encoder failure unchanged");
    const std::uint8_t garbage[] = {0x8d};
    require(telemetry::decode(garbage, sizeof garbage, input) != telemetry::Error::none, "decoder rejects truncation");
    require(input.boot_id == UINT64_MAX && input.sensor_quality == telemetry::SensorQuality::raw, "decoder failure unchanged");
    require(telemetry::decode(nullptr, 5, input) == telemetry::Error::size, "null pointer rejected");
    input.sensor_quality = telemetry::SensorQuality::invalid;
    require(telemetry::encode(input, packet) == telemetry::Error::none, "valid encode");
    telemetry::Frame decoded;
    require(telemetry::decode(packet.bytes.data(), packet.size, decoded) == telemetry::Error::none, "valid decode");
    require(decoded.boot_id == UINT64_MAX, "full uint64 identity");
}
void codec_bounded_mutations() {
    const auto check = [](const std::uint8_t* data, std::size_t size) {
        telemetry::Frame decoded; decoded.boot_id = 77;
        const auto result = telemetry::decode(data, size, decoded);
        if (result == telemetry::Error::none) {
            telemetry::Packet encoded;
            require(telemetry::encode(decoded, encoded) == telemetry::Error::none, "decoded frame reencodes");
            require(encoded.size == size && std::equal(encoded.bytes.begin(), encoded.bytes.begin() + encoded.size, data), "accepted wire has exactly canonical representation");
        } else require(decoded.boot_id == 77, "malformed input never changes output");
    };
    telemetry::Frame frame; frame.boot_id = UINT64_MAX; frame.sequence = UINT32_MAX; frame.uptime_s = UINT32_MAX;
    frame.clock_quality = telemetry::ClockQuality::network; frame.observed_at_unix_s = UINT32_MAX;
    frame.battery_mv = frame.solar_mv = UINT16_MAX; frame.power_mode = telemetry::PowerMode::critical;
    frame.sensor_kind = telemetry::SensorKind::dissolved_oxygen; frame.sensor_value = INT32_MIN;
    frame.sensor_quality = telemetry::SensorQuality::calibrated; frame.calibration_id = UINT16_MAX;
    telemetry::Packet seed; require(telemetry::encode(frame, seed) == telemetry::Error::none && seed.size == 44, "maximum width seed");
    for (std::size_t position = 0; position < seed.size; ++position)
        for (unsigned value = 0; value < 256; ++value) {
            auto mutated = seed; mutated.bytes[position] = static_cast<std::uint8_t>(value);
            check(mutated.bytes.data(), mutated.size);
        }
    std::uint32_t state = 0x52454546;
    const auto next = [&state]() { state ^= state << 13; state ^= state >> 17; state ^= state << 5; return state; };
    std::array<std::uint8_t, 80> bytes{};
    for (unsigned iteration = 0; iteration < 20000; ++iteration) {
        const auto size = next() % (bytes.size() + 1);
        for (auto& byte : bytes) byte = static_cast<std::uint8_t>(next());
        if (iteration % 2 == 0) bytes[0] = 0x8d;
        check(bytes.data(), size);
    }
}
void journal_blank_and_restart() {
    MemoryStore store; reef::BootJournal journal(store); std::uint64_t id = 99;
    require(journal.current(id) == reef::JournalError::unprovisioned && id == 99, "blank is not provisioned");
    require(journal.allocate_boot(id) == reef::JournalError::unprovisioned, "no auto commission");
    require(journal.provision_blank() == reef::JournalError::none, "commission");
    require(journal.provision_blank() == reef::JournalError::not_blank, "no repeated provision");
    for (std::uint64_t expected = 1; expected <= 100; ++expected) {
        reef::BootJournal rebooted(store);
        require(rebooted.allocate_boot(id) == reef::JournalError::none && id == expected, "strict persistent boot ordering");
        require(rebooted.current(id) == reef::JournalError::none && id == expected, "read back committed ID");
    }
}
void journal_every_write_interruption() {
    MemoryStore baseline; provision(baseline); reef::BootJournal journal(baseline); std::uint64_t id = 0;
    require(journal.allocate_boot(id) == reef::JournalError::none && id == 1, "seed first boot");
    for (std::size_t cut = 0; cut <= 33; ++cut) {
        MemoryStore store = baseline; store.reset_faults(); store.write_limit = cut;
        reef::BootJournal interrupted(store); id = 999;
        const auto result = interrupted.allocate_boot(id);
        require((cut == 33) == (result == reef::JournalError::none), "commit is last of 33 byte writes");
        require(id == (cut == 33 ? 2 : 999), "no uncommitted ID escapes");
        store.reset_faults(); reef::BootJournal recovered(store);
        require(recovered.current(id) == reef::JournalError::none && id == (cut == 33 ? 2 : 1), "old or new committed record recovers");
        const auto old = id;
        require(recovered.allocate_boot(id) == reef::JournalError::none && id == old + 1, "restart advances before emission");
    }
}
void journal_every_provision_interruption() {
    for (std::size_t cut = 0; cut <= 33; ++cut) {
        MemoryStore store; store.write_limit = cut; reef::BootJournal interrupted(store);
        const auto result = interrupted.provision_blank();
        require((cut == 33) == (result == reef::JournalError::none), "provision byte boundary");
        store.reset_faults(); reef::BootJournal recovered(store); std::uint64_t id = 999;
        const auto expected = cut == 0 ? reef::JournalError::unprovisioned : cut == 33 ? reef::JournalError::none : reef::JournalError::corrupt;
        require(recovered.current(id) == expected, "partial first record never auto resets");
        if (cut > 0 && cut < 33) require(recovered.provision_blank() == reef::JournalError::not_blank, "partial commissioning fails closed");
    }
}
void journal_sync_and_read_failures() {
    MemoryStore baseline; provision(baseline); reef::BootJournal seed(baseline); std::uint64_t id = 0;
    require(seed.allocate_boot(id) == reef::JournalError::none, "seed");
    for (std::size_t cut = 0; cut < 3; ++cut) {
        auto store = baseline; store.reset_faults(); store.sync_limit = cut; reef::BootJournal journal(store); id = 99;
        require(journal.allocate_boot(id) == reef::JournalError::io && id == 99, "sync failure not published");
        store.reset_faults(); reef::BootJournal recovered(store);
        require(recovered.current(id) == reef::JournalError::none && id == (cut == 2 ? 2 : 1), "sync failure recovery in durable-byte model");
    }
    for (std::size_t cut = 0; cut < 96; ++cut) {
        auto store = baseline; store.reset_faults(); store.read_limit = cut; reef::BootJournal journal(store); id = 99;
        require(journal.allocate_boot(id) == reef::JournalError::io && id == 99, "read failure not published");
        store.reset_faults(); reef::BootJournal recovered(store);
        require(recovered.current(id) == reef::JournalError::none && id == (cut < 64 ? 1 : 2), "read failure recovery");
    }
}
void journal_corruption_fail_closed() {
    MemoryStore baseline; provision(baseline); reef::BootJournal seed(baseline); std::uint64_t id = 0;
    require(seed.allocate_boot(id) == reef::JournalError::none, "seed");
    for (std::size_t byte = 0; byte < 64; ++byte) {
        auto store = baseline; store.bytes[byte] ^= 1; reef::BootJournal journal(store); id = 999;
        require(journal.current(id) == reef::JournalError::corrupt && id == 999, "every committed-record byte protected");
        require(journal.allocate_boot(id) == reef::JournalError::corrupt, "no rollback to older record on corruption");
        require(journal.provision_blank() == reef::JournalError::not_blank, "corrupt storage not erased");
    }
    MemoryStore garbage; garbage.bytes[0] = 1; reef::BootJournal journal(garbage);
    require(journal.current(id) == reef::JournalError::corrupt, "unknown data fail closed");
}
void journal_exhaustion_and_ambiguity() {
    MemoryStore store; seed_slot(store, 0, UINT64_MAX - 1); seed_slot(store, 1, UINT64_MAX);
    reef::BootJournal journal(store); std::uint64_t id = 0;
    require(journal.current(id) == reef::JournalError::none && id == UINT64_MAX, "maximum boot accepted");
    require(journal.allocate_boot(id) == reef::JournalError::exhausted && id == UINT64_MAX, "boot never wraps");
    seed_slot(store, 0, UINT64_MAX);
    require(journal.current(id) == reef::JournalError::corrupt, "equal journal IDs ambiguous");
    seed_slot(store, 0, 1);
    require(journal.current(id) == reef::JournalError::corrupt, "nonconsecutive journal IDs ambiguous");
}
void sequence_no_wrap() {
    reef::SequenceCounter sequence(UINT32_MAX - 1); std::uint32_t value = 0;
    require(sequence.take(value) && value == UINT32_MAX - 1, "penultimate sequence");
    require(sequence.take(value) && value == UINT32_MAX && sequence.exhausted(), "maximum sequence emitted once");
    require(!sequence.take(value) && value == UINT32_MAX, "sequence does not wrap");
    for (unsigned i = 0; i < 100; ++i) require(!sequence.take(value), "exhaustion remains terminal");
}
void runtime_samples_and_quality() {
    MemoryStore store; provision(store); reef::BootJournal journal(store); SyntheticSensor sensor;
    reef::Runtime runtime(journal, sensor, fast_config());
    require(runtime.start(clock_at(100)) == reef::RuntimeResult::ready, "start");
    require(runtime.start(clock_at(100)) == reef::RuntimeResult::fault, "no second start");
    require(runtime.poll(clock_at(100), power_at()) == reef::RuntimeResult::sampled, "first sample");
    require(runtime.front()->boot_id == 1 && runtime.front()->sequence == 0 && runtime.front()->uptime_s == 0, "sample identity");
    require(!runtime.front()->observed_at_unix_s && runtime.front()->sensor_value == 123 && !runtime.front()->calibration_id, "raw counts and unsynced clock");
    runtime.pop(); sensor.reading = {telemetry::SensorKind::salinity, 35000, telemetry::SensorQuality::calibrated, 7};
    reef::ClockReading rtc{101, telemetry::ClockQuality::rtc, 1700000000};
    require(runtime.poll(rtc, power_at()) == reef::RuntimeResult::sampled, "calibrated sample");
    require(runtime.front()->sensor_value == 35000 && runtime.front()->calibration_id == 7 && runtime.front()->observed_at_unix_s == 1700000000, "calibrated fields preserved");
    runtime.pop(); sensor.reading.calibration_id = 0;
    require(runtime.poll(clock_at(102), power_at()) == reef::RuntimeResult::sampled, "bad calibration becomes invalid");
    require(runtime.front()->sensor_kind == telemetry::SensorKind::salinity && runtime.front()->sensor_quality == telemetry::SensorQuality::invalid && !runtime.front()->sensor_value && !runtime.front()->calibration_id, "invalid has no fabricated value");
    runtime.pop(); sensor.reading = {static_cast<telemetry::SensorKind>(255), 9, telemetry::SensorQuality::raw, std::nullopt};
    runtime.poll(clock_at(103), power_at());
    require(runtime.front()->sensor_kind == telemetry::SensorKind::none && runtime.statistics().invalid_sensor_samples == 2, "unknown sensor normalized invalid");
}
void runtime_sleep_and_battery_hysteresis() {
    MemoryStore store; provision(store); reef::BootJournal journal(store); SyntheticSensor sensor; reef::Runtime runtime(journal, sensor);
    runtime.start(clock_at(0)); runtime.poll(clock_at(0), power_at()); runtime.pop();
    require(runtime.power_mode() == telemetry::PowerMode::normal && runtime.sleep_remaining_s(1) == 59, "normal sleep");
    require(runtime.poll(clock_at(59), power_at()) == reef::RuntimeResult::not_due && sensor.calls == 1, "no early sampling");
    runtime.poll(clock_at(60), power_at(12400));
    require(runtime.power_mode() == telemetry::PowerMode::conserve && runtime.sleep_remaining_s(60) == 240, "conserve threshold extends deadline from last sample");
    runtime.poll(clock_at(300), power_at(12500)); runtime.pop();
    require(runtime.power_mode() == telemetry::PowerMode::conserve && runtime.sleep_remaining_s(300) == 300, "conserve hysteresis");
    runtime.poll(clock_at(301), power_at(11800));
    require(runtime.power_mode() == telemetry::PowerMode::critical && runtime.sleep_remaining_s(301) == 899, "critical threshold");
    runtime.poll(clock_at(302), power_at(12199)); require(runtime.power_mode() == telemetry::PowerMode::critical, "critical held below exit");
    runtime.poll(clock_at(303), power_at(12200)); require(runtime.power_mode() == telemetry::PowerMode::conserve, "critical recovery threshold");
    runtime.poll(clock_at(304), power_at(12799)); require(runtime.power_mode() == telemetry::PowerMode::conserve, "conserve held below exit");
    runtime.poll(clock_at(360), power_at(12800));
    require(runtime.power_mode() == telemetry::PowerMode::normal && runtime.front()->battery_mv == 12800 && runtime.front()->solar_mv == 19000, "normal recovery and solar telemetry");
    runtime.pop(); runtime.poll(clock_at(361), {std::nullopt, std::nullopt});
    require(runtime.power_mode() == telemetry::PowerMode::critical, "missing battery not healthy");
    runtime.poll(clock_at(1260), {std::nullopt, std::nullopt});
    require(!runtime.front()->battery_mv && !runtime.front()->solar_mv, "unknown power stays null");
}
void runtime_queue_and_config() {
    for (std::size_t capacity = 1; capacity <= reef::max_queue_capacity; ++capacity) {
        MemoryStore store; provision(store); reef::BootJournal journal(store); SyntheticSensor sensor;
        auto config = fast_config(capacity); reef::Runtime runtime(journal, sensor, config); runtime.start(clock_at(0));
        for (std::size_t i = 0; i <= capacity; ++i) require(runtime.poll(clock_at(i), power_at()) == (i == capacity ? reef::RuntimeResult::queue_full : reef::RuntimeResult::sampled), "bounded drop-newest queue");
        require(runtime.queued() == capacity && runtime.statistics().dropped_newest == 1 && runtime.statistics().samples == capacity + 1, "overflow accounting");
        for (std::size_t i = 0; i < capacity; ++i) { require(runtime.front()->sequence == i, "FIFO preserved under overflow"); runtime.pop(); }
        require(!runtime.front() && !runtime.pop(), "empty queue");
        for (std::size_t i = capacity + 1; i < capacity + 65; ++i) {
            require(runtime.poll(clock_at(i), power_at()) == reef::RuntimeResult::sampled && runtime.front()->sequence == i, "dropped sequence remains a visible gap; ring wraps"); runtime.pop();
        }
    }
    MemoryStore store; provision(store); reef::BootJournal journal(store); SyntheticSensor sensor; auto config = fast_config(3);
    reef::Runtime runtime(journal, sensor, config); runtime.start(clock_at(0)); runtime.poll(clock_at(0), power_at()); runtime.poll(clock_at(1), power_at());
    config.queue_capacity = 1; require(!runtime.configure(config) && runtime.queued() == 2, "no shrink data loss");
    runtime.pop(); runtime.pop(); require(runtime.configure(config), "empty shrink accepted");
    config.normal_interval_s = 0; require(!runtime.configure(config), "zero interval rejected");
}
void runtime_restart_and_session_rollover() {
    MemoryStore store; provision(store); SyntheticSensor sensor;
    { reef::BootJournal journal(store); reef::Runtime runtime(journal, sensor, fast_config()); runtime.start(clock_at(100)); runtime.poll(clock_at(100), power_at()); require(runtime.front()->boot_id == 1, "first boot"); }
    reef::BootJournal journal(store); reef::Runtime runtime(journal, sensor, fast_config()); runtime.start(clock_at(0));
    require(runtime.queued() == 0, "RAM queue is not durable");
    runtime.poll(clock_at(0), power_at()); require(runtime.front()->boot_id == 2 && runtime.front()->sequence == 0, "restart identity cannot collide"); runtime.pop();
    runtime.poll(clock_at(UINT32_MAX), power_at());
    require(runtime.front()->uptime_s == UINT32_MAX && runtime.front()->boot_id == 2, "maximum uptime");
    runtime.poll(clock_at(std::uint64_t{UINT32_MAX} + 1), power_at());
    require(runtime.front()->boot_id == 2, "queued old session remains ordered"); runtime.pop();
    require(runtime.front()->boot_id == 3 && runtime.front()->sequence == 0 && runtime.front()->uptime_s == 0, "uptime overflow rotates persisted session");
}
void runtime_clock_faults_and_extremes() {
    MemoryStore store; provision(store); reef::BootJournal journal(store); SyntheticSensor sensor;
    reef::Runtime runtime(journal, sensor, fast_config());
    require(runtime.start({0, telemetry::ClockQuality::rtc, std::nullopt}) == reef::RuntimeResult::invalid_clock, "synchronized requires UTC");
    require(runtime.start({0, telemetry::ClockQuality::unsynchronized, 0}) == reef::RuntimeResult::invalid_clock, "unsynchronized prohibits UTC");
    require(runtime.start({0, static_cast<telemetry::ClockQuality>(255), 0}) == reef::RuntimeResult::invalid_clock, "clock enum bounded");
    require(runtime.start(clock_at(UINT64_MAX - 1)) == reef::RuntimeResult::ready, "large monotonic start");
    runtime.poll({UINT64_MAX - 1, telemetry::ClockQuality::network, UINT32_MAX}, power_at()); runtime.pop();
    require(runtime.poll({UINT64_MAX, telemetry::ClockQuality::rtc, 0}, power_at()) == reef::RuntimeResult::sampled, "UTC may adjust independently from monotonic");
    require(runtime.front()->uptime_s == 1 && runtime.front()->observed_at_unix_s == 0, "UTC zero is not missing");
    require(runtime.sleep_remaining_s(UINT64_MAX) == 1, "no deadline addition overflow");
    require(runtime.poll(clock_at(0), power_at()) == reef::RuntimeResult::invalid_clock, "monotonic wrap/regression rejected");
    require(runtime.poll(clock_at(UINT64_MAX), power_at()) == reef::RuntimeResult::fault, "clock fault requires new runtime boot");
}
void runtime_identity_fail_closed() {
    SyntheticSensor sensor; MemoryStore blank; reef::BootJournal unprovisioned(blank); reef::Runtime no_identity(unprovisioned, sensor);
    require(no_identity.start(clock_at(0)) == reef::RuntimeResult::identity_failure && no_identity.journal_error() == reef::JournalError::unprovisioned, "runtime cannot self-provision");
    require(no_identity.poll(clock_at(0), power_at()) == reef::RuntimeResult::fault && sensor.calls == 0, "no sample before persistent identity");
    MemoryStore store; provision(store); reef::BootJournal journal(store); reef::Runtime runtime(journal, sensor, fast_config()); runtime.start(clock_at(0)); runtime.poll(clock_at(0), power_at()); runtime.pop();
    store.reset_faults(); store.write_limit = 0;
    require(runtime.poll(clock_at(std::uint64_t{UINT32_MAX} + 1), power_at()) == reef::RuntimeResult::identity_failure, "rollover write failure stops new telemetry");
    require(runtime.queued() == 0 && sensor.calls == 1, "failed rotate creates no reading");
    store.reset_faults(); require(runtime.poll(clock_at(std::uint64_t{UINT32_MAX} + 2), power_at()) == reef::RuntimeResult::fault, "fault does not auto-retry");
}
void runtime_invalid_configs() {
    auto config = reef::Config{};
    require(reef::valid_config(config), "default example structurally valid");
    config.critical_enter_mv = 0; require(!reef::valid_config(config), "zero threshold invalid"); config = {};
    config.critical_exit_mv = config.critical_enter_mv; require(!reef::valid_config(config), "hysteresis strictly ordered"); config = {};
    config.conserve_enter_mv = config.critical_exit_mv; require(!reef::valid_config(config), "mode bands strictly ordered"); config = {};
    config.conserve_exit_mv = config.conserve_enter_mv; require(!reef::valid_config(config), "conserve hysteresis required"); config = {};
    config.normal_interval_s = 0; require(!reef::valid_config(config), "nonzero sleep"); config = {};
    config.conserve_interval_s = 1; require(!reef::valid_config(config), "ordered sleep"); config = {};
    config.critical_interval_s = 1; require(!reef::valid_config(config), "critical sleep ordered"); config = {};
    config.queue_capacity = 17; require(!reef::valid_config(config), "bounded capacity"); config.queue_capacity = 0;
    MemoryStore store; provision(store); reef::BootJournal journal(store); SyntheticSensor sensor; reef::Runtime runtime(journal, sensor, config);
    require(runtime.start(clock_at(0)) == reef::RuntimeResult::invalid_config, "bad config rejected before identity allocation");
    std::uint64_t id = 99; require(journal.current(id) == reef::JournalError::none && id == 0, "invalid config does not consume identity");
}
} // namespace

int main(int argc, char** argv) {
    const std::pair<const char*, std::function<void()>> cases[] = {
        {"codec_output_atomicity", codec_output_atomicity},
        {"codec_bounded_mutations", codec_bounded_mutations},
        {"journal_blank_and_restart", journal_blank_and_restart},
        {"journal_every_write_interruption", journal_every_write_interruption},
        {"journal_every_provision_interruption", journal_every_provision_interruption},
        {"journal_sync_and_read_failures", journal_sync_and_read_failures},
        {"journal_corruption_fail_closed", journal_corruption_fail_closed},
        {"journal_exhaustion_and_ambiguity", journal_exhaustion_and_ambiguity},
        {"sequence_no_wrap", sequence_no_wrap},
        {"runtime_samples_and_quality", runtime_samples_and_quality},
        {"runtime_sleep_and_battery_hysteresis", runtime_sleep_and_battery_hysteresis},
        {"runtime_queue_and_config", runtime_queue_and_config},
        {"runtime_restart_and_session_rollover", runtime_restart_and_session_rollover},
        {"runtime_clock_faults_and_extremes", runtime_clock_faults_and_extremes},
        {"runtime_identity_fail_closed", runtime_identity_fail_closed},
        {"runtime_invalid_configs", runtime_invalid_configs},
    };
    if (argc != 2) { std::cerr << "one named test required\n"; return 2; }
    for (const auto& test : cases) if (test.first == std::string(argv[1])) {
        try { test.second(); std::cout << "PASS " << test.first << '\n'; return 0; }
        catch (const std::exception& error) { std::cerr << "FAIL " << test.first << ": " << error.what() << '\n'; return 1; }
    }
    std::cerr << "unknown test\n"; return 2;
}
