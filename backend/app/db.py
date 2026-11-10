from contextlib import contextmanager
from pathlib import Path
from threading import Lock

from alembic.config import Config as MigrationConfig
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker, with_loader_criteria

from alembic import command

from .config import USER, defaults
from .models import Owned, Settings, User


class Database:
    def __init__(self, config):
        path = config.db_url.removeprefix("sqlite:///")
        self.directory = Path(path).parent
        self.engine = create_engine(
            config.db_url, hide_parameters=True, connect_args={"check_same_thread": False, "timeout": 30}
        )
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.lock = Lock()

        @event.listens_for(self.sessions, "do_orm_execute")
        def local_user(execution):
            if execution.is_select:
                execution.statement = execution.statement.options(
                    with_loader_criteria(
                        Owned, lambda entity: entity.user_id == USER, include_aliases=True
                    )
                )

        @event.listens_for(self.engine, "connect")
        def pragmas(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=30000")
            connection.execute("PRAGMA secure_delete=ON")

    def initialize(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        with self.engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            cfg = MigrationConfig()
            cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
            cfg.attributes["connection"] = conn
            from sqlalchemy import inspect

            if "alembic_version" in inspect(conn).get_table_names() and conn.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar() in ("0001", "0002", "0003","0004"):
                import sqlite3

                from .models import uid

                folder = self.directory / "backups"
                folder.mkdir(exist_ok=True)
                target = sqlite3.connect(folder / ("before-sources-" + uid() + ".db"))
                try:
                    conn.connection.driver_connection.backup(target)
                    if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise RuntimeError("Backup integrity check failed")
                finally:
                    target.close()
            command.upgrade(cfg, "head")
        with self.write() as s:
            if not s.get(User, USER):
                s.add(User(id=USER))
                s.flush()
                s.add(Settings(values=defaults()))

    @contextmanager
    def write(self):
        with self.lock, self.sessions.begin() as s:
            s.execute(text("BEGIN IMMEDIATE"))
            yield s


def settings(s):
    return defaults() | s.scalar(select(Settings).where(Settings.user_id == USER)).values


def one(s, cls, record_id):
    from fastapi import HTTPException

    obj = s.get(cls, record_id)
    if obj is None or obj.user_id != USER:
        raise HTTPException(404, "Record not found")
    return obj


def row(obj):
    from sqlalchemy import inspect

    return {c.key: getattr(obj, c.key) for c in inspect(obj).mapper.column_attrs}
