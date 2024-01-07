from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import random
import os
import serial_asyncio
from io import TextIOWrapper
from .models import Recording
from sqlmodel import Session
from .routers import recordings
from .database import engine
import json
from dotenv import load_dotenv
from csv import DictWriter

load_dotenv()


class ControlServer:
    def __init__(self) -> None:
        self.read_count = 0
        self.websockets: set[WebSocket] = set()

        self.recording_file: TextIOWrapper | None = None
        self.csv_writer: DictWriter | None = None
        self.recording_count = 0
        self.data_queue: asyncio.Queue[dict] = asyncio.Queue()

        self.sensors = ["Sens1", "sens2", "sens3"]

    async def configure(self):
        if os.getenv("DATA_SOURCE") != "fake":
            (
                self.serial_reader,
                self.serial_writer,
            ) = await serial_asyncio.open_serial_connection(
                url=os.getenv("DATA_SOURCE")
            )

        else:
            self.serial_reader, self.serial_writer = None, None

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
            if self.serial_reader is not None:
                buffer = await self.serial_reader.readuntil()
                try:
                    data[0] = json.loads(buffer)
                except Exception:
                    await asyncio.sleep(0)
                    continue

                if data[0]["type"] == "data":
                    await self.data_queue.put(
                        {
                            "id": self.sensors[data[0]["id"]],
                            "time": data[0]["time"] / 1000,
                            "value": data[0]["value"],
                        }
                    )

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
                for value in data:
                    self.csv_writer.writerow(
                        {"time": value["time"], value["id"]: value["value"]}
                    )
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
                        newline="",
                    )
                    self.csv_writer = DictWriter(
                        self.recording_file, ["time"] + self.sensors
                    )
                    self.recording_count = 0
                    self.csv_writer.writeheader()
                await self.update_status(recordingStatus=True)

            elif msg["cmd"] == "stop-recording":
                if self.recording_file is None:
                    continue

                self.recording_file.close()
                self.recording_file = None
                self.csv_writer = None
                await self.update_status(recordingStatus=False)

            elif msg["cmd"] == "ignite":
                raise NotImplementedError

            elif msg["cmd"] == "toggle-relay":
                await self.toggle_relay(msg["id"], msg["state"])

    async def close_all(self):
        for websocket in self.websockets:
            await websocket.close()

        self.websockets.clear()

    async def toggle_relay(self, relay_id: int, state: bool) -> None:
        print(relay_id, state)
        data = json.dumps({"cmd": "toggle-relay", "id": relay_id, "state": state})
        encoded = str.encode(data)
        self.serial_writer.write(encoded)
        await self.serial_writer.drain()
        # TODO await self.update_status(=True)


manager = ControlServer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs("recordings", exist_ok=True)
    await manager.configure()
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
    try:
        await manager.connect_websocket(websocket)
        await manager.receive_msg(websocket)
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in manager.websockets:
            manager.websockets.remove(websocket)
        print("Websocket disconnect")
