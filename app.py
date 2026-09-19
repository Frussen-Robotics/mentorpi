import asyncio

from fastapi import FastAPI

from rosbridge import get_battery_status, get_ros_status

app = FastAPI()


@app.get("/status")
async def status():
    ros, battery = await asyncio.gather(get_ros_status(), get_battery_status())
    return {"platform": "mentorpi", "runtime": "ok", "ros": ros, "battery": battery}
