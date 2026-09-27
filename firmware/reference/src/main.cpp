#include "poseidon/reef.hpp"
#include "reference_config.hpp"

// Compile-only translation unit: no sensor, GPIO, bus, network, storage, radio,
// actuator, or sleep-driver calls. No physical target execution is authorized.
extern "C" void app_main() {
    poseidon::telemetry::Frame synthetic;
    synthetic.boot_id = 1;
    poseidon::telemetry::Packet packet;
    const auto result = poseidon::telemetry::encode(synthetic, packet);
    (void)result;
    static_assert(!poseidon::reference::hardware_io_authorized, "reference must stay compile-only");
}
