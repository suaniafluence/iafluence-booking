from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_config


class Base(DeclarativeBase):
    pass


# Serverless Postgres (e.g. Neon free tier) suspends after ~5 min idle: the first connection then waits
# for a cold start. pool_pre_ping drops connections closed by the suspend; connect_timeout leaves room to wake up.
CONNECT_TIMEOUT_S = 10

engine = create_engine(
    get_config().database_url,
    pool_pre_ping=True,
    connect_args={"connect_timeout": CONNECT_TIMEOUT_S},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db
