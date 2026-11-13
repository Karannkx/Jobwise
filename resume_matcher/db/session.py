"""Engine / session management."""

from __future__ import annotations

import logging
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ..errors import StorageError
from .models import Base

log = logging.getLogger(__name__)


def restrict_permissions(path: Path) -> None:
    """Owner-only permissions where the OS supports it (no-op on Windows)."""
    if sys.platform == "win32":
        return
    try:
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
    except OSError:
        log.debug("could not restrict permissions on %s", path)


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            restrict_permissions(self.path.parent)
            self.engine: Engine = create_engine(
                f"sqlite:///{self.path}",
                connect_args={"check_same_thread": False, "timeout": 30},
            )
            event.listen(self.engine, "connect", self._on_connect)
            Base.metadata.create_all(self.engine)
            self._migrate()
        except (OSError, SQLAlchemyError) as exc:
            log.exception("database initialisation failed")
            raise StorageError(
                f"The local database could not be opened at {self.path}. "
                "Check that the folder exists and that you have permission to write to it."
            ) from exc
        if self.path.exists():
            restrict_permissions(self.path)
        self._factory = sessionmaker(self.engine, expire_on_commit=False)

    def _migrate(self) -> None:
        """Additive schema upgrade for databases created by an older version.

        Only adds missing nullable / defaulted columns and the unique job index; never drops data.
        """
        insp = inspect(self.engine)
        with self.engine.begin() as conn:
            for table in Base.metadata.sorted_tables:
                if not insp.has_table(table.name):
                    continue
                have = {c["name"] for c in insp.get_columns(table.name)}
                for col in table.columns:
                    if col.name in have:
                        continue
                    ddl = f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(self.engine.dialect)}"
                    if col.server_default is not None:
                        ddl += f" DEFAULT '{col.server_default.arg}'"
                    conn.exec_driver_sql(ddl)
                    log.info("database upgraded: added %s.%s", table.name, col.name)
            conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_jobs_source_ext ON jobs (source, external_id)"
            )

    @staticmethod
    def _on_connect(dbapi_conn, _record) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._factory()
        try:
            yield session
            session.commit()
        except OperationalError as exc:
            session.rollback()
            log.exception("database operational error")
            raise StorageError(
                "The local database is unavailable (it may be locked or read-only). "
                "Close other copies of the application and try again."
            ) from exc
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()
