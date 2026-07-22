from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class SQLiteRepository:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS battles (
                    battle_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    contract_hash TEXT NOT NULL,
                    contract_json TEXT NOT NULL,
                    guided_strategy_json TEXT,
                    strategy_mode TEXT NOT NULL DEFAULT 'guided',
                    custom_code TEXT,
                    custom_code_hash TEXT,
                    code_validation_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS baseline_batches (
                    batch_id TEXT PRIMARY KEY,
                    battle_id TEXT NOT NULL REFERENCES battles(battle_id),
                    state TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS baseline_runs (
                    batch_id TEXT NOT NULL REFERENCES baseline_batches(batch_id),
                    strategy_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    family TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'baseline',
                    worker_run_id TEXT,
                    state TEXT NOT NULL,
                    result_json TEXT,
                    result_hash TEXT,
                    error TEXT,
                    PRIMARY KEY (batch_id, strategy_id)
                );

                CREATE INDEX IF NOT EXISTS idx_batches_battle_created
                ON baseline_batches(battle_id, created_at DESC);
                """
            )
            battle_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(battles)").fetchall()
            }
            if "guided_strategy_json" not in battle_columns:
                connection.execute(
                    "ALTER TABLE battles ADD COLUMN guided_strategy_json TEXT"
                )
            for column, definition in (
                ("strategy_mode", "TEXT NOT NULL DEFAULT 'guided'"),
                ("custom_code", "TEXT"),
                ("custom_code_hash", "TEXT"),
                ("code_validation_json", "TEXT"),
            ):
                if column not in battle_columns:
                    connection.execute(
                        f"ALTER TABLE battles ADD COLUMN {column} {definition}"
                    )
            run_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(baseline_runs)").fetchall()
            }
            if "role" not in run_columns:
                connection.execute(
                    "ALTER TABLE baseline_runs ADD COLUMN role TEXT NOT NULL DEFAULT 'baseline'"
                )

    def create_battle(self, record: dict[str, Any]) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO battles
                (battle_id, name, status, contract_hash, contract_json,
                 guided_strategy_json, strategy_mode, custom_code,
                 custom_code_hash, code_validation_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["battle_id"], record["name"], record["status"],
                    record["contract_hash"],
                    json.dumps(record["experiment_contract"], ensure_ascii=False),
                    json.dumps(record.get("guided_strategy"), ensure_ascii=False)
                    if record.get("guided_strategy") is not None else None,
                    record.get("strategy_mode", "guided"),
                    record.get("custom_code"),
                    record.get("custom_code_hash"),
                    json.dumps(record.get("code_validation"), ensure_ascii=False)
                    if record.get("code_validation") is not None else None,
                    record["created_at"],
                ),
            )

    def get_battle(self, battle_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM battles WHERE battle_id = ?", (battle_id,)
            ).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["experiment_contract"] = json.loads(record.pop("contract_json"))
        guided_json = record.pop("guided_strategy_json", None)
        record["guided_strategy"] = json.loads(guided_json) if guided_json else None
        if record.get("strategy_mode", "guided") == "guided" and record["guided_strategy"] is None:
            record["guided_strategy"] = {
                "template_id": "multi_horizon_momentum", "lookback_days": 126
            }
        validation_json = record.pop("code_validation_json", None)
        record["code_validation"] = json.loads(validation_json) if validation_json else None
        return record

    def update_code_validation(self, battle_id: str, validation: dict[str, Any]) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                "UPDATE battles SET code_validation_json = ? WHERE battle_id = ?",
                (json.dumps(validation, ensure_ascii=False), battle_id),
            )

    def create_batch(self, record: dict[str, Any], runs: list[dict[str, Any]]) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO baseline_batches
                (batch_id, battle_id, state, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record["batch_id"], record["battle_id"], record["state"],
                    record.get("error"), record["created_at"], record["updated_at"],
                ),
            )
            connection.executemany(
                """
                INSERT INTO baseline_runs
                (batch_id, strategy_id, display_name, family, role, worker_run_id,
                 state, result_json, result_hash, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        record["batch_id"], run["strategy_id"], run["display_name"],
                        run["family"], run.get("role", "baseline"),
                        run.get("worker_run_id"), run["state"], None, None,
                        run.get("error"),
                    )
                    for run in runs
                ],
            )

    def update_batch(self, batch_id: str, *, state: str, updated_at: str, error: str | None = None) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """UPDATE baseline_batches SET state = ?, updated_at = ?, error = ?
                   WHERE batch_id = ?""",
                (state, updated_at, error, batch_id),
            )

    def update_run(
        self,
        batch_id: str,
        strategy_id: str,
        *,
        state: str,
        worker_run_id: str | None = None,
        result: dict[str, Any] | None = None,
        result_hash: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                UPDATE baseline_runs
                SET state = ?, worker_run_id = COALESCE(?, worker_run_id),
                    result_json = COALESCE(?, result_json),
                    result_hash = COALESCE(?, result_hash), error = ?
                WHERE batch_id = ? AND strategy_id = ?
                """,
                (
                    state, worker_run_id,
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    result_hash, error, batch_id, strategy_id,
                ),
            )

    def get_batch(self, batch_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            batch = connection.execute(
                "SELECT * FROM baseline_batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()
            if batch is None:
                return None
            runs = connection.execute(
                "SELECT * FROM baseline_runs WHERE batch_id = ? ORDER BY rowid", (batch_id,)
            ).fetchall()
        record = dict(batch)
        record["runs"] = []
        for row in runs:
            item = dict(row)
            result_json = item.pop("result_json")
            item["result"] = json.loads(result_json) if result_json else None
            record["runs"].append(item)
        return record

    def latest_batch(self, battle_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT batch_id FROM baseline_batches
                WHERE battle_id = ? ORDER BY created_at DESC LIMIT 1
                """,
                (battle_id,),
            ).fetchone()
        return self.get_batch(row["batch_id"]) if row else None
