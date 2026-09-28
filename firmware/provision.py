#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyserial>=3.5"]
# ///
"""Provision a hallmonitor kit over USB: flash the firmware, create the kit on the server, and load its settings.

    uv run provision.py --course SEC504 --instructor "Josh Wright"      # a new kit
    uv run provision.py --course SEC504 --instructor "Josh Wright" --sensor Govee_H5074_67B3
    uv run provision.py --update                                        # resend networks.json to a kit
    uv run provision.py --update --instructor "Another Instructor"      # and change its label

A new kit is flashed, created on the server with `add-kit` over SSH, and sent its token, label,
and the Wi-Fi networks in networks.json. Without --sensor, the script lists the Govee sensors the
kit hears, strongest first, and asks which one to pair. --update skips the flash and the server,
and sends only the networks and any label or sensor given.
"""

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import serial
from serial.tools import list_ports

HERE = Path(__file__).resolve().parent
NETWORKS_PATH = HERE / "networks.json"
SERVER_URL = "https://hallmonitor.willhackforsushi.com"
# The server's admin command, run on hasborg over SSH (see server/README.md).
ADMIN = ["ssh", "hasborg", "cd hallmonitor && ~/.local/bin/uv run -q --offline --script hallmonitor.py"]
# USB-to-serial chips found on ESP32 boards: WCH (the Plus2's CH9102), Silicon Labs, FTDI, and
# Espressif's built-in USB.
USB_VENDORS = {0x1A86, 0x10C4, 0x0403, 0x303A}
REPLY_TIMEOUT = 10.0


def find_port() -> str:
    ports = [p.device for p in list_ports.comports() if p.vid in USB_VENDORS]
    if len(ports) == 1:
        return ports[0]
    if not ports:
        sys.exit("No kit found on USB. Plug it in (and turn it on), or pass --port.")
    sys.exit(f"More than one serial device found ({', '.join(ports)}); pass --port.")


def flash(port: str) -> None:
    pio = shutil.which("pio")
    if pio is None:
        sys.exit("pio not found; install PlatformIO with: uv tool install platformio")
    print(f"Flashing the firmware to {port}...")
    result = subprocess.run([pio, "run", "-t", "upload", "--upload-port", port], cwd=HERE)
    if result.returncode != 0:
        sys.exit("Flashing failed; nothing was created on the server.")


class KitTimeout(Exception):
    """The kit did not answer a command in time."""


class Kit:
    """The kit's serial command interface: one command per line, one line of JSON back."""

    def __init__(self, port: str) -> None:
        # pyserial opens the port with DTR and RTS both asserted, which resets neither an ESP32's
        # auto-reset circuit nor the ESP32-S3's built-in USB. Dropping either line can reset the kit,
        # and on the S3, dropping them both leaves it waiting in download mode.
        self.serial = serial.Serial(port, 115200, timeout=0.5)

    def command(self, line: str, timeout: float = REPLY_TIMEOUT):
        """Send one command and return its JSON reply, skipping boot messages and other output."""
        self.serial.reset_input_buffer()
        self.serial.write(line.encode() + b"\n")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            text = self.serial.readline().decode(errors="replace").strip()
            if not text.startswith(("{", "[")):
                continue
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                continue
        raise KitTimeout(f"The kit did not answer {line.split()[0]!r} within {timeout:.0f}s.")

    def configure(self, settings: dict) -> None:
        reply = self.command("config " + json.dumps(settings, separators=(",", ":")))
        if not reply.get("ok"):
            sys.exit(f"The kit rejected its settings: {reply.get('error')}")

    def wait_ready(self, timeout: float = 30.0) -> dict:
        """Wait for the kit to answer `show`, for example after a flash or a reboot."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                return self.command("show", timeout=3)
            except KitTimeout:
                continue
        raise KitTimeout(f"The kit did not respond on {self.serial.port} within {timeout:.0f}s.")


def load_networks() -> list[dict]:
    try:
        networks = json.loads(NETWORKS_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"Could not read {NETWORKS_PATH}: {exc}")
    return [{"ssid": n["ssid"], "psk": n["psk"]} for n in networks]


def create_kit(course: str, instructor: str, sensor: str | None) -> tuple[int, str]:
    """Run add-kit on the server and return the new kit's ID and token."""
    args = ["add-kit", "--course", course, "--instructor", instructor]
    if sensor:
        args += ["--sensor", sensor]
    remote = ADMIN[-1] + " " + shlex.join(args)
    result = subprocess.run([*ADMIN[:-1], remote], capture_output=True, text=True)
    kit = re.search(r"^kit (\d+):", result.stdout, re.M)
    token = re.search(r"^token .*: (\S+)$", result.stdout, re.M)
    if result.returncode != 0 or not kit or not token:
        sys.exit(f"add-kit failed on the server:\n{result.stdout}{result.stderr}")
    return int(kit.group(1)), token.group(1)


