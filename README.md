# MentorPi

`mentorpi` is the robot-side runtime developed by **Frussen Robotics** for the Hiwonder MentorPi platform.

Its purpose is to expose controlled, high-level physical capabilities to embodied AI agents without giving them arbitrary direct access to ROS 2 topics, drivers, or motors.

The first agent using this runtime is **Ruben**, but the MentorPi runtime is designed to remain independent from any specific agent.

## Status

The target platform is a **Hiwonder MentorPi M1 Advanced** with Raspberry Pi 5.

The vendor-provided system has been verified with:

* ROS 2
* RGB/depth camera
* LiDAR
* mecanum drive
* RRC controller board
* local network control

Development is now moving from hardware verification to the first minimal body capability.

## Architecture

The intended boundary is:

```text
AI agent
   │
   │ high-level capability
   ▼
MentorPi runtime
   │
   ├── capability API
   ├── supervision
   ├── action execution
   └── ROS integration
           │
           ▼
        ROS 2
           │
           ▼
        hardware
```

The agent expresses intentions; the MentorPi runtime handles physical control.

An agent may eventually request actions such as:

```text
get_status()
observe_scene()
stop()
rotate_by(...)
navigate_to(...)
```

Realtime control loops remain local to the robot.

## Engineering principles

* Preserve the original Hiwonder system where practical.
* Do not give AI agents arbitrary direct access to ROS or motors.
* Expose narrow, controlled physical capabilities.
* Keep realtime control local to the robot.
* Keep stopping and safety mechanisms independent from cloud AI models.
* Allow only one active motion source at a time.
* Add structure only when a concrete need appears.
* Build and verify one small vertical slice at a time.

## First milestone

The first milestone is intentionally minimal:

```text
GET /status
```

The initial endpoint only needs to prove that the MentorPi runtime can run locally on the Raspberry Pi and expose a stable capability interface.

ROS state, battery information, networking, sensors, and motion capabilities will be added incrementally after this first vertical slice works.

## Run locally

With Python 3.11 or newer, from the repository root, create a local virtual environment and install the runtime dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

This keeps the runtime dependencies separate from the vendor Python environment.

Start the server on the local loopback interface:

```bash
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

In another terminal on the same machine, verify the endpoint:

```bash
curl http://127.0.0.1:8000/status
```

When rosbridge and battery data are available, expect HTTP `200 OK` with `Content-Type: application/json` and a body like this on the MentorPi:

```json
{
  "platform": "mentorpi",
  "runtime": "ok",
  "ros": {
    "status": "ok",
    "version": 2,
    "distro": "humble"
  },
  "battery": {
    "status": "ok",
    "millivolts": 7590,
    "volts": 7.59
  }
}
```

Each request runs two independent checks through short-lived connections to `ws://127.0.0.1:9090`: a call to `/rosapi/get_ros_version` and a read-only subscription to `/ros_robot_controller/battery` (`std_msgs/msg/UInt16`). The checks run concurrently within the request, each with a two-second deadline plus up to 0.2 seconds for connection cleanup. The version and distro come from the service response.

Battery status uses the first valid sample received during that request. `millivolts` preserves the ROS message's raw integer; `volts` is that value divided by 1000. For example, `7581` becomes `7.581` V. The connection closes after the check, removing its subscription; there is no cache or background monitoring. No battery percentage or remaining runtime is estimated.

If rosbridge is unreachable or neither check succeeds before its deadline, the endpoint still returns HTTP `200 OK`:

```json
{
  "platform": "mentorpi",
  "runtime": "ok",
  "ros": {
    "status": "unavailable"
  },
  "battery": {
    "status": "unavailable"
  }
}
```

If no valid battery sample is obtained before the deadline or its connection fails, only `battery` reports `{"status": "unavailable"}`; ROS version status is independent and may still be `"ok"`. Likewise, a failed or invalid ROS version response makes only `ros` unavailable.

`"runtime": "ok"` still means only that the MentorPi runtime process is alive and able to handle an HTTP request. ROS status verifies connectivity through rosbridge and the ROS version service; battery status reports only the measured voltage. Neither establishes complete robot readiness or the health of motors, camera, LiDAR, network, battery, or other hardware. No vendor changes or host ROS libraries are required.

