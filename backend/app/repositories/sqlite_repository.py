from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _password_hash(password: str, salt: bytes | None = None) -> tuple[str, str]:
    actual_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        actual_salt,
        210_000,
    )
    return actual_salt.hex(), digest.hex()


class SQLiteGameRepository:
    """Durable users, sessions, best-of-five battles, and round evidence."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS battles (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    state TEXT NOT NULL,
                    human_wins INTEGER NOT NULL DEFAULT 0,
                    ai_wins INTEGER NOT NULL DEFAULT 0,
                    round_count INTEGER NOT NULL DEFAULT 0,
                    winner TEXT,
                    contract_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS battle_rounds (
                    id TEXT PRIMARY KEY,
                    battle_id TEXT NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
                    round_number INTEGER NOT NULL,
                    forge_run_id TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL,
                    winner TEXT,
                    human_score REAL,
                    ai_score REAL,
                    ai_champion_track TEXT,
                    settings_json TEXT NOT NULL,
                    human_strategy_json TEXT NOT NULL,
                    result_json TEXT,
                    education_json TEXT,
                    coach_state TEXT NOT NULL DEFAULT 'waiting',
                    coach_memory_json TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    UNIQUE(battle_id, round_number)
                );
                CREATE INDEX IF NOT EXISTS idx_battles_user
                    ON battles(user_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_rounds_battle
                    ON battle_rounds(battle_id, round_number);
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(battles)").fetchall()
            }
            if "contract_json" not in columns:
                connection.execute(
                    "ALTER TABLE battles ADD COLUMN contract_json TEXT"
                )
            connection.execute(
                """
                UPDATE battles
                SET contract_json = (
                    SELECT battle_rounds.settings_json
                    FROM battle_rounds
                    WHERE battle_rounds.battle_id = battles.id
                    ORDER BY battle_rounds.round_number
                    LIMIT 1
                )
                WHERE contract_json IS NULL
                  AND EXISTS (
                    SELECT 1 FROM battle_rounds
                    WHERE battle_rounds.battle_id = battles.id
                  )
                """
            )
            connection.execute(
                """
                UPDATE battle_rounds
                SET state = 'failed',
                    result_json = ?,
                    completed_at = ?
                WHERE state = 'running'
                """,
                (
                    _json(
                        {
                            "error": (
                                "Backend restarted before this round completed; "
                                "start a new round to continue the battle."
                            )
                        }
                    ),
                    _utc_now(),
                ),
            )

    def create_user(self, username: str, password: str) -> dict[str, Any]:
        user_id = f"user-{uuid.uuid4().hex[:16]}"
        salt, digest = _password_hash(password)
        with self._connection() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO users(id, username, password_salt, password_hash, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, username, salt, digest, _utc_now()),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("username is already registered") from exc
        return {"id": user_id, "username": username}

    def authenticate(self, username: str, password: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
                (username,),
            ).fetchone()
        if row is None:
            return None
        _, digest = _password_hash(password, bytes.fromhex(row["password_salt"]))
        if not hmac.compare_digest(digest, row["password_hash"]):
            return None
        return {"id": row["id"], "username": row["username"]}

    def create_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO sessions(token_hash, user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    token_hash,
                    user_id,
                    now.isoformat(),
                    (now + timedelta(days=30)).isoformat(),
                ),
            )
        return token

    def user_from_token(self, token: str) -> dict[str, Any] | None:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT users.id, users.username, sessions.expires_at
                FROM sessions JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
        if row is None:
            return None
        if datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
            return None
        return {"id": row["id"], "username": row["username"]}

    def revoke_session(self, token: str) -> None:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._connection() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                (token_hash,),
            )

    def create_battle(self, user_id: str, name: str) -> dict[str, Any]:
        battle_id = f"battle-{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO battles(
                    id, user_id, name, state, human_wins, ai_wins,
                    round_count, created_at, updated_at
                ) VALUES (?, ?, ?, 'active', 0, 0, 0, ?, ?)
                """,
                (battle_id, user_id, name, now, now),
            )
        return self.get_battle(user_id, battle_id)

    def list_battles(self, user_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM battles WHERE user_id = ?
                ORDER BY updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [self._battle_row(row, include_rounds=False) for row in rows]

    def get_battle(self, user_id: str, battle_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM battles WHERE id = ? AND user_id = ?",
                (battle_id, user_id),
            ).fetchone()
            if row is None:
                raise ValueError("unknown battle")
            rounds = connection.execute(
                """
                SELECT * FROM battle_rounds WHERE battle_id = ?
                ORDER BY round_number
                """,
                (battle_id,),
            ).fetchall()
        battle = self._battle_row(row, include_rounds=True)
        battle["rounds"] = [self._round_row(item) for item in rounds]
        if battle["rounds"]:
            latest = battle["rounds"][-1]
            battle["can_start_round"] = bool(
                battle["can_start_round"]
                and latest["state"] in {"completed", "failed"}
                and (
                    latest["state"] == "failed"
                    or latest["coach_state"] in {"completed", "fallback"}
                )
            )
        return battle

    @staticmethod
    def _battle_row(
        row: sqlite3.Row,
        *,
        include_rounds: bool,
    ) -> dict[str, Any]:
        result = {
            "id": row["id"],
            "name": row["name"],
            "state": row["state"],
            "human_wins": row["human_wins"],
            "ai_wins": row["ai_wins"],
            "round_count": row["round_count"],
            "winner": row["winner"],
            "contract": _decode(row["contract_json"], None),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "wins_needed": max(0, 3 - max(row["human_wins"], row["ai_wins"])),
            "next_round": min(5, row["round_count"] + 1),
            "can_start_round": (
                row["state"] == "active" and row["round_count"] < 5
            ),
        }
        if include_rounds:
            result["rounds"] = []
        return result

    @staticmethod
    def _round_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "battle_id": row["battle_id"],
            "round_number": row["round_number"],
            "forge_run_id": row["forge_run_id"],
            "state": row["state"],
            "winner": row["winner"],
            "human_score": row["human_score"],
            "ai_score": row["ai_score"],
            "ai_champion_track": row["ai_champion_track"],
            "settings": _decode(row["settings_json"], {}),
            "human_strategy": _decode(row["human_strategy_json"], {}),
            "result": _decode(row["result_json"], {}),
            "education": _decode(row["education_json"], {}),
            "coach_state": row["coach_state"],
            "coach_memory": _decode(row["coach_memory_json"], None),
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
        }

    def validate_round_start(self, user_id: str, battle_id: str) -> int:
        battle = self.get_battle(user_id, battle_id)
        if battle["state"] != "active" or battle["round_count"] >= 5:
            raise ValueError("battle is already complete")
        if battle["rounds"] and battle["rounds"][-1]["state"] not in {
            "completed",
            "failed",
        }:
            raise ValueError("the previous round is still running")
        if (
            battle["rounds"]
            and battle["rounds"][-1]["state"] == "completed"
            and battle["rounds"][-1]["coach_state"]
            not in {"completed", "fallback"}
        ):
            raise ValueError("AI Coach is still learning from the previous round")
        return battle["round_count"] + 1

    def attach_round(
        self,
        *,
        user_id: str,
        battle_id: str,
        forge_run_id: str,
        settings: dict[str, Any],
        human_strategy: dict[str, Any],
    ) -> dict[str, Any]:
        round_number = self.validate_round_start(user_id, battle_id)
        battle = self.get_battle(user_id, battle_id)
        frozen_contract = battle.get("contract")
        if frozen_contract is not None and frozen_contract != settings:
            raise ValueError(
                "battle contract is frozen after Round 1; stocks and backtest "
                "settings cannot change"
            )
        round_id = f"round-{uuid.uuid4().hex[:16]}"
        now = _utc_now()
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO battle_rounds(
                        id, battle_id, round_number, forge_run_id, state,
                        settings_json, human_strategy_json, created_at
                    ) VALUES (?, ?, ?, ?, 'running', ?, ?, ?)
                    """,
                    (
                        round_id,
                        battle_id,
                        round_number,
                        forge_run_id,
                        _json(settings),
                        _json(human_strategy),
                        now,
                    ),
                )
                if frozen_contract is None:
                    connection.execute(
                        """
                        UPDATE battles SET contract_json = ?
                        WHERE id = ? AND user_id = ? AND contract_json IS NULL
                        """,
                        (_json(settings), battle_id, user_id),
                    )
                connection.execute(
                    """
                    UPDATE battles SET round_count = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (round_number, now, battle_id, user_id),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("a round is already running for this battle") from exc
        return self.get_battle(user_id, battle_id)["rounds"][-1]

    def delete_battle(self, user_id: str, battle_id: str) -> None:
        battle = self.get_battle(user_id, battle_id)
        if battle["rounds"] and battle["rounds"][-1]["state"] == "running":
            raise ValueError("cannot delete a battle while its round is running")
        with self._connection() as connection:
            deleted = connection.execute(
                "DELETE FROM battles WHERE id = ? AND user_id = ?",
                (battle_id, user_id),
            ).rowcount
        if deleted != 1:
            raise ValueError("unknown battle")

    @staticmethod
    def _decisive_winner(run: dict[str, Any]) -> tuple[str, float, float, str | None]:
        analysis = run.get("battle_analysis") or {}
        cards = (analysis.get("judge") or {}).get("scorecards") or []
        human = next((item for item in cards if item.get("id") == "human"), {})
        ai = analysis.get("ai_champion") or {}
        human_score = float(human.get("score") or 0.0)
        ai_score = float(ai.get("score") or 0.0)
        if human_score > ai_score:
            winner = "human"
        elif ai_score > human_score:
            winner = "ai"
        else:
            human_sharpe = float((human.get("summary") or {}).get("sharpe_ratio") or 0)
            ai_sharpe = float((ai.get("summary") or {}).get("sharpe_ratio") or 0)
            winner = "human" if human_sharpe >= ai_sharpe else "ai"
        return winner, human_score, ai_score, ai.get("track")

    def complete_round(self, run: dict[str, Any]) -> dict[str, Any] | None:
        run_id = run.get("run_id")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM battle_rounds WHERE forge_run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            battle = connection.execute(
                "SELECT * FROM battles WHERE id = ?",
                (row["battle_id"],),
            ).fetchone()
            if battle is None:
                return None
            winner, human_score, ai_score, track = self._decisive_winner(run)
            human_wins = battle["human_wins"] + (1 if winner == "human" else 0)
            ai_wins = battle["ai_wins"] + (1 if winner == "ai" else 0)
            finished = human_wins >= 3 or ai_wins >= 3 or row["round_number"] >= 5
            battle_winner = None
            if finished:
                battle_winner = "human" if human_wins > ai_wins else "ai"
            now = _utc_now()
            education = (
                (run.get("battle_analysis") or {}).get("education_summary") or {}
            )
            connection.execute(
                """
                UPDATE battle_rounds SET
                    state = 'completed', winner = ?, human_score = ?, ai_score = ?,
                    ai_champion_track = ?, result_json = ?, education_json = ?,
                    coach_state = 'pending', completed_at = ?
                WHERE forge_run_id = ?
                """,
                (
                    winner,
                    human_score,
                    ai_score,
                    track,
                    _json(
                        {
                            "baselines": run.get("baselines"),
                            "human": run.get("human"),
                            "candidates": run.get("candidates"),
                            "battle_analysis": run.get("battle_analysis"),
                            "robustness": run.get("robustness"),
                        }
                    ),
                    _json(education),
                    now,
                    run_id,
                ),
            )
            connection.execute(
                """
                UPDATE battles SET
                    state = ?, human_wins = ?, ai_wins = ?, winner = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    "completed" if finished else "active",
                    human_wins,
                    ai_wins,
                    battle_winner,
                    now,
                    row["battle_id"],
                ),
            )
        return {
            "battle_id": row["battle_id"],
            "round_id": row["id"],
            "round_number": row["round_number"],
            "winner": winner,
        }

    def fail_round(self, run_id: str, error: str) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE battle_rounds
                SET state = 'failed', result_json = ?, completed_at = ?
                WHERE forge_run_id = ?
                """,
                (_json({"error": error}), _utc_now(), run_id),
            )

    def latest_coach_memory(self, battle_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT coach_memory_json FROM battle_rounds
                WHERE battle_id = ? AND coach_memory_json IS NOT NULL
                ORDER BY round_number DESC LIMIT 1
                """,
                (battle_id,),
            ).fetchone()
        return _decode(row["coach_memory_json"], None) if row else None

    def completed_round_results(self, battle_id: str) -> list[dict[str, Any]]:
        """Return durable evidence from every completed round in one battle."""

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT round_number, forge_run_id, result_json
                FROM battle_rounds
                WHERE battle_id = ? AND state = 'completed'
                ORDER BY round_number
                """,
                (battle_id,),
            ).fetchall()
        return [
            {
                "round_number": row["round_number"],
                "forge_run_id": row["forge_run_id"],
                "result": _decode(row["result_json"], {}),
            }
            for row in rows
        ]

    def save_coach_memory(
        self,
        run_id: str,
        memory: dict[str, Any],
        *,
        state: str = "completed",
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE battle_rounds
                SET coach_state = ?, coach_memory_json = ?
                WHERE forge_run_id = ?
                """,
                (state, _json(memory), run_id),
            )

    def update_round_education(
        self,
        run_id: str,
        education: dict[str, Any],
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE battle_rounds SET education_json = ?
                WHERE forge_run_id = ?
                """,
                (_json(education), run_id),
            )

    def restore_run(self, run_id: str) -> dict[str, Any] | None:
        """Reconstruct a Forge response from one durable battle round."""

        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT battle_rounds.*, battles.user_id
                FROM battle_rounds
                JOIN battles ON battles.id = battle_rounds.battle_id
                WHERE battle_rounds.forge_run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        result = _decode(row["result_json"], {})
        for candidate in result.get("candidates") or []:
            retained_run_id = candidate.get("retained_from_run_id")
            if (
                candidate.get("selection_origin") != "prior_round_incumbent"
                or candidate.get("champion_iterations")
                or not retained_run_id
            ):
                continue
            visited: set[str] = set()
            while retained_run_id and retained_run_id not in visited:
                visited.add(retained_run_id)
                with self._connection() as connection:
                    retained_row = connection.execute(
                        """
                        SELECT result_json FROM battle_rounds
                        WHERE forge_run_id = ? AND state = 'completed'
                        """,
                        (retained_run_id,),
                    ).fetchone()
                retained_result = (
                    _decode(retained_row["result_json"], {})
                    if retained_row
                    else {}
                )
                retained_candidate = next(
                    (
                        item
                        for item in retained_result.get("candidates") or []
                        if item.get("track") == candidate.get("track")
                    ),
                    None,
                )
                if not retained_candidate:
                    break
                champion_iterations = retained_candidate.get(
                    "champion_iterations"
                )
                if champion_iterations:
                    candidate["champion_iterations"] = champion_iterations
                    candidate["champion_best_iteration"] = (
                        retained_candidate.get("champion_best_iteration")
                        or retained_candidate.get("best_iteration")
                    )
                    break
                if (
                    retained_candidate.get("selection_origin")
                    == "prior_round_incumbent"
                    and retained_candidate.get("retained_from_run_id")
                ):
                    retained_run_id = retained_candidate[
                        "retained_from_run_id"
                    ]
                    continue
                candidate["champion_iterations"] = (
                    retained_candidate.get("iterations") or []
                )
                candidate["champion_best_iteration"] = (
                    retained_candidate.get("best_iteration")
                )
                break
        analysis = result.get("battle_analysis") or {}
        education = _decode(row["education_json"], {})
        if analysis and education:
            analysis["education_summary"] = education
        baselines = result.get("baselines") or []
        if not baselines:
            scorecards = (analysis.get("judge") or {}).get("scorecards") or []
            baselines = [
                {
                    "name": card.get("label"),
                    "family": card.get("track") or "Reference",
                    "state": (
                        "completed" if card.get("eligible") else "failed"
                    ),
                    "worker_run_id": None,
                    "summary": card.get("summary") or {},
                    "analysis": {
                        "statistics": card.get("analysis_statistics") or {}
                    },
                    "behavior_evidence": {},
                    "error": None,
                    "restored_with_data_gaps": True,
                }
                for card in scorecards
                if card.get("owner") == "baseline"
            ]
        state = (
            "completed"
            if row["state"] == "completed"
            else "failed"
        )
        stored_error = _decode(row["result_json"], {}).get("error")
        return {
            "run_id": run_id,
            "state": state,
            "stage": "Restored from SQLite",
            "settings": _decode(row["settings_json"], {}),
            "baselines": baselines,
            "human": result.get("human") or {
                "state": "failed",
                "summary": {},
                "analysis": {},
                "behavior_evidence": {},
                "error": stored_error or "Run was interrupted before completion",
            },
            "candidates": result.get("candidates") or [],
            "created_at": row["created_at"],
            "updated_at": row["completed_at"] or row["created_at"],
            "error": stored_error,
            "battle_analysis": analysis or None,
            "robustness": result.get("robustness"),
            "battle_id": row["battle_id"],
            "round_number": row["round_number"],
            "user_id": row["user_id"],
            "restored": True,
            "restored_with_data_gaps": not bool(result.get("baselines")),
        }
