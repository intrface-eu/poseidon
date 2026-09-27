#pragma once
// Host-only function/type surface; no actual device or flash operations.
#include "esp_err.h"
#include <cstddef>
#include <cstdint>

enum esp_partition_type_t { ESP_PARTITION_TYPE_APP = 0, ESP_PARTITION_TYPE_DATA = 1 };
enum esp_partition_subtype_t { ESP_PARTITION_SUBTYPE_DATA_NVS = 2 };
struct esp_partition_t {
    void* flash_chip;
    esp_partition_type_t type;
    esp_partition_subtype_t subtype;
    std::uint32_t address;
    std::uint32_t size;
    std::uint32_t erase_size;
    char label[17];
    bool encrypted;
    bool readonly;
};
extern "C" const esp_partition_t* esp_partition_find_first(esp_partition_type_t, esp_partition_subtype_t, const char*);
extern "C" esp_err_t esp_partition_read(const esp_partition_t*, std::size_t, void*, std::size_t);