FastAPI's default documentation remains available at `/docs` and `/redoc`, with the OpenAPI schema at `/openapi.json`. Stop the server with `Ctrl+C`.

## Agent workspaces and reusable components

This repository contains reusable robot software, including the body API,
battery monitor, and systemd service definitions.

Agent identity, personality, memories, and personal instructions belong in
the agent's separate OpenClaw workspace. A new robot can use a fresh workspace;
it does not need a copy of Ruben's workspace.

The battery monitor uses the external `speak` skill installed in that workspace.
Its location is configured through `MENTORPI_SPEAK_SCRIPT`; the monitor does not
require a workspace named `ruben-workspace` or a running OpenClaw agent.

## Automatic startup and battery announcements

### New robot setup

1. Clone this repository and install the runtime dependencies as described above.
2. Create the new agent's OpenClaw workspace and install the `speak` skill.
   Configure its OpenAI API key and ALSA audio device, then verify speech manually.
3. Install the runtime and battery monitor as user systemd services.
4. Configure this robot's paths and credentials locally, outside Git.

The commands below are for a new installation. On an existing robot, inspect
and merge existing configuration and service files instead of overwriting them.

### Runtime service

Copy `systemd/mentorpi-runtime.service` to `~/.config/systemd/user/`.

Before enabling it, adjust `WorkingDirectory` and `ExecStart` in the installed
copy to match the actual repository and virtual environment paths. The supplied
runtime unit currently uses `/home/pi/frussen-robotics/mentorpi`.

### Battery monitor configuration

Create a private configuration file from the example:

```bash
mkdir -p ~/.config/mentorpi
chmod 700 ~/.config/mentorpi
install -m 600 systemd/battery-monitor.env.example \
  ~/.config/mentorpi/battery-monitor.env
```

Edit this local file and set:

- `MENTORPI_BATTERY_SCRIPT`: absolute path to this repository's `battery_monitor.py`.
- `MENTORPI_SPEAK_SCRIPT`: absolute path to the installed skill's `scripts/run.py`.
- `OPENAI_API_KEY`: the speech API key.
- `SPEAK_ALSA_DEVICE`: the audio device verified on this robot.

Voice, polling interval, and voltage thresholds are also configurable in that
file. An optional `MENTORPI_BATTERY_MESSAGE` overrides the spoken message.

Never commit the real configuration file or API key. A shell `export` alone
does not configure the systemd service.

### Enable the services

After installing and configuring the runtime unit:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/mentorpi-battery-monitor.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now mentorpi-runtime.service
systemctl --user enable --now mentorpi-battery-monitor.service
loginctl show-user "$USER" -p Linger
```

For startup without an interactive login, `Linger` must be `yes`.
If necessary, enable it with:

```bash
sudo loginctl enable-linger "$USER"
```

The battery monitor requests startup of `mentorpi-runtime.service`.
If the API or ROS is temporarily unavailable, it waits and polls again without
speaking or changing the saved announcement state.

### Announcement behavior

With the default configuration:

- Poll `/status` every 10 seconds.
- Attempt one spoken announcement when voltage is strictly below 7.2 V.
- Rearm when voltage is strictly above 7.4 V.
- Preserve the announcement state across service restarts and robot reboots.
- Leave the native Hiwonder low-voltage beep unchanged.

State is stored under `$XDG_STATE_HOME/mentorpi-battery-monitor`, or
`~/.local/state/mentorpi-battery-monitor` when that variable is unset.
Do not copy this state to a new robot.

The monitor records the attempt before invoking speech to prevent duplicate
announcements after a restart. If speech fails, the error is logged and no
automatic speech retry occurs until the monitor has rearmed.
Speech has a 45-second timeout and requires network access and valid API credentials.

The monitor is an advisory notification, not a battery protection or shutdown
mechanism.

### Inspect and manage

```bash
systemctl --user status mentorpi-battery-monitor.service --no-pager
journalctl --user -u mentorpi-battery-monitor.service -n 50 --no-pager
systemctl --user restart mentorpi-battery-monitor.service
systemctl --user stop mentorpi-battery-monitor.service
```

After editing the local environment file, restart the battery monitor.
After updating an installed service definition, also run
`systemctl --user daemon-reload`.

The threshold logic and state persistence have been tested in simulation.
End-to-end speech from the service should also be verified on each robot.
