#include "reporter.h"

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <M5Unified.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <WiFiMulti.h>
#include <esp_sntp.h>
#include <sys/time.h>

#include <deque>

#include "certs.h"
#include "config.h"
#include "govee.h"

static const uint32_t INTERVAL_MS = 5 * 60 * 1000;
static const uint32_t RETRY_MS = 60 * 1000;
static const uint32_t WIFI_RETRY_MS = 10 * 1000;
static const uint32_t TIME_RETRY_MS = 30 * 1000;
// A week of readings at one every 5 minutes, held in RAM. A power pull loses what has not been sent.
static const size_t MAX_QUEUE = 7 * 288;
static const size_t BATCH = 250;
// Any earlier time means the clock was never set.
static const time_t VALID_AFTER = 1735689600;  // 2025-01-01T00:00:00Z

struct Reading {
    time_t ts;
    float celsius;
    float humidity;
    int battery;
    int rssi;
};

ReporterStatus reporter;

static WiFiMulti wifiMulti;
static std::deque<Reading> queue;
static bool sampled = false, uploadNow = false;
static uint32_t lastSampleMs = 0, lastAttemptMs = 0, lastWifiTryMs = 0, lastTimeTryMs = 0;
static bool wifiTried = false, timeTried = false, attempted = false;
static volatile bool ntpSynced = false;

static bool clockValid() { return time(nullptr) > VALID_AFTER; }

static bool due(bool done, uint32_t since, uint32_t period) { return !done || millis() - since >= period; }

// Copy the system clock to the RTC, which keeps time across a power pull while its battery lasts
// (H7 in docs/plan.md). The kit keeps all times in UTC.
static void saveRtc() {
    time_t now = time(nullptr);
    M5.Rtc.setDateTime(gmtime(&now));
}

// Venues can block NTP, so the server's HTTP Date header is the fallback clock source. This uses
// plain HTTP (the server answers with a redirect that still carries the Date header), since
// checking the server's TLS certificate needs a valid clock first.
static void timeFromServer() {
    String url = config.server;
    url.replace("https://", "http://");
    HTTPClient http;
    const char* keys[] = {"Date"};
    if (!http.begin(url + "/")) return;
    http.collectHeaders(keys, 1);
    http.GET();
    String date = http.header("Date");
    http.end();
    struct tm t = {};
    if (date.isEmpty() || !strptime(date.c_str(), "%a, %d %b %Y %H:%M:%S GMT", &t)) return;
    // The kit's TZ is never set, so mktime treats the time as UTC.
    timeval tv = {mktime(&t), 0};
    settimeofday(&tv, nullptr);
    if (clockValid()) saveRtc();
}

static void sample() {
    GoveeReading r;
    if (!goveeLatest(config.sensor, INTERVAL_MS, r)) return;
    time_t heardAt = time(nullptr) - (millis() - r.heardMs) / 1000;
    queue.push_back({heardAt, r.celsius, r.humidity, r.battery, r.rssi});
    if (queue.size() > MAX_QUEUE) queue.pop_front();
    sampled = true;
    lastSampleMs = millis();
    uploadNow = true;
}

static void upload() {
    size_t n = std::min(queue.size(), BATCH);
    JsonDocument doc;
    // The kit reports its label and sensor with every upload: once deployed, the kit's settings
    // are the source of truth for the server's record of it.
    JsonObject kit = doc["kit"].to<JsonObject>();
    if (!config.course.isEmpty()) kit["course"] = config.course;
    if (!config.instructor.isEmpty()) kit["instructor"] = config.instructor;
    if (!config.sensor.isEmpty()) kit["sensor"] = config.sensor;
    JsonArray readings = doc["readings"].to<JsonArray>();
    for (size_t i = 0; i < n; i++) {
        const Reading& r = queue[i];
        char ts[24];
        struct tm t;
        gmtime_r(&r.ts, &t);
        strftime(ts, sizeof ts, "%Y-%m-%dT%H:%M:%SZ", &t);
        JsonObject o = readings.add<JsonObject>();
        o["ts"] = ts;
        o["celsius"] = r.celsius;
        o["humidity"] = r.humidity;
        o["battery"] = r.battery;
        o["rssi"] = r.rssi;
    }
    String body;
    serializeJson(doc, body);

    WiFiClientSecure client;
    client.setCACert(ROOT_CERTS);
    HTTPClient http;
    http.setTimeout(15000);
    if (!http.begin(client, config.server + "/api/v1/readings")) {
        reporter.error = "bad server URL";
        return;
    }
    http.addHeader("Content-Type", "application/json");
    http.addHeader("Authorization", "Bearer " + config.token);
    int code = http.POST(body);
    http.end();

    if (code == 200) {
        queue.erase(queue.begin(), queue.begin() + n);
        reporter.lastUploadMs = millis();
        reporter.error = "";
        uploadNow = !queue.empty();
    } else if (code == 401) {
        reporter.error = "token rejected";
    } else if (code >= 400 && code < 500) {
        // The server refuses this batch and would refuse it again, so drop it rather than let it
        // block every reading behind it.
        queue.erase(queue.begin(), queue.begin() + n);
        reporter.error = "HTTP " + String(code) + ", batch dropped";
    } else {
        reporter.error = code < 0 ? HTTPClient::errorToString(code) : "HTTP " + String(code);
    }
}

void reporterBegin() {
    if (M5.Rtc.isEnabled()) M5.Rtc.setSystemTimeFromRtc();
    sntp_set_time_sync_notification_cb([](struct timeval*) { ntpSynced = true; });
    configTime(0, 0, "pool.ntp.org", "time.google.com");
    WiFi.mode(WIFI_STA);
    for (auto& n : config.networks) wifiMulti.addAP(n.ssid.c_str(), n.psk.c_str());
}

void reporterTick() {
    // WiFiMulti scans and joins the strongest known network; it blocks for a few seconds per try.
    if (WiFi.status() != WL_CONNECTED && !config.networks.empty() && due(wifiTried, lastWifiTryMs, WIFI_RETRY_MS)) {
        wifiMulti.run(5000);
        wifiTried = true;
        lastWifiTryMs = millis();
    }
    reporter.wifiConnected = WiFi.status() == WL_CONNECTED;
    reporter.ssid = reporter.wifiConnected ? WiFi.SSID() : "";
    reporter.wifiRssi = reporter.wifiConnected ? WiFi.RSSI() : 0;

    if (ntpSynced) {
        ntpSynced = false;
        saveRtc();
    }
    if (!clockValid() && reporter.wifiConnected && !config.server.isEmpty() &&
        due(timeTried, lastTimeTryMs, TIME_RETRY_MS)) {
        timeFromServer();
        timeTried = true;
        lastTimeTryMs = millis();
    }
    reporter.timeValid = clockValid();

    // Readings wait for a valid clock, since a reading without a trustworthy time is not useful.
    if (reporter.timeValid && due(sampled, lastSampleMs, INTERVAL_MS)) sample();

    if (reporter.wifiConnected && reporter.timeValid && !queue.empty() && !config.token.isEmpty() &&
        (uploadNow || due(attempted, lastAttemptMs, RETRY_MS))) {
        uploadNow = false;
        attempted = true;
        lastAttemptMs = millis();
        upload();
    }
    reporter.queued = queue.size();
}
