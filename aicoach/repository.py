"""Data access layer for workouts, exercises, and sessions."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _normalize_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", name.strip())
    return cleaned


def _title_case(name: str) -> str:
    return " ".join(part.capitalize() for part in name.split())


@dataclass(frozen=True)
class Exercise:
    id: int
    canonical_name: str
    default_unit: str
    created: bool = False


@dataclass(frozen=True)
class SetInput:
    reps: int
    weight: float
    unit: str | None = None
    rpe: float | None = None
    note: str | None = None


class WorkoutRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        default_unit: str = "kg",
        idle_timeout_seconds: int = 10800,
    ) -> None:
        self.conn = conn
        self.default_unit = default_unit
        self.idle_timeout_seconds = idle_timeout_seconds

    def resolve_exercise(self, name: str) -> Exercise:
        normalized = _normalize_name(name)
        if not normalized:
            raise ValueError("Exercise name cannot be empty")

        row = self.conn.execute(
            """
            SELECT e.id, e.canonical_name, e.default_unit
            FROM exercise e
            WHERE e.canonical_name = ? COLLATE NOCASE
            """,
            (normalized,),
        ).fetchone()
        if row:
            return Exercise(row["id"], row["canonical_name"], row["default_unit"])

        row = self.conn.execute(
            """
            SELECT e.id, e.canonical_name, e.default_unit
            FROM exercise_alias a
            JOIN exercise e ON e.id = a.exercise_id
            WHERE a.alias = ? COLLATE NOCASE
            """,
            (normalized,),
        ).fetchone()
        if row:
            return Exercise(row["id"], row["canonical_name"], row["default_unit"])

        canonical = _title_case(normalized)
        cursor = self.conn.execute(
            """
            INSERT INTO exercise (canonical_name, default_unit)
            VALUES (?, ?)
            """,
            (canonical, self.default_unit),
        )
        exercise_id = cursor.lastrowid
        aliases = {normalized.lower()}
        parts = normalized.lower().split()
        if len(parts) > 1:
            aliases.add(parts[0])
        for alias in aliases:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO exercise_alias (alias, exercise_id)
                VALUES (?, ?)
                """,
                (alias, exercise_id),
            )
        self.conn.commit()
        return Exercise(exercise_id, canonical, self.default_unit, created=True)

    def _close_stale_sessions(self, now: datetime, performed_on: str) -> None:
        cutoff = (now - timedelta(seconds=self.idle_timeout_seconds)).isoformat(sep=" ")
        self.conn.execute(
            """
            UPDATE workout_session
            SET closed = 1
            WHERE closed = 0
              AND (
                    last_activity_at < ?
                 OR date(started_at) != date(?)
              )
            """,
            (cutoff, performed_on),
        )

    def _get_or_create_open_session(self, performed_on: str, now: datetime) -> int:
        self._close_stale_sessions(now, performed_on)
        cutoff = (now - timedelta(seconds=self.idle_timeout_seconds)).isoformat(sep=" ")
        row = self.conn.execute(
            """
            SELECT id
            FROM workout_session
            WHERE closed = 0
              AND date(started_at) = date(?)
              AND last_activity_at >= ?
            ORDER BY last_activity_at DESC
            LIMIT 1
            """,
            (performed_on, cutoff),
        ).fetchone()

        now_iso = now.replace(microsecond=0).isoformat(sep=" ")
        if row:
            session_id = row["id"]
            self.conn.execute(
                "UPDATE workout_session SET last_activity_at = ? WHERE id = ?",
                (now_iso, session_id),
            )
            return session_id

        cursor = self.conn.execute(
            """
            INSERT INTO workout_session (started_at, last_activity_at)
            VALUES (?, ?)
            """,
            (now_iso, now_iso),
        )
        return cursor.lastrowid

    def log_workout(
        self,
        exercise_name: str,
        sets: list[SetInput],
        *,
        performed_on: str | None = None,
        note: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not sets:
            raise ValueError("At least one set is required")

        now = now or datetime.now()
        performed_on = performed_on or now.date().isoformat()
        exercise = self.resolve_exercise(exercise_name)
        session_id = self._get_or_create_open_session(performed_on, now)

        stored_sets: list[dict[str, Any]] = []
        for index, set_input in enumerate(sets, start=1):
            unit = set_input.unit or exercise.default_unit or self.default_unit
            cursor = self.conn.execute(
                """
                INSERT INTO workout_set (
                    session_id, exercise_id, performed_on, set_index,
                    reps, weight, unit, rpe, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    exercise.id,
                    performed_on,
                    index,
                    set_input.reps,
                    set_input.weight,
                    unit,
                    set_input.rpe,
                    set_input.note,
                ),
            )
            stored_sets.append(
                {
                    "id": cursor.lastrowid,
                    "set_index": index,
                    "reps": set_input.reps,
                    "weight": set_input.weight,
                    "unit": unit,
                    "rpe": set_input.rpe,
                    "note": set_input.note,
                }
            )

        if note:
            self.conn.execute(
                """
                UPDATE workout_session
                SET note = CASE
                    WHEN note IS NULL OR note = '' THEN ?
                    ELSE note || ' | ' || ?
                END
                WHERE id = ?
                """,
                (note, note, session_id),
            )

        self.conn.commit()
        session_summary = self._session_summary(session_id)
        return {
            "exercise": {
                "id": exercise.id,
                "canonical_name": exercise.canonical_name,
                "created": exercise.created,
            },
            "performed_on": performed_on,
            "sets": stored_sets,
            "session": session_summary,
        }

    def _session_summary(self, session_id: int) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT id, started_at, last_activity_at, closed, note
            FROM workout_session
            WHERE id = ?
            """,
            (session_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Session {session_id} not found")

        stats = self.conn.execute(
            """
            SELECT
                COUNT(DISTINCT exercise_id) AS exercise_count,
                COUNT(*) AS set_count
            FROM workout_set
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()

        return {
            "id": row["id"],
            "started_at": row["started_at"],
            "last_activity_at": row["last_activity_at"],
            "closed": bool(row["closed"]),
            "note": row["note"],
            "exercise_count": stats["exercise_count"],
            "set_count": stats["set_count"],
        }

    def get_current_workout(self, now: datetime | None = None) -> dict[str, Any] | None:
        now = now or datetime.now()
        performed_on = now.date().isoformat()
        self._close_stale_sessions(now, performed_on)
        cutoff = (now - timedelta(seconds=self.idle_timeout_seconds)).isoformat(sep=" ")

        row = self.conn.execute(
            """
            SELECT id, started_at, last_activity_at, closed, note
            FROM workout_session
            WHERE closed = 0
              AND date(started_at) = date(?)
              AND last_activity_at >= ?
            ORDER BY last_activity_at DESC
            LIMIT 1
            """,
            (performed_on, cutoff),
        ).fetchone()
        if not row:
            return None

        exercises = self._session_exercises(row["id"])
        return {
            "id": row["id"],
            "started_at": row["started_at"],
            "last_activity_at": row["last_activity_at"],
            "closed": bool(row["closed"]),
            "note": row["note"],
            "exercises": exercises,
        }

    def _session_exercises(self, session_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT
                e.canonical_name AS exercise,
                ws.set_index,
                ws.reps,
                ws.weight,
                ws.unit,
                ws.rpe,
                ws.note
            FROM workout_set ws
            JOIN exercise e ON e.id = ws.exercise_id
            WHERE ws.session_id = ?
            ORDER BY ws.id
            """,
            (session_id,),
        ).fetchall()

        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row["exercise"], []).append(
                {
                    "set_index": row["set_index"],
                    "reps": row["reps"],
                    "weight": row["weight"],
                    "unit": row["unit"],
                    "rpe": row["rpe"],
                    "note": row["note"],
                }
            )

        return [
            {"exercise": exercise, "sets": sets}
            for exercise, sets in grouped.items()
        ]

    def get_exercise_history(self, exercise_name: str, limit: int = 10) -> dict[str, Any]:
        exercise = self.resolve_exercise(exercise_name)
        rows = self.conn.execute(
            """
            SELECT
                ws.session_id,
                ws.performed_on,
                ws.set_index,
                ws.reps,
                ws.weight,
                ws.unit,
                ws.rpe,
                ws.note
            FROM workout_set ws
            WHERE ws.exercise_id = ?
            ORDER BY ws.performed_on DESC, ws.session_id DESC, ws.set_index ASC
            """,
            (exercise.id,),
        ).fetchall()

        sessions: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for row in rows:
            key = (row["session_id"], row["performed_on"])
            if current is None or (current["session_id"], current["performed_on"]) != key:
                if current is not None:
                    sessions.append(current)
                current = {
                    "session_id": row["session_id"],
                    "performed_on": row["performed_on"],
                    "sets": [],
                }
            current["sets"].append(
                {
                    "set_index": row["set_index"],
                    "reps": row["reps"],
                    "weight": row["weight"],
                    "unit": row["unit"],
                    "rpe": row["rpe"],
                    "note": row["note"],
                }
            )
            if len(sessions) >= limit and current is not None:
                break

        if current is not None and len(sessions) < limit:
            sessions.append(current)

        return {
            "exercise": exercise.canonical_name,
            "sessions": sessions[:limit],
        }

    def get_recent_workouts(self, limit: int = 10, days: int | None = None) -> list[dict[str, Any]]:
        params: list[Any] = []
        where_clause = ""
        if days is not None:
            where_clause = "WHERE date(ws.started_at) >= date('now', ?)"
            params.append(f"-{days} days")

        rows = self.conn.execute(
            f"""
            SELECT
                ws.id AS session_id,
                ws.started_at,
                ws.last_activity_at,
                ws.closed,
                ws.note,
                COUNT(DISTINCT wset.exercise_id) AS exercise_count,
                COUNT(wset.id) AS set_count
            FROM workout_session ws
            LEFT JOIN workout_set wset ON wset.session_id = ws.id
            {where_clause}
            GROUP BY ws.id
            ORDER BY ws.started_at DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()

        workouts: list[dict[str, Any]] = []
        for row in rows:
            workouts.append(
                {
                    "session_id": row["session_id"],
                    "started_at": row["started_at"],
                    "last_activity_at": row["last_activity_at"],
                    "closed": bool(row["closed"]),
                    "note": row["note"],
                    "exercise_count": row["exercise_count"],
                    "set_count": row["set_count"],
                    "exercises": self._session_exercises(row["session_id"]),
                }
            )
        return workouts

    def list_exercises(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT e.id, e.canonical_name, e.default_unit, e.category
            FROM exercise e
            ORDER BY e.canonical_name COLLATE NOCASE
            """
        ).fetchall()

        exercises: list[dict[str, Any]] = []
        for row in rows:
            aliases = self.conn.execute(
                "SELECT alias FROM exercise_alias WHERE exercise_id = ? ORDER BY alias",
                (row["id"],),
            ).fetchall()
            exercises.append(
                {
                    "id": row["id"],
                    "canonical_name": row["canonical_name"],
                    "default_unit": row["default_unit"],
                    "category": row["category"],
                    "aliases": [alias["alias"] for alias in aliases],
                }
            )
        return exercises

    def get_exercise_session_summaries(self, exercise_name: str) -> list[dict[str, Any]]:
        """Return per-session aggregates for progress calculations."""
        exercise = self.resolve_exercise(exercise_name)
        rows = self.conn.execute(
            """
            SELECT
                ws.session_id,
                ws.performed_on,
                MAX(ws.weight) AS top_weight,
                SUM(ws.reps) AS total_reps,
                SUM(ws.weight * ws.reps) AS volume,
                MAX(ws.reps) AS top_reps_at_max_weight
            FROM workout_set ws
            WHERE ws.exercise_id = ?
            GROUP BY ws.session_id, ws.performed_on
            ORDER BY ws.performed_on ASC, ws.session_id ASC
            """,
            (exercise.id,),
        ).fetchall()

        summaries: list[dict[str, Any]] = []
        for row in rows:
            top_weight = row["top_weight"]
            top_reps = self.conn.execute(
                """
                SELECT reps
                FROM workout_set
                WHERE exercise_id = ? AND session_id = ? AND weight = ?
                ORDER BY reps DESC
                LIMIT 1
                """,
                (exercise.id, row["session_id"], top_weight),
            ).fetchone()
            summaries.append(
                {
                    "session_id": row["session_id"],
                    "performed_on": row["performed_on"],
                    "top_weight": top_weight,
                    "top_reps": top_reps["reps"] if top_reps else row["top_reps_at_max_weight"],
                    "total_reps": row["total_reps"],
                    "volume": row["volume"],
                }
            )
        return summaries
