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

From the repository root, create a local virtual environment and install the runtime dependencies:

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

Expected response: HTTP `200 OK` with `Content-Type: application/json` and this body:

```json
{
  "platform": "mentorpi",
  "runtime": "ok"
}
```

This response means only that the MentorPi runtime process is alive and able to handle an HTTP request. It does not inspect or imply that ROS, motors, camera, LiDAR, network, battery, or any other robot hardware or service is operational.

FastAPI's default documentation remains available at `/docs` and `/redoc`, with the OpenAPI schema at `/openapi.json`. Stop the server with `Ctrl+C`.
