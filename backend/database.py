"""SQLAlchemy mappings compatible with the original SQLite schema."""
from contextlib import contextmanager
from sqlalchemy import Float, Integer, Text, create_engine, func, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

class Base(DeclarativeBase):
    pass

class Interview(Base):
    __tablename__ = 'interviews'
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    token: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default='invited', server_default='invited')
    created: Mapped[float] = mapped_column(Float)
    started: Mapped[float | None] = mapped_column(Float)
    completed: Mapped[float | None] = mapped_column(Float)
    mode: Mapped[str] = mapped_column(Text)
    expected_chunks: Mapped[int | None] = mapped_column(Integer)
    recording_complete: Mapped[int] = mapped_column(Integer, default=0, server_default='0')

class AnswerRecord(Base):
    __tablename__ = 'answers'
    interview_id: Mapped[str] = mapped_column(Text, primary_key=True)
    question_id: Mapped[str] = mapped_column(Text, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float)
    evaluation: Mapped[str | None] = mapped_column(Text)
    next_question: Mapped[str | None] = mapped_column(Text)

class IntegrityEvent(Base):
    __tablename__ = 'events'
    interview_id: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    elapsed: Mapped[float] = mapped_column(Float)
    detail: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float)

class RecordingChunk(Base):
    __tablename__ = 'chunks'
    interview_id: Mapped[str] = mapped_column(Text, primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    digest: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer)

def as_dict(record):
    return {column.key: getattr(record, column.key) for column in record.__table__.columns}

class Database:
    def __init__(self, path, url=None):
        target = url or URL.create('sqlite+pysqlite', database=str(path.resolve()))
        sqlite = make_url(target).get_backend_name() == 'sqlite'
        self.engine = create_engine(target, connect_args={'check_same_thread': False, 'timeout': 15} if sqlite else {}, pool_pre_ping=True)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self, *, write=False, interview_id=None):
        with self.sessions() as session:
            with session.begin():
                if write:
                    if self.engine.dialect.name == 'sqlite':
                        session.execute(text('BEGIN IMMEDIATE'))
                    elif interview_id:
                        session.execute(select(Interview.id).where(Interview.id == interview_id).with_for_update())
                yield session

    def count(self, session, model, iid):
        return session.scalar(select(func.count()).select_from(model).where(model.interview_id == iid))
