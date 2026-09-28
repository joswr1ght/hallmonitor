// Kit settings stored in flash (NVS), and the serial commands that provision them.
#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>
#include <vector>

struct Network {
    String ssid;
    String psk;
    // Set when an instructor adds or edits the network in the setup portal. Once deployed, the
    // instructor's changes are the source of truth, so the server never overrides these entries.
    bool instructor;
};

struct KitConfig {
    uint32_t kitId = 0;
    String server;      // for example https://hallmonitor.willhackforsushi.com
    String token;       // from the server's add-kit command
    String course;      // for example SEC504
    String instructor;  // for example Josh Wright
    String sensor;      // the paired Govee sensor's name (Govee_H5074_67B3) or Bluetooth address
    std::vector<Network> networks;
};

extern KitConfig config;

void loadConfig();
void saveConfig();
// True when the kit has everything it needs to report: server, token, sensor, and a network.
bool configComplete();
// Replace the networks that came from provisioning or the server with `incoming`, keeping every
// network an instructor set in the setup portal. Returns true if the list changed.
bool mergeNetworks(JsonArrayConst incoming);
// Handle one line from the USB serial port. See firmware/README.md for the commands.
void handleSerialCommand(const String& line);
