"""Shared pytest fixtures."""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from aicoach.db import connect, init_db
from aicoach.repository import SetInput, WorkoutRepository


@pytest.fixture
def repo(tmp_path) -> WorkoutRepository:
    db_path = tmp_path / "test.db"
    conn = connect(db_path)
    init_db(conn)
    repository = WorkoutRepository(conn, default_unit="kg", idle_timeout_seconds=10800)
    yield repository
    conn.close()


@pytest.fixture
def fixed_now() -> datetime:
    return datetime(2026, 7, 14, 10, 0, 0)
