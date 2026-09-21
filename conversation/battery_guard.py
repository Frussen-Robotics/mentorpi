"""Suspend the battery announcer and restore its previous active state."""
import json
import os
import subprocess
import sys
from pathlib import Path

UNIT = "mentorpi-battery-monitor.service"
STATE = Path(os.environ["RUNTIME_DIRECTORY"]) / "battery-state.json"


def systemctl(*args):
    return subprocess.run(
        ["systemctl", "--user", *args],
        check=True,
        text=True,
        capture_output=True,
        timeout=10,
    )


def main():
    action = sys.argv[1]
    if action == "pause":
        if STATE.exists():
            raise RuntimeError("Previous battery state already exists")
        result = systemctl("show", UNIT, "-p", "ActiveState", "--value")
        was_active = result.stdout.strip() in ("active", "activating", "reloading")

        temporary = STATE.with_suffix(".tmp")
        temporary.write_text(json.dumps({"was_active": was_active}))
        temporary.replace(STATE)

        systemctl("stop", UNIT)
        print(f"Battery announcer paused; restore afterwards: {was_active}")

    elif action == "restore":
        if not STATE.exists():
            return
        state = json.loads(STATE.read_text())
        if type(state.get("was_active")) is not bool:
            raise ValueError("Invalid saved battery state")
        if state["was_active"]:
            systemctl("start", "--no-block", UNIT)
            print("Battery announcer restart requested")
        STATE.unlink()

    else:
        raise ValueError("Expected pause or restore")


if __name__ == "__main__":
    main()
