import os
from dotenv import load_dotenv
from sqlmodel import SQLModel, create_engine
from . import models

load_dotenv()

engine = create_engine(
    os.getenv("DB_URL"), echo=True, connect_args={"check_same_thread": False}
)

if __name__ == "__main__":
    print(engine)
    print(os.getenv("DB_URL"))

    SQLModel.metadata.create_all(engine)
