// The setup portal (F1 in docs/plan.md): a Wi-Fi network and web page for configuring the kit from
// a phone. Holding the main button for 3 seconds starts it.
#pragma once

bool portalActive();
void portalStart();
// Call from loop() while the portal is active. A short press or 10 idle minutes restarts the kit.
void portalTick();
