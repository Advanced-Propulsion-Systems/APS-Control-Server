from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlmodel import Session, select, desc
import os
import uuid
from ..models import Recording
from ..dependencies import get_session

router = APIRouter(prefix="/recordings")


@router.get("/")
async def index_recordings(session: Session = Depends(get_session)) -> list[Recording]:
    data = session.exec(select(Recording).order_by(desc(Recording.created_at))).all()
    return data


@router.get("/{id}")
async def download_recording(id: uuid.UUID, session: Session = Depends(get_session)):
    recording = session.get(Recording, id)
    if recording.name is None:
        recording.name = recording.created_at.isoformat()

    return FileResponse(
        path=os.path.join("recordings", id.hex + ".csv"),
        filename=recording.name + ".csv",
    )


@router.delete("/{id}")
async def delete_recording(id: uuid.UUID, session: Session = Depends(get_session)):
    raise NotImplementedError
