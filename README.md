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

Implemented capabilities include the local status API, persistent battery announcements, and an on-demand GPT Live conversation service.

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

ROS connectivity and battery voltage are now exposed through this endpoint. Additional sensing and motion capabilities will be added incrementally.

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

## GPT Live conversation

The conversation service connects the robot's microphone and speaker to
`gpt-live-1`. It uses its own Python environment and does not invoke the
external `speak` skill.

It starts on demand, not at boot. Microphone audio is sent to OpenAI while
the session is active. Input and output transcripts are printed to the
systemd journal; do not share logs containing private conversations.
The API session is configured with `store: false`.

### Install on a new robot

From the repository root, with Python 3.11 or newer and ALSA's
`arecord` and `aplay` available:

```bash
python3 -m venv ~/.cache/mentorpi/conversation/venv
~/.cache/mentorpi/conversation/venv/bin/python \
  -m pip install -r conversation/requirements.txt
```

The following copies are for a fresh installation only. On an existing
installation, preserve and merge local configuration.

```bash
mkdir -p ~/.config/mentorpi ~/.config/systemd/user
install -m 600 conversation/conversation.env.example \
  ~/.config/mentorpi/conversation.env
cp systemd/mentorpi-conversation.service ~/.config/systemd/user/
```

Edit `~/.config/mentorpi/conversation.env` before starting the service:

- Set `CONVERSATION_PYTHON` to the dedicated environment's Python executable.
- Set `CONVERSATION_SCRIPT` to the absolute path of `conversation/run.py`.
- Set `CONVERSATION_GUARD_SCRIPT` to the absolute path of
  `conversation/battery_guard.py`.
- Set `CONVERSATION_MIC` and `SPEAK_ALSA_DEVICE` for this robot's audio hardware.
- Set `OPENAI_API_KEY` locally; never commit it.
- Set `SPEAK_LIVE_VOICE` to the desired voice.
- Optionally set `CONVERSATION_INSTRUCTIONS_FILE` to a local UTF-8 prompt file.

`CONVERSATION_MAX_SECONDS=0` removes the application's duration limit.
A positive value limits the conversation duration in seconds. API limits,
network failures, or audio errors can still end the session; automatic
reconnection is not implemented.

The supplied service expects the battery monitor service described above
to be installed. After installing the unit:

```bash
systemctl --user daemon-reload
```

### Start, inspect, and stop

```bash
systemctl --user start mentorpi-conversation.service
systemctl --user status mentorpi-conversation.service --no-pager
journalctl --user -u mentorpi-conversation.service -n 30 -f
```

Wait for the session-active message before speaking. Ctrl+C exits the log
viewer only; it does not stop the conversation.

To stop microphone capture and close the session:

```bash
systemctl --user stop mentorpi-conversation.service
systemctl --user is-active mentorpi-battery-monitor.service
```

The service requests an orderly shutdown of recording, playback, and the
API session. It does not automatically restart after an error.
After changing the environment or instructions file, restart the service.

### Battery announcements during conversation

Before starting, `battery_guard.py` records whether the battery monitor is
active and stops it. The service's stop hook requests a monitor restart
only if it was previously active, including after application failures.

This is temporary coordination: no spoken battery warning is issued during
conversation. The native Hiwonder beep remains unchanged. Do not manually
start the battery monitor or invoke `speak` during a conversation, because
independent audio playback is not yet coordinated.

### Current scope and validation

On Ruben, manual conversation, user interruptions, service startup and
shutdown, and battery monitor restoration have been verified on hardware.

`conversation/manual.py` remains the original two-minute diagnostic script.
It does not manage the battery monitor; prefer the systemd service for
normal use.

The conversation currently uses generic instructions. It does not
automatically load an OpenClaw workspace, identity, or memories, and has
no backend tools or robot motion control. Wake-word activation, shared
announcement handling, and acoustic echo cancellation are not implemented.
