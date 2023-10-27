from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import asyncio
import random


class ControlServer:
    def __init__(self) -> None:
        self.read_count = 0
        self.websockets: set[WebSocket] = set()

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

            msg = {"type": "data", "data": data}
            for websocket in self.websockets:
                await websocket.send_json(msg)

            self.read_count += 1

    async def receive_msg(self, socket: WebSocket):
        try:
            while True:
                msg = await socket.receive_json()
                print(msg)

        except WebSocketDisconnect:
            self.websockets.remove(socket)

    async def close_all(self):
        for websocket in self.websockets:
            await websocket.close()

        self.websockets.clear()


manager = ControlServer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    broadcast_task = asyncio.create_task(manager.broadcast_msgs())
    yield
    broadcast_task.cancel()
    manager.close_all()


app = FastAPI(lifespan=lifespan)


@app.websocket("/ws")
async def live_websocket(websocket: WebSocket):
    await manager.connect_websocket(websocket)
    await manager.receive_msg(websocket)
