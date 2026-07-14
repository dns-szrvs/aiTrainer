"""SQLite connection and schema management."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS exercise (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    category TEXT,
    default_unit TEXT NOT NULL DEFAULT 'kg',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS exercise_alias (
    alias TEXT NOT NULL UNIQUE COLLATE NOCASE,
    exercise_id INTEGER NOT NULL REFERENCES exercise(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS workout_session (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    last_activity_at TEXT NOT NULL,
    closed INTEGER NOT NULL DEFAULT 0,
    note TEXT
);

CREATE TABLE IF NOT EXISTS workout_set (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES workout_session(id) ON DELETE CASCADE,
    exercise_id INTEGER NOT NULL REFERENCES exercise(id) ON DELETE CASCADE,
    performed_on TEXT NOT NULL,
    set_index INTEGER NOT NULL,
    reps INTEGER NOT NULL,
    weight REAL NOT NULL,
    unit TEXT NOT NULL DEFAULT 'kg',
    rpe REAL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_workout_set_session ON workout_set(session_id);
CREATE INDEX IF NOT EXISTS idx_workout_set_exercise ON workout_set(exercise_id);
CREATE INDEX IF NOT EXISTS idx_workout_set_performed_on ON workout_set(performed_on);
CREATE INDEX IF NOT EXISTS idx_workout_session_closed ON workout_session(closed, last_activity_at);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()
