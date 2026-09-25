#include "config.h"

#include <ArduinoJson.h>
#include <Preferences.h>

#include "govee.h"

KitConfig config;

// The settings are one JSON document stored as an NVS blob. A string would be capped at 4,000 bytes,
// which the SANS class network list alone comes close to.
static Preferences prefs;

void loadConfig() {
    prefs.begin("hallmon", true);
    std::vector<char> stored(prefs.getBytesLength("config"));
    prefs.getBytes("config", stored.data(), stored.size());
    prefs.end();

    JsonDocument doc;
    if (stored.empty() || deserializeJson(doc, stored.data(), stored.size())) return;
    config.kitId = doc["kit_id"] | 0;
    config.server = doc["server"] | "";
    config.token = doc["token"] | "";
    config.course = doc["course"] | "";
    config.instructor = doc["instructor"] | "";
    config.sensor = doc["sensor"] | "";
    config.networks.clear();
    for (JsonObject n : doc["networks"].as<JsonArray>()) {
        config.networks.push_back({n["ssid"] | "", n["psk"] | "", n["instructor"] | false});
    }
}

void saveConfig() {
    JsonDocument doc;
    doc["kit_id"] = config.kitId;
    doc["server"] = config.server;
    doc["token"] = config.token;
    doc["course"] = config.course;
    doc["instructor"] = config.instructor;
    doc["sensor"] = config.sensor;
    JsonArray networks = doc["networks"].to<JsonArray>();
    for (auto& n : config.networks) {
        JsonObject o = networks.add<JsonObject>();
        o["ssid"] = n.ssid;
        o["psk"] = n.psk;
        o["instructor"] = n.instructor;
    }
    String out;
    serializeJson(doc, out);
    prefs.begin("hallmon", false);
    prefs.putBytes("config", out.c_str(), out.length());
    prefs.end();
}

bool configComplete() {
    return !config.server.isEmpty() && !config.token.isEmpty() && !config.sensor.isEmpty() &&
           !config.networks.empty();
}

// Instructor entries win on a conflicting SSID, since the instructor's changes are the source of
// truth for a deployed kit.
bool mergeNetworks(JsonArrayConst incoming) {
    std::vector<Network> merged;
    for (auto& n : config.networks) {
        if (n.instructor) merged.push_back(n);
    }
    for (JsonObjectConst n : incoming) {
        String ssid = n["ssid"] | "";
        if (ssid.isEmpty()) continue;
        bool taken = false;
        for (auto& m : merged) taken |= m.ssid == ssid;
        if (!taken) merged.push_back({ssid, n["psk"] | "", false});
    }
    bool changed = merged.size() != config.networks.size();
    for (size_t i = 0; !changed && i < merged.size(); i++) {
        const Network &a = merged[i], &b = config.networks[i];
        changed = a.ssid != b.ssid || a.psk != b.psk || a.instructor != b.instructor;
    }
    config.networks = merged;
    return changed;
}

static void reply(bool ok, const char* error = nullptr) {
    JsonDocument doc;
    doc["ok"] = ok;
    if (error) doc["error"] = error;
    serializeJson(doc, Serial);
    Serial.println();
}

// Print the settings without secrets: the token and the network passwords never leave the kit.
static void showConfig() {
    JsonDocument doc;
    doc["kit_id"] = config.kitId;
    doc["server"] = config.server;
    doc["token_set"] = !config.token.isEmpty();
    doc["course"] = config.course;
    doc["instructor"] = config.instructor;
    doc["sensor"] = config.sensor;
    JsonArray networks = doc["networks"].to<JsonArray>();
    for (auto& n : config.networks) {
        JsonObject o = networks.add<JsonObject>();
        o["ssid"] = n.ssid;
        o["instructor"] = n.instructor;
    }
    doc["complete"] = configComplete();
    serializeJson(doc, Serial);
    Serial.println();
}

static void listSensors() {
    JsonDocument doc;
    JsonArray list = doc.to<JsonArray>();
    for (auto& r : goveeHeard(15 * 60 * 1000)) {
        JsonObject o = list.add<JsonObject>();
        o["name"] = r.name;
        o["address"] = r.address;
        o["rssi"] = r.rssi;
        o["celsius"] = r.celsius;
        o["humidity"] = r.humidity;
        o["battery"] = r.battery;
        o["age_s"] = (millis() - r.heardMs) / 1000;
    }
    serializeJson(doc, Serial);
    Serial.println();
}

void handleSerialCommand(const String& line) {
    int space = line.indexOf(' ');
    String command = space < 0 ? line : line.substring(0, space);
    String arg = space < 0 ? "" : line.substring(space + 1);

    if (command == "show") {
        showConfig();
    } else if (command == "sensors") {
        listSensors();
    } else if (command == "reboot") {
        reply(true);
        Serial.flush();
        ESP.restart();
    } else if (command == "config") {
        // config {"kit_id": 1, "server": "...", "token": "...", "course": "...", "instructor": "...",
        //         "sensor": "...", "networks": [{"ssid": "...", "psk": "..."}]}
        // Keys that are left out keep their current values.
        JsonDocument doc;
        if (deserializeJson(doc, arg) || !doc.is<JsonObject>()) {
            reply(false, "expected: config {json}");
            return;
        }
        if (doc["kit_id"].is<uint32_t>()) config.kitId = doc["kit_id"];
        if (doc["server"].is<const char*>()) config.server = doc["server"].as<const char*>();
        if (doc["token"].is<const char*>()) config.token = doc["token"].as<const char*>();
        if (doc["course"].is<const char*>()) config.course = doc["course"].as<const char*>();
        if (doc["instructor"].is<const char*>()) config.instructor = doc["instructor"].as<const char*>();
        if (doc["sensor"].is<const char*>()) config.sensor = doc["sensor"].as<const char*>();
        if (doc["networks"].is<JsonArray>()) mergeNetworks(doc["networks"].as<JsonArrayConst>());
        saveConfig();
        reply(true);
    } else if (!command.isEmpty()) {
        reply(false, "commands: show, sensors, config {json}, reboot");
    }
}
