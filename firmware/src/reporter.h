// Wi-Fi, clock, the readings queue, and uploads to the hallmonitor server.
#pragma once

#include <Arduino.h>

struct ReporterStatus {
    bool wifiConnected = false;
    String ssid;
    int wifiRssi = 0;
    bool timeValid = false;
    size_t queued = 0;
    uint32_t lastUploadMs = 0;  // millis() of the last successful upload, 0 if none yet
    String error;               // the last upload problem, empty after a success
};

extern ReporterStatus reporter;

void reporterBegin();
// Call from loop(): keeps Wi-Fi and the clock up, records a reading every 5 minutes, and uploads.
void reporterTick();
