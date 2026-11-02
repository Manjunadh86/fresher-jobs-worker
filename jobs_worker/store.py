"""SQLite persistence: every job ever seen, every digest, every run. Replaces the old seen.json ledger."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

from .config import DATA_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  url_key     TEXT PRIMARY KEY,
  url         TEXT NOT NULL,
  company     TEXT NOT NULL,
  title       TEXT NOT NULL,
  location    TEXT,
  tier        TEXT,
  kind        TEXT,
  source      TEXT,
  posted      TEXT,
  salary      TEXT,
  batch       TEXT,
  snippet     TEXT,
  first_seen  TEXT NOT NULL,
  last_seen   TEXT NOT NULL,
  published   INTEGER NOT NULL DEFAULT 0,
  published_on TEXT
);
CREATE INDEX IF NOT EXISTS jobs_published ON jobs(published, tier);
CREATE TABLE IF NOT EXISTS runs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at  TEXT NOT NULL,
  finished_at TEXT,
  ok          INTEGER,
  candidates  INTEGER,
  mnc         INTEGER,
  startups    INTEGER,
  errors      TEXT,
  note        TEXT
);
CREATE TABLE IF NOT EXISTS digests (
  day         TEXT PRIMARY KEY,
  markdown    TEXT NOT NULL,
  payload     TEXT NOT NULL,
  created_at  TEXT NOT NULL
);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    try:
        con.execute("ALTER TABLE jobs ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")
        con.commit()
    except sqlite3.OperationalError:
        pass  # column exists
    _import_legacy_ledger(con)
    return con


def day_rows(con, day: str, include_hidden=False):
    q = "SELECT * FROM jobs WHERE published_on=?" + ("" if include_hidden else " AND hidden=0") + " ORDER BY tier, company, title"
    rows = [dict(r) for r in con.execute(q, (day,))]
    for r in rows:
        r["posted"] = dt.date.fromisoformat(r["posted"]) if r.get("posted") else None
    return rows


def set_hidden(con, url_key: str, hidden: bool):
    con.execute("UPDATE jobs SET hidden=? WHERE url_key=?", (int(hidden), url_key))
    con.commit()


def days(con):
    return [r[0] for r in con.execute("SELECT DISTINCT published_on FROM jobs WHERE published_on IS NOT NULL ORDER BY 1 DESC")]


def _import_legacy_ledger(con):
    """One-time import of the old scripts/daily_fresher_jobs.py seen.json so nothing gets reposted."""
    legacy = DATA_DIR / "seen.json"
    if not legacy.exists():
        return
    if con.execute("SELECT 1 FROM runs WHERE note='legacy-import' LIMIT 1").fetchone():
        return
    try:
        data = json.loads(legacy.read_text())
    except Exception:  # noqa: BLE001
        return
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    for key, meta in data.items():
        con.execute(
            "INSERT OR IGNORE INTO jobs(url_key,url,company,title,first_seen,last_seen,published,published_on)"
            " VALUES(?,?,?,?,?,?,1,?)",
            (key, "https://" + key if not key.startswith("http") else key, meta.get("company", ""),
             meta.get("title", ""), meta.get("first_posted", now), now, meta.get("first_posted")),
        )
    con.execute("INSERT INTO runs(started_at,finished_at,ok,note) VALUES(?,?,1,'legacy-import')", (now, now))
    con.commit()


def published_keys(con) -> set[str]:
    return {r[0] for r in con.execute("SELECT url_key FROM jobs WHERE published=1")}


def upsert_candidates(con, rows, today: str):
    for r in rows:
        con.execute(
            """INSERT INTO jobs(url_key,url,company,title,location,tier,kind,source,posted,salary,batch,snippet,first_seen,last_seen)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(url_key) DO UPDATE SET last_seen=excluded.last_seen, posted=COALESCE(jobs.posted, excluded.posted),
                 location=COALESCE(NULLIF(jobs.location,''), excluded.location), snippet=COALESCE(NULLIF(jobs.snippet,''), excluded.snippet)""",
            (r["url_key"], r["url"], r["company"], r["title"], r.get("location"), r.get("tier"), r.get("kind"), r.get("source"),
             r["posted"].isoformat() if r.get("posted") else None, r.get("salary", ""), r.get("batch", ""), r.get("snippet", ""),
             today, today),
        )
    con.commit()


def mark_published(con, rows, today: str):
    con.executemany("UPDATE jobs SET published=1, published_on=COALESCE(published_on, ?) WHERE url_key=?",
                    [(today, r["url_key"]) for r in rows])
    con.commit()


def start_run(con) -> int:
    cur = con.execute("INSERT INTO runs(started_at) VALUES(?)", (dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),))
    con.commit()
    return cur.lastrowid


def finish_run(con, run_id, ok, candidates=0, mnc=0, startups=0, errors=None, note=""):
    con.execute("UPDATE runs SET finished_at=?, ok=?, candidates=?, mnc=?, startups=?, errors=?, note=? WHERE id=?",
                (dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), int(ok), candidates, mnc, startups,
                 json.dumps(errors or []), note, run_id))
    con.commit()


def save_digest(con, day, markdown, payload):
    con.execute("INSERT OR REPLACE INTO digests(day,markdown,payload,created_at) VALUES(?,?,?,?)",
                (day, markdown, json.dumps(payload, default=str), dt.datetime.now(dt.UTC).isoformat(timespec="seconds")))
    con.commit()


def last_digest_day(con) -> str | None:
    r = con.execute("SELECT day FROM digests ORDER BY day DESC LIMIT 1").fetchone()
    return r[0] if r else None
