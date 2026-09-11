"""Database engine and session handling.

One SQLite file holds everything. Foreign keys are enforced (SQLite does not do this by
default) and WAL is enabled so a backup can be taken while the application is running.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

#: Waar de administratie stond voordat de standaardplek veranderde.
OUDE_DATA_DIR = Path("Documents") / "boekhouding-data"


def standaard_data_dir(home: Path | None = None) -> Path:
    """Where the administration lives when BOEKHOUDING_DATA is not set.

    A visible folder straight in the user's home directory, deliberately *not* inside
    Documents. On Windows, Documents is the folder OneDrive offers to back up, and a
    live SQLite database in a syncing folder is a well-known way to corrupt one -- this
    program is meant to keep working without a cloud anywhere near it. AppData would be
    wrong for the opposite reason: facturen/ and documenten/ are the user's own records,
    which have to stay findable, copyable to a USB stick, and readable seven years from
    now, not hidden away as program state.

    An administration already sitting in the old location keeps being used, so updating
    the program never leaves someone staring at an empty set of books.
    """
    home = home or Path.home()
    nieuw = home / "Boekhouding"
    oud = home / OUDE_DATA_DIR
    if not nieuw.exists() and (oud / "boekhouding.sqlite3").exists():
        return oud
    return nieuw


DATA_DIR = Path(os.environ.get("BOEKHOUDING_DATA") or standaard_data_dir())
DB_PATH = DATA_DIR / "boekhouding.sqlite3"
DOCUMENTS_DIR = DATA_DIR / "documenten"
INVOICE_PDF_DIR = DATA_DIR / "facturen"
INBOX_DIR = DATA_DIR / "inbox"

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=FULL")
    cursor.close()


def ensure_directories() -> None:
    for directory in (DATA_DIR, DOCUMENTS_DIR, INVOICE_PDF_DIR, INBOX_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def get_engine() -> Engine:
    global _engine, _SessionFactory
    if _engine is None:
        ensure_directories()
        _engine = create_engine(f"sqlite:///{DB_PATH}", future=True)
        _SessionFactory = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionFactory is not None
    return _SessionFactory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on any exception."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    with session_scope() as session:
        yield session


def init_db() -> None:
    from app import models  # noqa: F401  -- registers the mappings

    models.Base.metadata.create_all(get_engine())
    with session_scope() as session:
        models.Settings.get_or_create(session)


def configure_for_tests(directory: Path) -> None:
    """Point the whole application at a throwaway data directory."""
    global _engine, _SessionFactory, DATA_DIR, DB_PATH, DOCUMENTS_DIR, INVOICE_PDF_DIR, INBOX_DIR
    DATA_DIR = directory
    DB_PATH = directory / "boekhouding.sqlite3"
    DOCUMENTS_DIR = directory / "documenten"
    INVOICE_PDF_DIR = directory / "facturen"
    INBOX_DIR = directory / "inbox"
    _engine = None
    _SessionFactory = None
    init_db()
