#!/usr/bin/env python3
"""Battery announcement monitor; speech is provided by an external skill."""

import fcntl
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import ProxyHandler, build_opener


def transition(warned, millivolts, low=7200, reset=7400):
    if type(millivolts) is not int or not 0 < millivolts <= 65535:
        return warned, False
    if millivolts > reset:
        return False, False
    if millivolts < low and not warned:
        return True, True
    return warned, False


def load_state(path):
    if not path.exists():
        return False
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or type(data.get("warned")) is not bool:
        raise ValueError("Invalid battery monitor state")
    return data["warned"]


def save_state(path, warned):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as handle:
        json.dump({"warned": warned}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def read_battery(http, url):
    with http.open(url, timeout=4) as response:
        data = json.load(response)
    if data.get("runtime") != "ok":
        raise ValueError("Runtime unavailable")
    if data.get("ros", {}).get("status") != "ok":
        raise ValueError("ROS unavailable")
    battery = data.get("battery", {})
    if battery.get("status") != "ok":
        raise ValueError("Battery unavailable")
    value = battery.get("millivolts")
    if type(value) is not int or not 0 < value <= 65535:
        raise ValueError("Invalid battery sample")
    return value


def announce(speak, message):
    process = subprocess.Popen(
        [sys.executable, str(speak), message],
        start_new_session=True,
    )
    try:
        code = process.wait(timeout=45)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        raise RuntimeError("Speech timed out") from None
    if code:
        raise RuntimeError(f"Speech exited with code {code}")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    speak_setting = os.environ.get("MENTORPI_SPEAK_SCRIPT")
    if not speak_setting:
        raise SystemExit("Set MENTORPI_SPEAK_SCRIPT to the speak run.py path")
    speak = Path(speak_setting).expanduser()
    if not speak.is_file():
        raise SystemExit(f"Speak script not found: {speak}")

    low = int(os.environ.get("MENTORPI_BATTERY_LOW_MV", "7200"))
    reset = int(os.environ.get("MENTORPI_BATTERY_RESET_MV", "7400"))
    interval = int(os.environ.get("MENTORPI_BATTERY_INTERVAL_SECONDS", "10"))
    if not 0 < low < reset <= 65535 or interval < 1:
        raise SystemExit("Invalid thresholds or polling interval")

    url = os.environ.get(
        "MENTORPI_STATUS_URL", "http://127.0.0.1:8000/status"
    )
    message = os.environ.get(
        "MENTORPI_BATTERY_MESSAGE",
        "La mia batteria è quasi scarica. Mi metti in carica, per favore?",
    )
    state_dir = Path(
        os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))
    ) / "mentorpi-battery-monitor"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "state.json"
    http = build_opener(ProxyHandler({}))

    with (state_dir / "monitor.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Battery monitor already running")

        # Invalid stored state stops startup instead of repeating an alert.
        warned = load_state(state_file)
        unavailable = False
        logging.info("Started; announcement already attempted: %s", warned)

        while True:
            try:
                millivolts = read_battery(http, url)
            except Exception as error:
                if not unavailable:
                    logging.warning("Battery reading unavailable: %s", error)
                unavailable = True
                time.sleep(interval)
                continue

            if unavailable:
                logging.info("Battery reading restored")
                unavailable = False

            updated, should_speak = transition(warned, millivolts, low, reset)
            if updated != warned:
                # Persist before speaking to prevent duplicates after restart.
                save_state(state_file, updated)
                warned = updated
                if not warned:
                    logging.info("Rearmed at %.2f V", millivolts / 1000)

            if should_speak:
                logging.info("Low battery: %.2f V", millivolts / 1000)
                try:
                    announce(speak, message)
                except Exception:
                    logging.exception("Speech failed; no automatic retry")

            time.sleep(interval)


if __name__ == "__main__":
    main()
