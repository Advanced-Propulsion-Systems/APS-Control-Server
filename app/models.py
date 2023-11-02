from sqlmodel import SQLModel, Field
from datetime import datetime, UTC
import uuid


class Recording(SQLModel, table=True):
    id: uuid.UUID = Field(primary_key=True, default_factory=uuid.uuid4)
    name: str | None = Field(min_length=3)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
