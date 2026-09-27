#pragma once
// Host-only fake. Erase/reset/commissioning APIs intentionally absent.
#include "esp_err.h"
extern "C" esp_err_t nvs_flash_init_partition(const char*);
extern "C" esp_err_t nvs_flash_deinit_partition(const char*);
