#include "govee.h"

#include <NimBLEDevice.h>
#include <map>
#include <mutex>

// Govee puts its readings in manufacturer-specific data under company ID 0xEC88, which appears on
// air (and at the start of NimBLE's manufacturer data) as the bytes 88 EC.
static const uint8_t GOVEE_ID[] = {0x88, 0xEC};
// Forget sensors not heard for this long, so the table stays small at a busy venue.
static const uint32_t FORGET_MS = 15 * 60 * 1000;

// `value` is the manufacturer data after the two company ID bytes, matching client/hallclient.py.
typedef bool (*Decoder)(const uint8_t* value, size_t len, float& celsius, float& humidity, int& battery);

// H5074 and H5051: signed hundredths of a degree C, hundredths of a percent RH, battery percent.
static bool decodeH5074(const uint8_t* v, size_t len, float& celsius, float& humidity, int& battery) {
    if (len < 6) return false;
    celsius = (int16_t)(v[1] | v[2] << 8) / 100.0f;
    humidity = (uint16_t)(v[3] | v[4] << 8) / 100.0f;
    battery = v[5];
    return true;
}

// H5075 and H5072: temperature and humidity packed into one 24-bit big-endian integer, where the
// low three decimal digits are humidity in tenths of a percent and the rest is temperature in
// tenths of a degree C. Bit 23 flags a negative temperature.
static bool decodeH5075(const uint8_t* v, size_t len, float& celsius, float& humidity, int& battery) {
    if (len < 5) return false;
    uint32_t packed = (uint32_t)v[1] << 16 | (uint32_t)v[2] << 8 | v[3];
    bool negative = packed & 0x800000;
    packed &= 0x7FFFFF;
    celsius = (packed / 1000) / 10.0f * (negative ? -1 : 1);
    humidity = (packed % 1000) / 10.0f;
    battery = v[4];
    return true;
}

// Supporting a new Govee model means adding one row here (see H5 in docs/plan.md).
static const struct {
    const char* model;
    Decoder decode;
} DECODERS[] = {
    {"H5074", decodeH5074},
    {"H5051", decodeH5074},
    {"H5075", decodeH5075},
    {"H5072", decodeH5075},
};

static std::mutex tableLock;
static std::map<std::string, GoveeReading> table;  // keyed by address

class ScanCallbacks : public NimBLEScanCallbacks {
    void onResult(const NimBLEAdvertisedDevice* device) override {
        std::string name = device->getName();
        if (name.empty()) return;
        Decoder decode = nullptr;
        for (auto& d : DECODERS) {
            if (name.find(d.model) != std::string::npos) {
                decode = d.decode;
                break;
            }
        }
        if (!decode) return;
        // Govee sensors can advertise more than one manufacturer data record (the H5074 also sends
        // an Apple beacon), so look for the one under Govee's company ID.
        for (uint8_t i = 0; i < device->getManufacturerDataCount(); i++) {
            std::string data = device->getManufacturerData(i);
            if (data.size() < 2 || (uint8_t)data[0] != GOVEE_ID[0] || (uint8_t)data[1] != GOVEE_ID[1]) continue;
            GoveeReading r;
            if (!decode((const uint8_t*)data.data() + 2, data.size() - 2, r.celsius, r.humidity, r.battery)) return;
            r.name = name.c_str();
            r.address = device->getAddress().toString().c_str();
            r.rssi = device->getRSSI();
            r.heardMs = millis();
            std::lock_guard<std::mutex> guard(tableLock);
            table[device->getAddress().toString()] = r;
            return;
        }
    }

    void onScanEnd(const NimBLEScanResults& results, int reason) override {
        // The scan is meant to run forever; restart it if the stack ever ends it.
        NimBLEDevice::getScan()->start(0, false, true);
    }
};

static ScanCallbacks callbacks;

void goveeBegin() {
    NimBLEDevice::init("");
    NimBLEScan* scan = NimBLEDevice::getScan();
    // Report every advertisement, not just the first from each device, since each one carries a
    // new reading. Active scanning is needed to receive the local name, which picks the decoder.
    scan->setScanCallbacks(&callbacks, true);
    scan->setDuplicateFilter(0);
    scan->setActiveScan(true);
    // Listen half the time, leaving the shared radio to Wi-Fi the other half (H8 in docs/plan.md).
    scan->setInterval(100);
    scan->setWindow(50);
    scan->setMaxResults(0);
    scan->start(0, false, true);
}

std::vector<GoveeReading> goveeHeard(uint32_t maxAgeMs) {
    std::vector<GoveeReading> heard;
    uint32_t now = millis();
    {
        std::lock_guard<std::mutex> guard(tableLock);
        for (auto it = table.begin(); it != table.end();) {
            uint32_t age = now - it->second.heardMs;
            if (age > FORGET_MS) {
                it = table.erase(it);
                continue;
            }
            if (age <= maxAgeMs) heard.push_back(it->second);
            ++it;
        }
    }
    std::sort(heard.begin(), heard.end(), [](const GoveeReading& a, const GoveeReading& b) { return a.rssi > b.rssi; });
    return heard;
}

bool goveeLatest(const String& sensor, uint32_t maxAgeMs, GoveeReading& out) {
    if (sensor.isEmpty()) return false;
    for (auto& r : goveeHeard(maxAgeMs)) {
        if (r.name == sensor || r.address.equalsIgnoreCase(sensor)) {
            out = r;
            return true;
        }
    }
    return false;
}
