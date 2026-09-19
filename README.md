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
