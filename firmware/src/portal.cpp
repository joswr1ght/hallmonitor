#include "portal.h"

#include <DNSServer.h>
#include <M5Unified.h>
#include <WebServer.h>
#include <WiFi.h>

#include "config.h"
#include "govee.h"
#include "reporter.h"

static const uint32_t IDLE_MS = 10 * 60 * 1000;
// How long to wait while testing a network's password before calling it a failure.
static const uint32_t TEST_MS = 15 * 1000;
// Longest instructor name the server accepts (MAX_LABEL in server/hallmonitor.py).
static const size_t MAX_LABEL = 40;
#ifdef PLUS2_BUZZER
// The Plus2's passive buzzer. Arduino's tone() drives it directly; on the Plus2, M5Unified's
// speaker driver needs more IRAM than the firmware has left.
static const int BUZZER_PIN = 2;
#endif

static DNSServer dns;
static WebServer server(80);
static bool active = false;
static uint32_t lastActivityMs = 0;
static String apName, apPassword;
static String notice;       // the result of the last change, shown at the top of the page
static String screenNote;   // a short version of it for the kit's screen

struct Seen {
    String ssid;
    int rssi;
};
static std::vector<Seen> seen;  // networks from the last Wi-Fi scan, strongest first

bool portalActive() { return active; }

// Letters and digits that are hard to confuse on a small screen: no 0/o, 1/l/i.
static String randomPassword() {
    const char* chars = "abcdefghjkmnpqrstuvwxyz23456789";
    String out;
    for (int i = 0; i < 8; i++) out += chars[esp_random() % strlen(chars)];
    return out;
}

static String html(const String& text) {
    String out;
    for (char c : text) {
        switch (c) {
            case '&': out += "&amp;"; break;
            case '<': out += "&lt;"; break;
            case '>': out += "&gt;"; break;
            case '"': out += "&quot;"; break;
            case '\'': out += "&#39;"; break;
            default: out += c;
        }
    }
    return out;
}

static String ago(uint32_t ms) {
    uint32_t s = ms / 1000;
    if (s < 60) return String(s) + " s";
    if (s < 3600) return String(s / 60) + " min";
    return String(s / 3600) + " h";
}

static void drawScreen() {
    M5.Display.fillScreen(TFT_WHITE);
    // A phone camera joins the network from this QR code without typing the password.
    String qr = "WIFI:T:WPA;S:" + apName + ";P:" + apPassword + ";;";
    M5.Display.qrcode(qr.c_str(), 2, 2, 131, 1);
    M5.Display.setTextColor(TFT_BLACK, TFT_WHITE);
    M5.Display.setTextDatum(top_left);
    M5.Display.setFont(&fonts::Font2);
    int x = 140;
    M5.Display.drawString("Network", x, 4);
    M5.Display.drawString(apName, x, 20);
    M5.Display.drawString("Password", x, 42);
    M5.Display.setFont(&fonts::Font4);
    M5.Display.drawString(apPassword.substring(0, 4), x, 58);
    M5.Display.drawString(apPassword.substring(4), x, 80);
    M5.Display.setFont(&fonts::Font2);
    M5.Display.drawString("192.168.4.1", x, 104);
    M5.Display.setTextColor(screenNote.isEmpty() ? TFT_DARKGREY : TFT_BLUE, TFT_WHITE);
    M5.Display.drawString(screenNote.isEmpty() ? "Press to exit" : screenNote, x, 120);
}

static void scanNetworks() {
    seen.clear();
    int n = WiFi.scanNetworks();
    for (int i = 0; i < n; i++) {
        String ssid = WiFi.SSID(i);
        if (ssid.isEmpty()) continue;
        bool dup = false;
        for (auto& s : seen) dup |= s.ssid == ssid;  // one row per SSID, however many access points
        if (!dup) seen.push_back({ssid, WiFi.RSSI(i)});
    }
    WiFi.scanDelete();
    std::sort(seen.begin(), seen.end(), [](const Seen& a, const Seen& b) { return a.rssi > b.rssi; });
}

static int signalFor(const String& ssid) {
    for (auto& s : seen) {
        if (s.ssid == ssid) return s.rssi;
    }
    return 0;
}

static void redirectHome() {
    server.sendHeader("Location", "http://192.168.4.1/");
    server.send(303);
}

static const char* PAGE_CSS =
    "body{font-family:system-ui,sans-serif;margin:0 auto;padding:12px;max-width:560px;color:#111}"
    "h1{font-size:1.2rem}h2{font-size:1rem;margin:22px 0 6px;border-top:1px solid #ddd;padding-top:12px}"
    ".notice{background:#eef4ff;border-left:4px solid #2a78d6;padding:8px}.muted{color:#777}"
    "label{display:block;margin:6px 0}input[type=text],input[type=password]{width:100%;padding:8px;"
    "font-size:1rem;box-sizing:border-box}button{font-size:1rem;padding:8px 14px;margin-top:8px}"
    "table{width:100%;border-collapse:collapse}td{padding:4px 2px;border-bottom:1px solid #eee}";

