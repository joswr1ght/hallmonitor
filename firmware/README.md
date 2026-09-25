# firmware

Firmware for the hallmonitor kit: an M5StickC Plus2 paired with a Govee sensor. The kit reads the
sensor over BLE, queues readings, joins the strongest known Wi-Fi network, and uploads batches to
the server. Holding the main button starts the setup portal for changing Wi-Fi networks and the
paired sensor.

Not started. The toolchain (Arduino core or MicroPython) is not chosen yet; see Phase 2 in
[../docs/plan.md](../docs/plan.md). This directory will hold the source, the build configuration,
and the flash and provisioning instructions.
