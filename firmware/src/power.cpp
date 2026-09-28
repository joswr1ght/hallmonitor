#include "power.h"

#include <M5Unified.h>

// The level comes from the battery voltage, which wobbles with load and with the charger cycling
// near full, so the kit reports the average of the past minute of once-a-second samples.
static const size_t SAMPLES = 60;
// USB supplies 5 V; anything above this means the kit is plugged in.
static const int USB_MV = 4000;

static int levels[SAMPLES];
static size_t count = 0, next = 0;
static bool usb = false;
static uint32_t lastSampleMs = 0;

// The StickS3's power chip reports the USB voltage. The Plus2's cannot (-1), so it falls back to the
// charger's status pin, which is all that board offers. That pin reports what the charger is doing,
// not whether USB is present, so it flickers once the battery is nearly full.
static bool readUsb() {
    int vbus = M5.Power.getVBUSVoltage();
    if (vbus >= 0) return vbus > USB_MV;
    return M5.Power.isCharging() == m5::Power_Class::is_charging;
}

void powerTick() {
    if (lastSampleMs && millis() - lastSampleMs < 1000) return;
    lastSampleMs = millis();
    usb = readUsb();
    int level = M5.Power.getBatteryLevel();
    if (level < 0) return;
    levels[next] = level;
    next = (next + 1) % SAMPLES;
    if (count < SAMPLES) count++;
}

bool powerOnUsb() { return usb; }

int powerBatteryLevel() {
    if (count == 0) return -1;
    int sum = 0;
    for (size_t i = 0; i < count; i++) sum += levels[i];
    return (sum + count / 2) / count;
}
