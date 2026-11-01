from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sonata.models import DownloadOptions, validate_url


def timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    """One connection per operation; WAL and transactions coordinate workers."""

    def __init__(self, path: Path):
        self.path = path
        self._write_lock = threading.RLock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'queued', options TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0, speed REAL NOT NULL DEFAULT 0,
                    eta INTEGER, error TEXT NOT NULL DEFAULT '', parent_id INTEGER,
                    created TEXT NOT NULL, updated TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS media (
                    media_key TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL,
                    collection TEXT NOT NULL, folder TEXT NOT NULL, files TEXT NOT NULL,
                    size INTEGER NOT NULL, completed TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS claims (media_key TEXT PRIMARY KEY, job_id INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state);
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}
            for name, definition in {
                "scan_state": "TEXT NOT NULL DEFAULT 'pending'",
                "scan": "TEXT NOT NULL DEFAULT '{}'",
                "auto_start": "INTEGER NOT NULL DEFAULT 0",
            }.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
            db.execute("PRAGMA user_version=2")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def recover(self):
        # Never restart network traffic automatically after a crash.
        with self._write_lock, self.connect() as db:
            db.execute(
                "UPDATE jobs SET state='paused',speed=0,eta=NULL,auto_start=0 WHERE state IN ('scanning','resolving','downloading','processing','queued')"
            )
            db.execute("UPDATE jobs SET scan_state='pending' WHERE scan_state='scanning'")
            db.execute("DELETE FROM claims")

    def add(
        self,
        url: str,
        options: DownloadOptions,
        title: str = "",
        parent_id: int | None = None,
        auto_start: bool = False,
    ) -> int:
        url = validate_url(url)
        options.validate()
        with self._write_lock, self.connect() as db:
            cur = db.execute(
                "INSERT INTO jobs(url,title,options,parent_id,created,updated,auto_start) VALUES(?,?,?,?,?,?,?)",
                (
                    url,
                    title or url,
                    json.dumps(options.to_dict()),
                    parent_id,
                    timestamp(),
                    timestamp(),
                    int(auto_start),
                ),
            )
            return cur.lastrowid

    def update(self, job_id: int, **values):
        allowed = {
            "title",
            "state",
            "progress",
            "speed",
            "eta",
            "error",
            "scan_state",
            "scan",
            "auto_start",
            "options",
        }
        if not values or not set(values) <= allowed:
            raise ValueError("Invalid job fields")
        values["updated"] = timestamp()
        with self._write_lock, self.connect() as db:
            db.execute(
                f"UPDATE jobs SET {','.join(k + '=?' for k in values)} WHERE id=?", (*values.values(), job_id)
            )

    def jobs(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM jobs ORDER BY id DESC")]

    def job(self, job_id: int) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return dict(row)

    def claim(self, media_key: str, job_id: int) -> bool:
        with self._write_lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT files FROM media WHERE media_key=?", (media_key,)).fetchone()
            if row and all(Path(p).is_file() for p in json.loads(row["files"])):
                return False
            result = db.execute("INSERT OR IGNORE INTO claims VALUES(?,?)", (media_key, job_id))
            return result.rowcount == 1

    def release(self, job_id: int):
        with self._write_lock, self.connect() as db:
            db.execute("DELETE FROM claims WHERE job_id=?", (job_id,))

    def complete(
        self, job_id: int, media_key: str, title: str, files: list[Path], folder: Path, collection: str
    ):
        if not files or any(not p.is_file() for p in files):
            raise ValueError("The downloader did not produce a media file.")
        with self._write_lock, self.connect() as db:
            job = db.execute("SELECT url FROM jobs WHERE id=?", (job_id,)).fetchone()
            db.execute(
                "INSERT OR REPLACE INTO media VALUES(?,?,?,?,?,?,?,?)",
                (
                    media_key,
                    title,
                    job["url"],
                    collection,
                    str(folder.resolve()),
                    json.dumps([str(p.resolve()) for p in files]),
                    sum(p.stat().st_size for p in files),
                    timestamp(),
                ),
            )
            db.execute(
                "UPDATE jobs SET state='completed',progress=100,speed=0,eta=NULL,error='',updated=? WHERE id=?",
                (timestamp(), job_id),
            )
            db.execute("DELETE FROM claims WHERE job_id=?", (job_id,))

    def history(self, query: str = "", collection: str | None = None) -> list[dict]:
        sql = "SELECT * FROM media WHERE (title LIKE ? ESCAPE '\\' OR url LIKE ? ESCAPE '\\')"
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params = [f"%{escaped}%", f"%{escaped}%"]
        if collection is not None:
            sql += " AND collection=?"
            params.append(collection)
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql + " ORDER BY completed DESC", params)]

    def setting(self, key: str, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def save_setting(self, key: str, value):
        with self._write_lock, self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, json.dumps(value)))

    def clear_finished(self):
        with self._write_lock, self.connect() as db:
            db.execute("DELETE FROM jobs WHERE state IN ('completed','cancelled','skipped','expanded')")
