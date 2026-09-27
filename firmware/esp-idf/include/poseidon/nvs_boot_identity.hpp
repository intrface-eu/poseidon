#pragma once

#include "poseidon/reef.hpp"
#include "esp_err.h"
#include "esp_partition.h"
#include "nvs.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include <array>
#include <atomic>
#include <cstdint>

namespace poseidon::reef {

// Development format/layout only. These are not downlink-controlled settings.
// A supplied spec must match every fixed value; no alternate-partition fallback.
struct PartitionSpec {
    const char* label = "reef_state";
    esp_partition_type_t type = ESP_PARTITION_TYPE_DATA;
    esp_partition_subtype_t subtype = ESP_PARTITION_SUBTYPE_DATA_NVS;
    std::uint32_t address = 0x3f0000;
    std::uint32_t size = 0x10000;
    const char* namespace_name = "reef_boot";
    const char* key = "identity_v1";
};

class NvsBootIdentity final : public BootIdentity {
public:
    // No constructor calls into ESP-IDF, even when enabled.
    explicit NvsBootIdentity(bool enabled = false) noexcept : enabled_(enabled) {}
    ~NvsBootIdentity() override;
    NvsBootIdentity(const NvsBootIdentity&) = delete;
    NvsBootIdentity& operator=(const NvsBootIdentity&) = delete;
    NvsBootIdentity(NvsBootIdentity&&) = delete;
    NvsBootIdentity& operator=(NvsBootIdentity&&) = delete;

    // Opening, allocating and closing must occur in the same FreeRTOS worker.
    // Disabled paths, including close/destruction, make zero SDK/RTOS calls.
    JournalError open_existing(const PartitionSpec& spec = PartitionSpec{}) noexcept;
    JournalError allocate_boot(std::uint64_t& output) noexcept override;
    JournalError close() noexcept;
    esp_err_t last_esp_error() const noexcept { return last_error_.load(); }

private:
    using Record = std::array<std::uint8_t, 32>;
    enum class State { fresh, opened, faulted, closed };
    JournalError reject(esp_err_t error, JournalError result = JournalError::io) noexcept;
    JournalError fail(esp_err_t error, JournalError result, bool process_fault) noexcept;
    JournalError read_record(std::uint64_t& floor) noexcept;
    JournalError cleanup_owned() noexcept;
    void release_lease() noexcept;
    static Record serialize(std::uint64_t floor) noexcept;

    const bool enabled_;
    std::atomic_flag busy_ = ATOMIC_FLAG_INIT;
    std::atomic<esp_err_t> last_error_{ESP_OK};
    State state_ = State::fresh;
    JournalError fault_result_ = JournalError::io;
    TaskHandle_t owner_task_ = nullptr;
    bool lease_owned_ = false;
    bool init_owned_ = false;
    bool handle_owned_ = false;
    bool cleanup_failed_ = false;
    nvs_handle_t handle_ = 0;
    std::uint64_t floor_ = 0;
};

} // namespace poseidon::reef