static void handleRoot() {
    lastActivityMs = millis();
    String p;
    p.reserve(12000);
    p += "<!doctype html><html><head><meta charset=utf-8>"
         "<meta name=viewport content='width=device-width,initial-scale=1'><title>" + html(apName) +
         "</title><style>" + String(PAGE_CSS) + "</style></head><body>";
    p += "<h1>Kit " + String(config.kitId) + " setup</h1>";
    if (!notice.isEmpty()) p += "<p class=notice>" + html(notice) + "</p>";

    // Status
    p += "<h2>Status</h2><p>" + html(config.instructor) + "<br>";
    GoveeReading r;
    if (goveeLatest(config.sensor, 15 * 60 * 1000, r)) {
        p += "Sensor " + html(r.name) + ": " + String(r.celsius * 9 / 5 + 32, 1) + "&#176;F, " +
             String(r.humidity, 0) + "%, heard " + ago(millis() - r.heardMs) + " ago<br>";
    } else {
        p += "Sensor " + html(config.sensor.isEmpty() ? "(none)" : config.sensor) + ": not heard<br>";
    }
    p += reporter.lastUploadMs ? "Last upload " + ago(millis() - reporter.lastUploadMs) + " ago"
                               : String("No upload since the kit started");
    p += ", " + String(reporter.queued) + " readings waiting</p>";

    // Wi-Fi: saved networks, then a form to add one or update a password.
    p += "<h2>Wi-Fi</h2><table>";
    for (auto& n : config.networks) {
        int rssi = signalFor(n.ssid);
        p += "<tr><td>" + html(n.ssid) + (n.instructor ? " <span class=muted>(set here)</span>" : "") +
             "</td><td class=muted>" + (rssi ? String(rssi) + " dBm" : "not in range") +
             "</td><td><form method=post action=/wifi/remove style=margin:0><input type=hidden name=ssid value='" +
             html(n.ssid) + "'><button style=margin:0>Remove</button></form></td></tr>";
    }
    if (config.networks.empty()) p += "<tr><td class=muted>No saved networks</td></tr>";
    p += "</table><h2>Add a network or change its password</h2><form method=post action=/wifi>";
    for (auto& s : seen) {
        bool saved = false;
        for (auto& n : config.networks) saved |= n.ssid == s.ssid;
        p += "<label><input type=radio name=ssid value='" + html(s.ssid) + "'> " + html(s.ssid) +
             " <span class=muted>" + String(s.rssi) + " dBm" + (saved ? ", saved" : "") + "</span></label>";
    }
    p += "<label>Other network name<input type=text name=other autocapitalize=none></label>"
         "<label>Password<input type=password name=psk autocomplete=off></label>"
         "<label><input type=checkbox name=force> Save even if the kit cannot connect now</label>"
         "<button>Test and save</button></form>"
         "<form method=post action=/scan><button>Scan again</button></form>";

    // Sensor: every Govee sensor heard recently, strongest first.
    p += "<h2>Sensor</h2><form method=post action=/sensor>";
    auto sensors = goveeHeard(15 * 60 * 1000);
    for (auto& g : sensors) {
        p += "<label><input type=radio name=sensor value='" + html(g.name) + "'" +
             (g.name == config.sensor ? " checked" : "") + "> " + html(g.name) + " <span class=muted>" +
             String(g.rssi) + " dBm, " + String(g.celsius * 9 / 5 + 32, 1) + "&#176;F, " + String(g.humidity, 0) +
             "%</span></label>";
    }
    if (sensors.empty()) p += "<p class=muted>No Govee sensors heard yet. Some take 90 seconds to appear.</p>";
    p += "<button>Pair this sensor</button></form><p class=muted>Place the sensor next to the kit so it "
         "tops the list. <a href='/'>Refresh</a></p>";

    // Instructor
    p += "<h2>Instructor</h2><form method=post action=/label><label>Name<input type=text name=instructor value='" +
         html(config.instructor) + "'></label><button>Save name</button></form>";

    p += "<h2>Finish</h2><form method=post action=/done><button>Restart and reconnect</button></form>"
         "<p class=muted>Changes are saved as they are made. The kit restarts on its own after 10 idle "
         "minutes.</p></body></html>";
    server.send(200, "text/html", p);
}

