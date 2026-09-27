#include "poseidon/nvs_boot_identity.hpp"
#include "nvs_flash.h"

#include <algorithm>
#include <cstring>

namespace poseidon::reef {
namespace {
// The fixed partition has exactly one allocator lease for the whole lifecycle.
// No reset API: uncertain writes or cleanup require a genuinely new process/boot.
std::atomic<NvsBootIdentity*> partition_lease{nullptr};
std::atomic<bool> process_faulted{false};
constexpr char partition_label[] = "reef_state";
constexpr char namespace_name[] = "reef_boot";
constexpr char record_key[] = "identity_v1";

class Operation {
public:
    explicit Operation(std::atomic_flag& busy) noexcept : busy_(busy), acquired_(!busy.test_and_set()) {}
    ~Operation() { if (acquired_) busy_.clear(); }
    bool acquired() const noexcept { return acquired_; }
private:
    std::atomic_flag& busy_;
    bool acquired_;
};

std::uint32_t crc32(const std::uint8_t* bytes, std::size_t size) noexcept {
    // CRC-32/ISO-HDLC: reflected polynomial 0xedb88320 (normal 0x04c11db7),
    // init/xorout 0xffffffff, refin/refout=true. Stored little-endian.
    std::uint32_t crc = UINT32_MAX;
    for (std::size_t i = 0; i < size; ++i) {
        crc ^= bytes[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1U)));
    }
    return ~crc;
}
std::uint64_t read64(const std::uint8_t* bytes) noexcept {
    std::uint64_t value = 0;
    for (unsigned i = 0; i < 8; ++i) value |= static_cast<std::uint64_t>(bytes[i]) << (8 * i);
    return value;
}
bool equal_text(const char* text, const char* expected) noexcept {
    return text != nullptr && std::strcmp(text, expected) == 0;
}
bool fixed_spec(const PartitionSpec& spec) noexcept {
    return equal_text(spec.label, partition_label) && equal_text(spec.namespace_name, namespace_name) &&
        equal_text(spec.key, record_key) && spec.type == ESP_PARTITION_TYPE_DATA &&
        spec.subtype == ESP_PARTITION_SUBTYPE_DATA_NVS && spec.address == 0x3f0000 && spec.size == 0x10000;
}
JournalError classify(esp_err_t error) noexcept {
    if (error == ESP_ERR_NVS_NOT_FOUND || error == ESP_ERR_NVS_PART_NOT_FOUND || error == ESP_ERR_NOT_FOUND)
        return JournalError::unprovisioned;
    if (error == ESP_ERR_NVS_TYPE_MISMATCH || error == ESP_ERR_NVS_INVALID_LENGTH ||
        error == ESP_ERR_NVS_NEW_VERSION_FOUND) return JournalError::corrupt;
    return JournalError::io;
}
} // namespace

NvsBootIdentity::Record NvsBootIdentity::serialize(std::uint64_t floor) noexcept {
    Record record{};
    record[0] = 'R'; record[1] = 'N'; record[2] = 'V'; record[3] = 'S';
    record[4] = 1; record[5] = 1; // Development version and commissioned marker.
    for (unsigned i = 0; i < 8; ++i) {
        record[8 + i] = static_cast<std::uint8_t>(floor >> (8 * i));
        record[16 + i] = static_cast<std::uint8_t>(~floor >> (8 * i));
    }
    const auto checksum = crc32(record.data(), 24);
    for (unsigned i = 0; i < 4; ++i) record[24 + i] = static_cast<std::uint8_t>(checksum >> (8 * i));
    return record;
}
JournalError NvsBootIdentity::reject(esp_err_t error, JournalError result) noexcept {
    last_error_.store(error);
    return result;
}
JournalError NvsBootIdentity::fail(esp_err_t error, JournalError result, bool poison) noexcept {
    last_error_.store(error);
    state_ = State::faulted;
    fault_result_ = result;
    if (poison) process_faulted.store(true);
    return result;
}
void NvsBootIdentity::release_lease() noexcept {
    if (!lease_owned_) return;
    auto* expected = this;
    partition_lease.compare_exchange_strong(expected, nullptr);
    lease_owned_ = false;
}

