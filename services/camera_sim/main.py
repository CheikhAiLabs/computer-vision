import asyncio
from contextlib import asynccontextmanager
import logging
import os
import subprocess
import threading
import time
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Gauge, start_http_server
import uvicorn
from common.config import RTSP_URL
from common.runtime import setup
from services.camera_sim.scene import render, WIDTH, HEIGHT, FPS, SCENARIOS
from common.line import CAMERAS

LOG = logging.getLogger(__name__)
scenario = "normal"
scenario_started = time.time()
stop = threading.Event()
UP = Gauge("camera_publisher_up", "FFmpeg accepts camera frames")
FRAMES = Counter("camera_frames", "Frames written to FFmpeg")
RESTARTS = Counter("camera_publisher_restarts", "FFmpeg publisher start attempts")
CAMERA_UP = Gauge('camera_view_publisher_up', 'Publisher accepting frames by view', ['camera'])


def command(camera='process'):
    return ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-f", "rawvideo",
            "-pix_fmt", "bgr24", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS),
            "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "ultrafast",
            "-tune", "zerolatency", "-pix_fmt", "yuv420p", "-g", str(FPS),
            "-threads", "1", "-f", "rtsp", "-rtsp_transport", "tcp",
            RTSP_URL.rsplit('/',1)[0] + '/line1-' + camera]


async def publish_video(camera):
    frame_number = 0
    while not stop.is_set():
        proc = None
        try:
            RESTARTS.inc()
            proc = await asyncio.create_subprocess_exec(*command(camera), stdin=subprocess.PIPE)
            LOG.info("Camera publisher started view=%s", camera)
            while not stop.is_set() and proc.returncode is None:
                start = time.monotonic()
                proc.stdin.write(render(frame_number, scenario, camera, time.time(), scenario_started).tobytes())
                await asyncio.wait_for(proc.stdin.drain(), timeout=5)
                CAMERA_UP.labels(camera).set(1)
                if camera == 'process':
                    UP.set(1)
                FRAMES.inc()
                frame_number += 1
                await asyncio.sleep(max(0, 1 / FPS - (time.monotonic() - start)))
        except (BrokenPipeError, ConnectionResetError, asyncio.TimeoutError, OSError):
            LOG.exception("Camera publish failed; reconnecting")
        finally:
            CAMERA_UP.labels(camera).set(0)
            if camera == 'process':
                UP.set(0)
            if proc is not None and proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), 3)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
        await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app):
    start_http_server(int(os.getenv("METRICS_PORT", "9105")))
    tasks = [asyncio.create_task(publish_video(camera)) for camera in CAMERAS]
    try:
        yield
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="computer-vision camera", lifespan=lifespan)


@app.get("/healthz")
def health():
    return {"status": "ok", "note": "Control plane alive; see camera_publisher_up for video"}


@app.get("/state")
def state():
    return {"scenario": scenario, "started_at": scenario_started, "cameras": list(CAMERAS)}


@app.post("/scenario/{name}")
def change(name: str):
    global scenario, scenario_started
    if name not in SCENARIOS:
        raise HTTPException(400, "Unknown scenario")
    scenario = name
    scenario_started = time.time()
    LOG.info("Camera scenario=%s", name)
    return state()


if __name__ == "__main__":
    setup()
    uvicorn.run(app, host="0.0.0.0", port=8082)