// Try the network while the portal stays up. Joining another network can move the kit's radio to
// that network's channel, which briefly drops the phone; the result waits on the page for its return.
static bool testNetwork(const String& ssid, const String& psk) {
    screenNote = "Testing...";
    drawScreen();
    WiFi.begin(ssid.c_str(), psk.c_str());
    uint32_t start = millis();
    wl_status_t status = WiFi.status();
    while (millis() - start < TEST_MS) {
        status = WiFi.status();
        if (status == WL_CONNECTED || status == WL_CONNECT_FAILED) break;
        delay(250);
    }
    WiFi.disconnect(false);
    return status == WL_CONNECTED;
}

static void handleWifi() {
    lastActivityMs = millis();
    String ssid = server.arg("other");
    ssid.trim();
    if (ssid.isEmpty()) ssid = server.arg("ssid");
    String psk = server.arg("psk");
    if (ssid.isEmpty() || ssid.length() > 32 || (psk.length() && (psk.length() < 8 || psk.length() > 63))) {
        notice = "Choose a network, and use a password of 8 to 63 characters.";
        return redirectHome();
    }
    bool ok = testNetwork(ssid, psk);
    bool save = ok || server.hasArg("force");
    if (save) {
        // An instructor's entry is the source of truth for this kit; the server's list never replaces it.
        bool found = false;
        for (auto& n : config.networks) {
            if (n.ssid == ssid) {
                n.psk = psk;
                n.instructor = true;
                found = true;
            }
        }
        if (!found) config.networks.push_back({ssid, psk, true});
        saveConfig();
    }
    notice = ok     ? "Connected to " + ssid + ". Saved."
             : save ? "Could not connect to " + ssid + " now; saved anyway."
                    : "Could not connect to " + ssid + ". Not saved; check the password, or tick \"Save even if\".";
    screenNote = ok ? "Wi-Fi saved" : save ? "Saved, untested" : "Wi-Fi failed";
    drawScreen();
    redirectHome();
}

static void handleRemove() {
    lastActivityMs = millis();
    String ssid = server.arg("ssid");
    auto& nets = config.networks;
    nets.erase(std::remove_if(nets.begin(), nets.end(), [&](const Network& n) { return n.ssid == ssid; }), nets.end());
    saveConfig();
    notice = "Removed " + ssid + ".";
    redirectHome();
}

static void handleSensor() {
    lastActivityMs = millis();
    String sensor = server.arg("sensor");
    if (sensor.isEmpty()) {
        notice = "Choose a sensor first.";
        return redirectHome();
    }
    config.sensor = sensor;
    saveConfig();
    notice = "Paired with " + sensor + ".";
    screenNote = "Sensor saved";
    drawScreen();
    redirectHome();
}

static void handleLabel() {
    lastActivityMs = millis();
    String instructor = server.arg("instructor");
    instructor.trim();
    if (instructor.isEmpty() || instructor.length() > MAX_LABEL) {
        notice = "Enter an instructor name of up to " + String(MAX_LABEL) + " characters.";
        return redirectHome();
    }
    config.instructor = instructor;
    saveConfig();
    notice = "Instructor saved: " + instructor + ".";
    redirectHome();
}

static void handleDone() {
    server.send(200, "text/html",
                "<!doctype html><meta name=viewport content='width=device-width'><p style='font-family:sans-serif'>"
                "Restarting. The kit reconnects with its saved networks in about a minute.</p>");
    delay(500);
    ESP.restart();
}

void portalStart() {
    active = true;
#ifdef PLUS2_BUZZER
    tone(BUZZER_PIN, 3000, 150);
#else
    M5.Speaker.tone(3000, 150);
#endif
    apName = "hallmon-" + String(config.kitId);
    apPassword = randomPassword();
    // Leaving the venue network stops uploads; the kit restarts when the portal closes.
    WiFi.disconnect(false);
    WiFi.mode(WIFI_AP_STA);
    WiFi.softAP(apName.c_str(), apPassword.c_str());
    // Answer every DNS name with the kit's address, so phones open the setup page on their own.
    dns.start(53, "*", WiFi.softAPIP());
    server.on("/", HTTP_GET, handleRoot);
    server.on("/wifi", HTTP_POST, handleWifi);
    server.on("/wifi/remove", HTTP_POST, handleRemove);
    server.on("/sensor", HTTP_POST, handleSensor);
    server.on("/label", HTTP_POST, handleLabel);
    server.on("/scan", HTTP_POST, [] {
        lastActivityMs = millis();
        scanNetworks();
        redirectHome();
    });
    server.on("/done", HTTP_POST, handleDone);
    // Phones probe for captive portals at their own URLs; sending them to the page makes it pop up.
    server.onNotFound(redirectHome);
    server.begin();
    drawScreen();
    scanNetworks();
    lastActivityMs = millis();
}

void portalTick() {
    dns.processNextRequest();
    server.handleClient();
    if (M5.BtnA.wasClicked() || millis() - lastActivityMs > IDLE_MS) ESP.restart();
}
