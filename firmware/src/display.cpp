#include "display.h"

#include <M5Unified.h>

#include "config.h"
#include "govee.h"
#include "power.h"
#include "reporter.h"

// A reading older than this is shown as stale, matching the staff page's 12-minute threshold.
static const uint32_t STALE_MS = 12 * 60 * 1000;

static M5Canvas canvas(&M5.Display);
static uint32_t lastDrawMs = 0;

static String ago(uint32_t ms) {
    uint32_t s = ms / 1000;
    if (s < 60) return String(s) + "s";
    if (s < 3600) return String(s / 60) + "m";
    return String(s / 3600) + "h";
}

void displayBegin() {
    M5.Display.setRotation(1);  // landscape, 240 x 135
    M5.Display.setBrightness(80);
    canvas.createSprite(M5.Display.width(), M5.Display.height());
}

// The status screen answers "is it working?" without a laptop (see "What the screen shows" in
// docs/plan.md): the reading, the label, the sensor, Wi-Fi, the last upload, and the kit ID.
void displayTick() {
    if (lastDrawMs && millis() - lastDrawMs < 1000) return;
    lastDrawMs = millis();

    canvas.fillScreen(TFT_BLACK);
    canvas.setTextColor(TFT_WHITE);
    canvas.setTextDatum(top_left);

    GoveeReading r;
    bool heard = goveeLatest(config.sensor, STALE_MS, r);
    canvas.setFont(&fonts::FreeSansBold18pt7b);
    if (heard) {
        String temp = String(r.celsius * 9 / 5 + 32, 1);
        canvas.drawString(temp, 4, 2);
        int x = 4 + canvas.textWidth(temp);
        canvas.drawCircle(x + 5, 8, 3, TFT_WHITE);  // the GFX fonts have no degree sign
        canvas.drawString("F", x + 11, 2);
        canvas.setFont(&fonts::FreeSans12pt7b);
        canvas.setTextDatum(top_right);
        canvas.drawString(String(r.humidity, 0) + "%", canvas.width() - 4, 8);
        canvas.setTextDatum(top_left);
    } else {
        canvas.setTextColor(TFT_ORANGE);
        canvas.drawString("--.-", 4, 2);
        canvas.setTextColor(TFT_WHITE);
    }

    canvas.setFont(&fonts::Font2);  // 16 px lines below the reading
    int y = 40;
    auto line = [&](const String& text, uint16_t color = TFT_WHITE) {
        canvas.setTextColor(color);
        canvas.drawString(text, 4, y);
        y += 16;
    };

    line(config.instructor.isEmpty() ? "No instructor set" : config.instructor, TFT_LIGHTGREY);

    if (config.sensor.isEmpty()) {
        line("No sensor paired", TFT_ORANGE);
    } else if (heard) {
        line(r.name + " " + String(r.rssi) + " dBm, " + ago(millis() - r.heardMs) + " ago");
    } else {
        line(config.sensor + " not heard", TFT_ORANGE);
    }

    if (config.networks.empty()) {
        line("No Wi-Fi networks set", TFT_ORANGE);
    } else if (reporter.wifiConnected) {
        line("Wi-Fi " + reporter.ssid + " " + String(reporter.wifiRssi) + " dBm");
    } else {
        line("Wi-Fi: searching", TFT_ORANGE);
    }

    if (!reporter.timeValid) {
        line("Waiting for the clock", TFT_ORANGE);
    } else if (!reporter.error.isEmpty()) {
        line("Upload: " + reporter.error + ", " + String(reporter.queued) + " queued", TFT_ORANGE);
    } else if (reporter.lastUploadMs) {
        line("Sent " + ago(millis() - reporter.lastUploadMs) + " ago, " + String(reporter.queued) + " queued");
    } else {
        line("Not sent yet, " + String(reporter.queued) + " queued");
    }

    // The kit's own power, right-aligned on the kit ID line. Plugged in, the level reads the charging
    // voltage, so it runs high; it is shown only as a rough guide to how far charging has come.
    int level = powerBatteryLevel();
    bool usb = powerOnUsb();
    String percent = level >= 0 ? " " + String(level) + "%" : "";
    canvas.setTextDatum(top_right);
    canvas.setTextColor(!usb && level >= 0 && level <= 20 ? TFT_ORANGE : TFT_DARKGREY);
    canvas.drawString(usb ? "USB" + percent : level >= 0 ? "Battery" + percent : "", canvas.width() - 4, y);
    canvas.setTextDatum(top_left);
    line("Kit " + String(config.kitId), TFT_DARKGREY);
    canvas.pushSprite(0, 0);
}
