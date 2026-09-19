from fastapi import FastAPI

from rosbridge import get_ros_status

app = FastAPI()


@app.get("/status")
async def status():
    return {"platform": "mentorpi", "runtime": "ok", "ros": await get_ros_status()}
