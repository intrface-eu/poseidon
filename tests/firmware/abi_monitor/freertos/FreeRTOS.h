#pragma once
#include <cstdint>
using BaseType_t = int;
using UBaseType_t = unsigned;
using TickType_t = std::uint32_t;
constexpr BaseType_t pdPASS = 1;
constexpr BaseType_t pdFAIL = 0;
constexpr BaseType_t pdTRUE = 1;
constexpr BaseType_t pdFALSE = 0;
constexpr TickType_t portMAX_DELAY = UINT32_MAX;
#define configTICK_RATE_HZ 100
