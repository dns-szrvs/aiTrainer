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
                ws.id,
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
                    "id": row["id"],
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

    def _require_session(self, session_id: int) -> sqlite3.Row:
        row = self.conn.execute(
            """
            SELECT id, started_at, last_activity_at, closed, note
            FROM workout_session
            WHERE id = ?
            """,
            (session_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Session {session_id} not found")
        return row

    def _require_set(self, set_id: int) -> sqlite3.Row:
        row = self.conn.execute(
            """
            SELECT
                ws.id,
                ws.session_id,
                ws.exercise_id,
                ws.performed_on,
                ws.set_index,
                ws.reps,
                ws.weight,
                ws.unit,
                ws.rpe,
                ws.note,
                e.canonical_name AS exercise
            FROM workout_set ws
            JOIN exercise e ON e.id = ws.exercise_id
            WHERE ws.id = ?
            """,
            (set_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Set {set_id} not found")
        return row

    @staticmethod
    def _replace_date(timestamp: str, new_date: str) -> str:
        time_part = timestamp.split(" ", 1)[1] if " " in timestamp else "00:00:00"
        return f"{new_date} {time_part}"

    def get_session(self, session_id: int) -> dict[str, Any]:
        row = self._require_session(session_id)
        performed_on = self.conn.execute(
            """
            SELECT performed_on
            FROM workout_set
            WHERE session_id = ?
            ORDER BY id
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        return {
            "id": row["id"],
            "started_at": row["started_at"],
            "last_activity_at": row["last_activity_at"],
            "performed_on": performed_on["performed_on"] if performed_on else None,
            "closed": bool(row["closed"]),
            "note": row["note"],
            "exercises": self._session_exercises(session_id),
            "summary": self._session_summary(session_id),
        }

    def update_session(
        self,
        session_id: int,
        *,
        performed_on: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        row = self._require_session(session_id)
        if performed_on is None and note is None:
            raise ValueError("At least one of performed_on or note must be provided")

        if performed_on is not None:
            self.conn.execute(
                """
                UPDATE workout_set
                SET performed_on = ?
                WHERE session_id = ?
                """,
                (performed_on, session_id),
            )
            self.conn.execute(
                """
                UPDATE workout_session
                SET started_at = ?, last_activity_at = ?
                WHERE id = ?
                """,
                (
                    self._replace_date(row["started_at"], performed_on),
                    self._replace_date(row["last_activity_at"], performed_on),
                    session_id,
                ),
            )

        if note is not None:
            self.conn.execute(
                "UPDATE workout_session SET note = ? WHERE id = ?",
                (note, session_id),
            )

        self.conn.commit()
        return self.get_session(session_id)

    def update_workout_set(
        self,
        set_id: int,
        *,
        reps: int | None = None,
        weight: float | None = None,
        unit: str | None = None,
        rpe: float | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        row = self._require_set(set_id)
        updates: dict[str, Any] = {}
        if reps is not None:
            updates["reps"] = reps
        if weight is not None:
            updates["weight"] = weight
        if unit is not None:
            updates["unit"] = unit
        if rpe is not None:
            updates["rpe"] = rpe
        if note is not None:
            updates["note"] = note
        if not updates:
            raise ValueError("At least one set field must be provided")

        assignments = ", ".join(f"{column} = ?" for column in updates)
        self.conn.execute(
            f"UPDATE workout_set SET {assignments} WHERE id = ?",
            (*updates.values(), set_id),
        )
        self.conn.commit()
        updated = self._require_set(set_id)
        return {
            "id": updated["id"],
            "session_id": updated["session_id"],
            "exercise": updated["exercise"],
            "performed_on": updated["performed_on"],
            "set_index": updated["set_index"],
            "reps": updated["reps"],
            "weight": updated["weight"],
            "unit": updated["unit"],
            "rpe": updated["rpe"],
            "note": updated["note"],
        }

    def delete_session(self, session_id: int) -> dict[str, Any]:
        session = self.get_session(session_id)
        self.conn.execute("DELETE FROM workout_session WHERE id = ?", (session_id,))
        self.conn.commit()
        return {
            "deleted": True,
            "session_id": session_id,
            "removed_exercise_count": session["summary"]["exercise_count"],
            "removed_set_count": session["summary"]["set_count"],
        }

    def delete_exercise_from_session(self, session_id: int, exercise_name: str) -> dict[str, Any]:
        self._require_session(session_id)
        exercise = self.resolve_exercise(exercise_name)
        rows = self.conn.execute(
            """
            SELECT id
            FROM workout_set
            WHERE session_id = ? AND exercise_id = ?
            """,
            (session_id, exercise.id),
        ).fetchall()
        if not rows:
            raise ValueError(
                f"Exercise '{exercise.canonical_name}' not found in session {session_id}"
            )

        self.conn.execute(
            "DELETE FROM workout_set WHERE session_id = ? AND exercise_id = ?",
            (session_id, exercise.id),
        )
        remaining = self.conn.execute(
            "SELECT COUNT(*) AS count FROM workout_set WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if remaining["count"] == 0:
            self.conn.execute("DELETE FROM workout_session WHERE id = ?", (session_id,))
            self.conn.commit()
            return {
                "deleted_exercise": exercise.canonical_name,
                "session_id": session_id,
                "removed_set_count": len(rows),
                "session_deleted": True,
            }

        self.conn.commit()
        return {
            "deleted_exercise": exercise.canonical_name,
            "session_id": session_id,
            "removed_set_count": len(rows),
            "session_deleted": False,
            "session": self.get_session(session_id),
        }

    def get_exercise_history(self, exercise_name: str, limit: int = 10) -> dict[str, Any]:
        exercise = self.resolve_exercise(exercise_name)
        rows = self.conn.execute(
            """
            SELECT
                ws.id,
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
                    "id": row["id"],
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
