#pragma once
// Explicit NVS host fake declarations. No commissioning/erase API is provided.
#include "esp_err.h"
#include <cstddef>
#include <cstdint>
typedef std::uint32_t nvs_handle_t;
enum nvs_open_mode_t { NVS_READONLY, NVS_READWRITE };
struct nvs_stats_t {
    std::size_t used_entries, free_entries, available_entries, total_entries, namespace_count;
};
#define ESP_ERR_NVS_NOT_INITIALIZED 0x1101
#define ESP_ERR_NVS_NOT_FOUND 0x1102
#define ESP_ERR_NVS_TYPE_MISMATCH 0x1103
#define ESP_ERR_NVS_READ_ONLY 0x1104
#define ESP_ERR_NVS_NOT_ENOUGH_SPACE 0x1105
#define ESP_ERR_NVS_INVALID_NAME 0x1106
#define ESP_ERR_NVS_INVALID_HANDLE 0x1107
#define ESP_ERR_NVS_REMOVE_FAILED 0x1108
#define ESP_ERR_NVS_INVALID_STATE 0x110b
#define ESP_ERR_NVS_INVALID_LENGTH 0x110c
#define ESP_ERR_NVS_NO_FREE_PAGES 0x110d
#define ESP_ERR_NVS_PART_NOT_FOUND 0x110f
#define ESP_ERR_NVS_NEW_VERSION_FOUND 0x1110
extern "C" esp_err_t nvs_get_stats(const char*, nvs_stats_t*);
extern "C" esp_err_t nvs_open_from_partition(const char*, const char*, nvs_open_mode_t, nvs_handle_t*);
extern "C" esp_err_t nvs_get_blob(nvs_handle_t, const char*, void*, std::size_t*);
extern "C" esp_err_t nvs_set_blob(nvs_handle_t, const char*, const void*, std::size_t);
extern "C" esp_err_t nvs_commit(nvs_handle_t);
extern "C" void nvs_close(nvs_handle_t);
