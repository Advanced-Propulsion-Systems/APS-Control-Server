from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import random
import os
import serial
from io import TextIOWrapper
from .models import Recording
from sqlmodel import Session
from .routers import recordings
from .database import engine
import json
from dotenv import load_dotenv

load_dotenv()


class ControlServer:
    def __init__(self) -> None:
        self.read_count = 0
        self.websockets: set[WebSocket] = set()

        self.recording_file: TextIOWrapper | None = None
        self.recording_count = 0
        self.data_queue: asyncio.Queue[dict] = asyncio.Queue()

        self.sensors = ["Sens1", "sens2", "sens3"]

        if os.getenv("DATA_SOURCE") != "fake":
            self.serial_port = serial.Serial("/dev/ttyUSB0")

    def sensor_metadata(self):
        data = []
        for name in self.sensors:
            data.append(
                {
                    "id": name,
                }
            )

        return {"type": "setup", "sensors": data}

    async def connect_websocket(self, websocket: WebSocket):
        await websocket.accept()
        await websocket.send_json(self.sensor_metadata())
        self.websockets.add(websocket)

    async def read_sensors(self):
        while True:
            data = [{}]
            if os.getenv("DATA_SOURCE") != "fake":
                if self.serial_port.in_waiting == 0:
                    await asyncio.sleep(0)
                    continue

                buffer = self.serial_port.read_until()
                try:
                    data[0] = json.loads(buffer)
                except Exception:
                    await asyncio.sleep(0.1)
                    continue

                if data[0]["type"] == "data":
                    await self.data_queue.put(
                        {
                            "id": self.sensors[data[0]["id"]],
                            "time": data[0]["time"] / 1000,
                            "value": data[0]["value"],
                        }
                    )

                await asyncio.sleep(0)

            else:
                data = []
                for index in range(3):
                    data.append(
                        {
                            "id": self.sensors[index],
                            "time": self.read_count,
                            "value": random.random(),
                        }
                    )

                    await self.data_queue.put(data[index])

                await asyncio.sleep(1)

            if self.recording_file is not None:
                self.recording_file.write(str(self.recording_count))
                for key, value in data.items():
                    self.recording_file.write("," + str(value["value"]))
                self.recording_file.write("\n")
                self.recording_count += 1

            self.read_count += 1

    async def broadcast_sensor_data(self):
        while True:
            data = await self.data_queue.get()
            await self.broadcast_msg({"type": "data", "data": data})

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

                elif msg["cmd"] == "toggle-relay":
                    await self.toggle_relay(msg["id"], msg["state"])

        except WebSocketDisconnect as e:
            print("Disconnect websocket", e)
            self.websockets.remove(socket)

    async def close_all(self):
        for websocket in self.websockets:
            await websocket.close()

        self.websockets.clear()

    async def toggle_relay(self, relay_id: int, state: bool) -> None:
        print(relay_id, state)
        data = json.dumps({"cmd": "toggle-relay", "id": relay_id, "state": state})
        encoded = str.encode(data)
        self.serial_port.write(encoded)
        # TODO await self.update_status(=True)


manager = ControlServer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs("recordings", exist_ok=True)
    sensor_reading_task = asyncio.create_task(manager.read_sensors())
    broadcast_task = asyncio.create_task(manager.broadcast_sensor_data())
    yield
    sensor_reading_task.cancel()
    broadcast_task.cancel()
    await manager.close_all()


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
