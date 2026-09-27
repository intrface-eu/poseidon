#include "esp_ota_ops.h"
#include <type_traits>

namespace poseidon::reference {
// Compile-only ABI bindings to ESP-IDF 5.3.1. No function below is invoked by
// app_main. Taking addresses does not read/write partitions, confirm an image,
// reboot, program eFuses, or validate a signature. This is not an update agent.
struct OtaApiBindings {
    const esp_partition_t* (*running_partition)();
    esp_err_t (*image_state)(const esp_partition_t*, esp_ota_img_states_t*);
    esp_err_t (*confirm_running_image)();
    esp_err_t (*rollback_and_reboot)();
};
static_assert(std::is_same<decltype(&esp_ota_get_running_partition), decltype(OtaApiBindings::running_partition)>::value, "running partition API changed");
static_assert(std::is_same<decltype(&esp_ota_get_state_partition), decltype(OtaApiBindings::image_state)>::value, "image state API changed");
static_assert(std::is_same<decltype(&esp_ota_mark_app_valid_cancel_rollback), decltype(OtaApiBindings::confirm_running_image)>::value, "confirm API changed");
static_assert(std::is_same<decltype(&esp_ota_mark_app_invalid_rollback_and_reboot), decltype(OtaApiBindings::rollback_and_reboot)>::value, "rollback API changed");
static_assert(ESP_OTA_IMG_PENDING_VERIFY != ESP_OTA_IMG_VALID, "trial boot must remain distinct from confirmed state");

// Deliberately not declared in the application interface and never called.
// Real update integration must add authenticated manifest verification, bounded
// image handling and an independently reviewed health-confirmation policy.
const OtaApiBindings& ota_api_compile_bindings() noexcept {
    static constexpr OtaApiBindings bindings{
        &esp_ota_get_running_partition,
        &esp_ota_get_state_partition,
        &esp_ota_mark_app_valid_cancel_rollback,
        &esp_ota_mark_app_invalid_rollback_and_reboot,
    };
    return bindings;
}
} // namespace poseidon::reference
