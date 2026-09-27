#pragma once
#include "FreeRTOS.h"
#include <cstddef>
struct FakeTask;
using TaskHandle_t = FakeTask*;
using TaskFunction_t = void (*)(void*);
enum eNotifyAction { eNoAction, eSetBits, eIncrement, eSetValueWithOverwrite, eSetValueWithoutOverwrite };
extern "C" {
BaseType_t xTaskCreate(TaskFunction_t entry, const char* name, std::uint32_t stack_bytes,
                       void* argument, UBaseType_t priority, TaskHandle_t* output);
TaskHandle_t xTaskGetCurrentTaskHandle();
BaseType_t xTaskGenericNotify(TaskHandle_t task, UBaseType_t index, std::uint32_t value,
                              eNotifyAction action, std::uint32_t* previous);
std::uint32_t ulTaskGenericNotifyTake(UBaseType_t index, BaseType_t clear, TickType_t ticks);
void vTaskDelay(TickType_t ticks);
void vTaskDelete(TaskHandle_t task);
}
#define xTaskNotifyGive(task) xTaskGenericNotify((task), 0, 0, eIncrement, nullptr)
#define ulTaskNotifyTake(clear, ticks) ulTaskGenericNotifyTake(0, (clear), (ticks))