def pick_sensor(kit: Kit) -> str:
    """List the Govee sensors the kit hears and ask which one to pair."""
    print("\nListening for Govee sensors. Place the kit's sensor next to it; an H5074 can take up to")
    print("90 seconds to show up.")
    while True:
        sensors = kit.command("sensors")
        print()
        if not sensors:
            print("  (none heard yet)")
        for i, s in enumerate(sensors, 1):
            fahrenheit = s["celsius"] * 9 / 5 + 32
            print(f"  {i}. {s['name']:<20} {s['rssi']:>4} dBm  {fahrenheit:5.1f}F  {s['humidity']:4.0f}%  "
                  f"heard {s['age_s']}s ago")
        choice = input("Number to pair, or Enter to refresh: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(sensors):
            return sensors[int(choice) - 1]["name"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--course", help="course number, for example SEC504")
    parser.add_argument("--instructor", help="instructor name")
    parser.add_argument("--sensor", help="Govee sensor name; without it, pick from the sensors the kit hears")
    parser.add_argument("--port", help="serial port (default: find the kit on USB)")
    parser.add_argument("--update", action="store_true",
                        help="resend networks and any given label to an already provisioned kit")
    parser.add_argument("--no-flash", action="store_true", help="skip flashing, for a kit already running the firmware")
    args = parser.parse_args()
    if not args.update and not (args.course and args.instructor):
        parser.error("a new kit needs --course and --instructor")

    networks = load_networks()
    port = args.port or find_port()
    if not args.update and not args.no_flash:
        flash(port)

    kit = Kit(port)
    state = kit.wait_ready()
    settings = {"networks": networks}
    for key in ("course", "instructor", "sensor"):
        if getattr(args, key):
            settings[key] = getattr(args, key)

    if args.update:
        if not state.get("token_set"):
            sys.exit("This kit has no token yet; provision it without --update first.")
        kit.configure(settings)
    else:
        if state.get("token_set"):
            print(f"Note: this kit was kit {state.get('kit_id')}. It becomes a new kit; revoke the old one on the "
                  "server if nothing else uses it.")
        kit_id, token = create_kit(args.course, args.instructor, args.sensor)
        print(f"Created kit {kit_id} on the server.")
        settings.update(kit_id=kit_id, server=SERVER_URL, token=token)
        kit.configure(settings)
        if not args.sensor:
            kit.configure({"sensor": pick_sensor(kit)})

    # The kit loads its Wi-Fi networks at boot.
    kit.command("reboot")
    time.sleep(2)
    state = kit.wait_ready()
    networks_loaded = len(state.get("networks", []))
    print(f"\nKit {state.get('kit_id')}: {state.get('course')} / {state.get('instructor')}, "
          f"sensor {state.get('sensor') or '(none)'}, {networks_loaded} Wi-Fi networks")
    if not state.get("complete"):
        print("The kit is missing settings; run `show` in `pio device monitor` to see which.")
        return 1
    print(f"Label the kit and its sensor with kit ID {state.get('kit_id')}.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KitTimeout as exc:
        sys.exit(str(exc))
    except KeyboardInterrupt:
        sys.exit(130)
