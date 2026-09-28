// Govee BLE thermometer and hygrometer scanning and decoding.
#pragma once

#include <Arduino.h>
#include <vector>

struct GoveeReading {
    String name;      // advertised local name, for example Govee_H5074_67B3
    String address;   // Bluetooth address, for example a4:c1:38:00:c0:a6
    float celsius = 0;
    float humidity = 0;
    int battery = 0;
    int rssi = 0;
    uint32_t heardMs = 0;  // millis() when this reading arrived
};

// Start a continuous BLE scan that records every Govee sensor it hears.
void goveeBegin();
// Every Govee sensor heard within maxAgeMs, strongest signal first. The setup portal and the
// serial "sensors" command list these so the right sensor can be picked.
std::vector<GoveeReading> goveeHeard(uint32_t maxAgeMs);
// The latest reading from the sensor matching `sensor` (a name or an address), if heard within maxAgeMs.
bool goveeLatest(const String& sensor, uint32_t maxAgeMs, GoveeReading& out);
