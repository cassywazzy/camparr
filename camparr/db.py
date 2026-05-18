import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = os.environ.get("CAMPARR_DB", "/config/camparr.db")


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS search_history (
                album_id      INTEGER PRIMARY KEY,
                artist        TEXT NOT NULL,
                album         TEXT NOT NULL,
                last_searched TEXT NOT NULL,
                result        TEXT NOT NULL,
                bandcamp_url  TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS downloads (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                album_id      INTEGER,
                artist        TEXT NOT NULL,
                album         TEXT NOT NULL,
                bandcamp_url  TEXT NOT NULL,
                format        TEXT NOT NULL,
                status        TEXT NOT NULL,
                files         TEXT,
                error         TEXT,
                created_at    TEXT NOT NULL,
                completed_at  TEXT
            )
        """)


def should_search(album_id, cooldown_hours):
    with _conn() as c:
        row = c.execute(
            "SELECT last_searched, result FROM search_history WHERE album_id = ?",
            (album_id,),
        ).fetchone()
    if not row:
        return True
    if row["result"] == "found":
        return False
    last = datetime.fromisoformat(row["last_searched"])
    return datetime.utcnow() - last > timedelta(hours=cooldown_hours)


def record_search(album_id, artist, album, result, bandcamp_url=None):
    with _conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO search_history
               (album_id, artist, album, last_searched, result, bandcamp_url)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (album_id, artist, album, datetime.utcnow().isoformat(), result, bandcamp_url),
        )


def record_download(album_id, artist, album, bandcamp_url, fmt, status, files=None, error=None):
    with _conn() as c:
        c.execute(
            """INSERT INTO downloads
               (album_id, artist, album, bandcamp_url, format, status, files, error, created_at, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                album_id, artist, album, bandcamp_url, fmt, status,
                ",".join(files) if files else None,
                error,
                datetime.utcnow().isoformat(),
                datetime.utcnow().isoformat() if status in ("done", "error") else None,
            ),
        )


def get_downloads(limit=50):
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM downloads ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_search_history(limit=100):
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM search_history ORDER BY last_searched DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_stats():
    with _conn() as c:
        total_searches = c.execute("SELECT COUNT(*) FROM search_history").fetchone()[0]
        found = c.execute("SELECT COUNT(*) FROM search_history WHERE result = 'found'").fetchone()[0]
        total_downloads = c.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]
        successful = c.execute("SELECT COUNT(*) FROM downloads WHERE status = 'done'").fetchone()[0]
        failed = c.execute("SELECT COUNT(*) FROM downloads WHERE status = 'error'").fetchone()[0]
    return {
        "total_searches": total_searches,
        "found": found,
        "total_downloads": total_downloads,
        "successful": successful,
        "failed": failed,
    }
