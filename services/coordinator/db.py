from sqlmodel import create_engine, Session, SQLModel
from .models import Task, Submission, WorkerScore  # 👈 this line is key

DATABASE_URL = "sqlite:///./coordinator.db"
engine = create_engine(DATABASE_URL, echo=False, connect_args={
                       "check_same_thread": False})


def init_db():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
