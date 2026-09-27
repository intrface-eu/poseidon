#include "poseidon/monitor_task.hpp"

#ifndef POSEIDON_MONITOR_PERSISTED
#define POSEIDON_MONITOR_PERSISTED 0
#endif
#if POSEIDON_MONITOR_PERSISTED != 0 && POSEIDON_MONITOR_PERSISTED != 1
#error "monitor persistence is a fixed build-time gate"
#endif

namespace {
poseidon::reef::MonitorTask monitor(POSEIDON_MONITOR_PERSISTED == 1);
// Debugger-only bounded status. No UART/log/network/device output path.
volatile poseidon::reef::MonitorError startup_result = poseidon::reef::MonitorError::disabled;
}

extern "C" void app_main() {
    // Default profile: constructor/start/destructor paths call zero SDK APIs.
    // Explicit persisted profile: creates the real worker, which alone opens
    // existing commissioned NVS, allocates identity, polls Runtime and owns timer
    // cleanup. No baseline, sensor, voltage, radio, or update fallback exists.
    startup_result = monitor.start(poseidon::reef::Config{});
}
