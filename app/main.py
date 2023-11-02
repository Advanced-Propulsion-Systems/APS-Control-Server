from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import random
import os
from io import TextIOWrapper
from .models import Recording
from sqlmodel import Session
from .routers import recordings
from .database import engine


class ControlServer:
    def __init__(self) -> None:
        self.read_count = 0
        self.websockets: set[WebSocket] = set()

        self.recording_file: TextIOWrapper | None = None
        self.recording_count = 0

    def sensor_metadata(self):
        sensors = []
        for index in range(3):
            sensors.append(
                {
                    "id": f"Sensor {index}",
                }
            )

        return {"type": "setup", "sensors": sensors}

    async def connect_websocket(self, websocket: WebSocket):
        await websocket.accept()
        await websocket.send_json(self.sensor_metadata())
        self.websockets.add(websocket)

    async def broadcast_msgs(self):
        while True:
            data = {}
            if True:  # TODO: get real data
                for index in range(3):
                    data[f"Sensor {index}"] = [self.read_count, random.random()]

                await asyncio.sleep(1)
            else:
                raise NotImplementedError("Real data readings not implemented yet")

            if self.recording_file is not None:
                self.recording_file.write(str(self.recording_count))
                for key, value in data.items():
                    self.recording_file.write("," + str(value[1]))
                self.recording_file.write("\n")
                self.recording_count += 1

            msg = {"type": "data", "data": data}
            for websocket in self.websockets:
                await websocket.send_json(msg)

            self.read_count += 1

    async def broadcast_msg(self, msg: dict):
        async with asyncio.TaskGroup() as tg:
            for websocket in self.websockets:
                tg.create_task(websocket.send_json(msg))

    async def update_status(self, **kwargs):
        await self.broadcast_msg({"type": "update-status", "changes": kwargs})

    async def receive_msg(self, socket: WebSocket):
        try:
            while True:
                msg = await socket.receive_json()
                if msg["cmd"] == "start-recording":
                    if self.recording_file is not None:
                        continue

                    with Session(engine) as session:
                        recording = Recording(name=msg["name"].strip())
                        session.add(recording)
                        session.commit()

                        self.recording_file = open(
                            os.path.join("recordings", recording.id.hex + ".csv"),
                            "w",
                            buffering=1,
                        )
                        self.recording_count = 0
                    await self.update_status(recordingStatus=True)

                elif msg["cmd"] == "stop-recording":
                    if self.recording_file is None:
                        continue

                    self.recording_file.close()
                    self.recording_file = None
                    await self.update_status(recordingStatus=False)

                elif msg["cmd"] == "ignite":
                    raise NotImplementedError

        except WebSocketDisconnect:
            self.websockets.remove(socket)

    async def close_all(self):
        for websocket in self.websockets:
            await websocket.close()

        self.websockets.clear()


manager = ControlServer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs("recordings", exist_ok=True)
    broadcast_task = asyncio.create_task(manager.broadcast_msgs())
    yield
    broadcast_task.cancel()
    manager.close_all()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(recordings.router)


@app.websocket("/ws")
async def live_websocket(websocket: WebSocket):
    await manager.connect_websocket(websocket)
    await manager.receive_msg(websocket)