JournalError NvsBootIdentity::read_record(std::uint64_t& floor) noexcept {
    std::size_t length = 0;
    auto error = nvs_get_blob(handle_, record_key, nullptr, &length);
    if (error != ESP_OK) return reject(error, classify(error));
    if (length != Record{}.size()) return reject(ESP_ERR_NVS_INVALID_LENGTH, JournalError::corrupt);
    Record bytes{};
    error = nvs_get_blob(handle_, record_key, bytes.data(), &length);
    if (error != ESP_OK) return reject(error, classify(error));
    if (length != bytes.size()) return reject(ESP_ERR_NVS_INVALID_LENGTH, JournalError::corrupt);
    const auto parsed = read64(bytes.data() + 8);
    if (bytes != serialize(parsed)) return reject(ESP_ERR_INVALID_STATE, JournalError::corrupt);
    floor = parsed;
    return JournalError::none;
}

JournalError NvsBootIdentity::cleanup_owned() noexcept {
    // Called only inside an operation after verifying the opening worker.
    if (cleanup_failed_) return JournalError::io;
    if (handle_owned_) { nvs_close(handle_); handle_owned_ = false; }
    if (init_owned_) {
        const auto error = nvs_flash_deinit_partition(partition_label);
        if (error != ESP_OK) {
            // Cleanup did not establish release. Quarantine, do not blindly
            // retry deinit from destruction or allow another process-local user.
            cleanup_failed_ = true;
            process_faulted.store(true);
            return fail(error, JournalError::io, true);
        }
        init_owned_ = false;
    }
    release_lease();
    return JournalError::none;
}

JournalError NvsBootIdentity::open_existing(const PartitionSpec& spec) noexcept {
    if (!enabled_) return reject(ESP_ERR_NOT_ALLOWED);
    Operation operation(busy_);
    if (!operation.acquired()) return reject(ESP_ERR_INVALID_STATE);
    if (state_ == State::faulted) return fault_result_;
    if (state_ != State::fresh || process_faulted.load()) return reject(ESP_ERR_INVALID_STATE);
    if (!fixed_spec(spec)) return fail(ESP_ERR_INVALID_ARG, JournalError::io, false);
    owner_task_ = xTaskGetCurrentTaskHandle();
    if (owner_task_ == nullptr) return fail(ESP_ERR_INVALID_STATE, JournalError::io, false);
    NvsBootIdentity* vacant = nullptr;
    if (!partition_lease.compare_exchange_strong(vacant, this)) return reject(ESP_ERR_INVALID_STATE);
    lease_owned_ = true;
    // Recheck after claiming: the former owner may have faulted while we waited.
    if (process_faulted.load()) {
        release_lease();
        return fail(ESP_ERR_INVALID_STATE, JournalError::io, false);
    }
    const auto abort_open = [this](esp_err_t error, JournalError result, bool poison = false) noexcept {
        fail(error, result, poison);
        const auto cleanup = cleanup_owned();
        return cleanup == JournalError::none ? result : cleanup;
    };
    const auto* partition = esp_partition_find_first(spec.type, spec.subtype, partition_label);
    if (!partition) return abort_open(ESP_ERR_NOT_FOUND, JournalError::unprovisioned);
    if (partition->type != spec.type || partition->subtype != spec.subtype ||
        partition->address != spec.address || partition->size != spec.size ||
        std::strncmp(partition->label, partition_label, sizeof(partition->label)) != 0 ||
        partition->encrypted || partition->readonly)
        return abort_open(ESP_ERR_INVALID_ARG, JournalError::corrupt);

    // Reject erased storage before NVS initialization can create/recover pages.
    // 256 bytes of stack, at most 256 reads for the approved 64 KiB partition.
    std::array<std::uint8_t, 256> chunk{};
    bool non_erased = false;
    for (std::size_t offset = 0; offset < spec.size; offset += chunk.size()) {
        const auto error = esp_partition_read(partition, offset, chunk.data(), chunk.size());
        if (error != ESP_OK) return abort_open(error, JournalError::io);
        if (std::any_of(chunk.begin(), chunk.end(), [](std::uint8_t byte) { return byte != 0xff; })) {
            non_erased = true;
            break;
        }
    }
    if (!non_erased) return abort_open(ESP_ERR_NVS_NOT_FOUND, JournalError::unprovisioned);

    // Do not deinitialize a partition someone else initialized. All users of
    // this fixed partition must honor the application-level exclusive lease.
    nvs_stats_t statistics{};
    const auto existing = nvs_get_stats(partition_label, &statistics);
    if (existing == ESP_OK) return abort_open(ESP_ERR_INVALID_STATE, JournalError::io);
    if (existing != ESP_ERR_NVS_NOT_INITIALIZED && existing != ESP_ERR_NVS_PART_NOT_FOUND)
        return abort_open(existing, classify(existing));
    auto error = nvs_flash_init_partition(partition_label);
    if (error != ESP_OK) {
        // Success/ownership was not established, so do not deinitialize. An
        // implementation may have changed internal state before failing.
        return abort_open(error, classify(error), true);
    }
    init_owned_ = true;
    error = nvs_open_from_partition(partition_label, namespace_name, NVS_READONLY, &handle_);
    if (error != ESP_OK) return abort_open(error, classify(error));
    handle_owned_ = true;
    std::uint64_t original = 0;
    auto result = read_record(original);
    if (result != JournalError::none) return abort_open(last_error_.load(), result);
    nvs_close(handle_); handle_owned_ = false;

    error = nvs_open_from_partition(partition_label, namespace_name, NVS_READWRITE, &handle_);
    if (error != ESP_OK) return abort_open(error, classify(error));
    handle_owned_ = true;
    std::uint64_t revalidated = 0;
    result = read_record(revalidated);
    if (result != JournalError::none) return abort_open(last_error_.load(), result);
    if (revalidated != original) return abort_open(ESP_ERR_INVALID_STATE, JournalError::corrupt);
    floor_ = original;
    state_ = State::opened;
    last_error_.store(ESP_OK);
    return JournalError::none;
}

