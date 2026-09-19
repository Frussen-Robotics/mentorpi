import asyncio
import json
from uuid import uuid4

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException


async def get_ros_status():
    """Check ROS connectivity via one short-lived rosbridge service call."""
    request_id = uuid4().hex
    service = "/rosapi/get_ros_version"
    try:
        # One deadline covers connection, send, and all received messages.
        async with asyncio.timeout(2):
            async with connect(
                "ws://127.0.0.1:9090",
                proxy=None,
                open_timeout=2,
                close_timeout=0.2,
            ) as websocket:
                await websocket.send(json.dumps({
                    "op": "call_service",
                    "id": request_id,
                    "service": service,
                    "args": {},
                }))
                while True:
                    response = json.loads(await websocket.recv())
                    if not isinstance(response, dict):
                        break
                    if (
                        response.get("op") != "service_response"
                        or response.get("id") != request_id
                        or response.get("service") != service
                    ):
                        continue
                    values = response.get("values")
                    if response.get("result") is not True or not isinstance(values, dict):
                        break
                    version = values.get("version")
                    distro = values.get("distro")
                    if type(version) is not int or not isinstance(distro, str) or not distro:
                        break
                    return {"status": "ok", "version": version, "distro": distro}
    except (OSError, TimeoutError, WebSocketException, ValueError):
        pass
    return {"status": "unavailable"}
