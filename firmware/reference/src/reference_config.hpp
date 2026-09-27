#pragma once

namespace poseidon::reference {
// Reserved from hardware/interfaces/reference-v1.json revision HW-REF-1.1,
// MCU-01 ESP32-DevKitC-32E. These constants do not configure any hardware.
constexpr char hardware_revision[] = "HW-REF-1.1";
constexpr int provisional_radio_uart_tx_gpio = 17;
constexpr int provisional_radio_uart_rx_gpio = 16;
constexpr int provisional_probe_i2c_sda_gpio = 21;
constexpr int provisional_probe_i2c_scl_gpio = 22;
constexpr char provisional_radio_region[] = "EU868_CANDIDATE_NOT_APPROVED";
constexpr bool hardware_io_authorized = false;
} // namespace poseidon::reference