JournalError NvsBootIdentity::allocate_boot(std::uint64_t& output) noexcept {
    if (!enabled_) return reject(ESP_ERR_NOT_ALLOWED);
    Operation operation(busy_);
    if (!operation.acquired()) return reject(ESP_ERR_INVALID_STATE);
    if (state_ == State::faulted) return fault_result_;
    if (state_ != State::opened || process_faulted.load()) return reject(ESP_ERR_INVALID_STATE);
    if (xTaskGetCurrentTaskHandle() != owner_task_) return reject(ESP_ERR_INVALID_STATE);
    std::uint64_t actual = 0;
    auto result = read_record(actual);
    if (result != JournalError::none) return fail(last_error_.load(), result, true);
    if (actual != floor_) return fail(ESP_ERR_INVALID_STATE, JournalError::corrupt, true);
    if (actual == UINT64_MAX) return fail(ESP_ERR_INVALID_STATE, JournalError::exhausted, true);
    const auto next = actual + 1;
    const auto record = serialize(next);
    auto error = nvs_set_blob(handle_, record_key, record.data(), record.size());
    if (error != ESP_OK) return fail(error, classify(error), true);
    error = nvs_commit(handle_);
    if (error != ESP_OK) return fail(error, classify(error), true);
    std::uint64_t verified = 0;
    result = read_record(verified);
    if (result != JournalError::none) return fail(last_error_.load(), result, true);
    if (verified != next) return fail(ESP_ERR_INVALID_STATE, JournalError::corrupt, true);
    floor_ = verified;
    output = verified;
    last_error_.store(ESP_OK);
    return JournalError::none;
}

JournalError NvsBootIdentity::close() noexcept {
    if (!enabled_) return JournalError::none;
    Operation operation(busy_);
    if (!operation.acquired()) return reject(ESP_ERR_INVALID_STATE);
    if (!lease_owned_ && !handle_owned_ && !init_owned_) { state_ = State::closed; return JournalError::none; }
    if (cleanup_failed_) return JournalError::io;
    if (xTaskGetCurrentTaskHandle() != owner_task_) return reject(ESP_ERR_INVALID_STATE);
    const auto result = cleanup_owned();
    if (result == JournalError::none) state_ = State::closed;
    return result;
}

NvsBootIdentity::~NvsBootIdentity() {
    if (!enabled_) return;
    (void)close();
    if (lease_owned_) {
        // Destruction must not race an operation. Wrong-worker destruction or
        // failed deinit cannot safely clean up resources: quarantine this process
        // instead of making SDK calls from the wrong task or leaving a dangling
        // lease pointer that could accidentally compare equal to a new object.
        process_faulted.store(true);
        release_lease();
    }
}
} // namespace poseidon::reef
