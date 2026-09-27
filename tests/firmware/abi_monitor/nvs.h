#pragma once
#include "esp_err.h"
#include <cstddef>
#include <cstdint>
using nvs_handle_t = std::uint32_t;
enum nvs_open_mode_t { NVS_READONLY = 0, NVS_READWRITE = 1 };
struct nvs_stats_t { std::size_t used_entries, free_entries, total_entries, namespace_count; };
constexpr esp_err_t ESP_ERR_NVS_NOT_INITIALIZED = 0x1101;
constexpr esp_err_t ESP_ERR_NVS_NOT_FOUND = 0x1102;
constexpr esp_err_t ESP_ERR_NVS_TYPE_MISMATCH = 0x1103;
constexpr esp_err_t ESP_ERR_NVS_INVALID_LENGTH = 0x110c;
constexpr esp_err_t ESP_ERR_NVS_PART_NOT_FOUND = 0x110f;
constexpr esp_err_t ESP_ERR_NVS_NEW_VERSION_FOUND = 0x1110;
extern "C" {
esp_err_t nvs_get_stats(const char*, nvs_stats_t*);
esp_err_t nvs_open_from_partition(const char*, const char*, nvs_open_mode_t, nvs_handle_t*);
esp_err_t nvs_get_blob(nvs_handle_t, const char*, void*, std::size_t*);
esp_err_t nvs_set_blob(nvs_handle_t, const char*, const void*, std::size_t);
esp_err_t nvs_commit(nvs_handle_t);
void nvs_close(nvs_handle_t);
}
