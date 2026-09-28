// The kit's own power: whether it runs on USB, and its battery level.
#pragma once

// Sample the power chip; call from loop(). It samples at most once a second.
void powerTick();
// Whether the kit runs on USB power.
bool powerOnUsb();
// The battery level in percent, averaged over the past minute, or -1 when it cannot be read.
int powerBatteryLevel();
