from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import asyncio
import random


class SensorManager:
    def __init__(self) -> None:
        self.read_count = 0
        self.websockets: set[WebSocket] = set()

    def sensor_metadata(self):
        sensors = []
        for index in range(3):
            sensors.append(
                {
                    "name": f"Sensor {index}",
                }
            )

        return {"type": "setup", "sensors": sensors}

    async def connect_websocket(self, websocket: WebSocket):
        await websocket.accept()
        await websocket.send_json(self.sensor_metadata())
        self.websockets.add(websocket)

    async def read_and_broadcast(self):
        data = []
        if True:  # TODO: get real data
            for index in range(3):
                data.append([self.read_count, random.random()])
                await asyncio.sleep(1)
        else:
            raise NotImplementedError("Real data readings not implemented yet")

        msg = {"type": "data", "data": data}
        for websocket in self.websockets:
            await websocket.send_json(msg)

        self.read_count += 1

    async def read_and_broadcast_loop(self):
        try:
            while True:
                await self.read_and_broadcast()

        except asyncio.CancelledError:
            self.close_all()

    async def close_all(self):
        for websocket in self.websockets:
            await websocket.close()

        self.websockets.clear()


manager = SensorManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    broadcast_task = asyncio.create_task(manager.read_and_broadcast_loop())
    yield
    broadcast_task.cancel()


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def show_live_sensors(request: Request):
    return templates.TemplateResponse("live.html", {"request": request})


@app.websocket("/live/ws")
async def live_websocket(websocket: WebSocket):
    await manager.connect_websocket(websocket)
    while True:
        await websocket.receive_json()
