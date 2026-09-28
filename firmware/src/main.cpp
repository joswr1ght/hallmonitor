// hallmonitor kit firmware: reads the paired Govee sensor over BLE, uploads readings to the
// hallmonitor server, and shows its status on the screen. Provisioned over USB serial; see
// firmware/README.md.
#include <M5Unified.h>

#include "config.h"
#include "display.h"
#include "govee.h"
#include "portal.h"
#include "power.h"
#include "reporter.h"

// Long enough for a config line carrying the full SANS class network list with room to grow.
static const size_t MAX_LINE = 16384;
static String serialLine;

static void readSerial() {
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n') {
            serialLine.trim();
            handleSerialCommand(serialLine);
            serialLine = "";
        } else if (serialLine.length() < MAX_LINE) {
            serialLine += c;
        }
    }
}

void setup() {
    // The main loop can block for seconds while joining Wi-Fi, so the serial port buffers a whole
    // config line. The buffer size must be set before Serial.begin, so M5.begin skips the serial port.
    Serial.setRxBufferSize(MAX_LINE);
    Serial.begin(115200);
    auto cfg = M5.config();
    cfg.serial_baudrate = 0;
#ifdef PLUS2_BUZZER
    cfg.internal_spk = false;  // the portal drives the buzzer with tone() instead
#endif
    M5.begin(cfg);
    loadConfig();
    displayBegin();
    goveeBegin();
    reporterBegin();
}

void loop() {
    M5.update();
    readSerial();
    powerTick();
    if (portalActive()) {
        portalTick();
    } else if (M5.BtnA.pressedFor(3000)) {
        portalStart();
    } else {
        reporterTick();
        displayTick();
    }
    delay(20);
}
