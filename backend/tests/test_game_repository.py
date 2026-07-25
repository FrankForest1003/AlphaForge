from __future__ import annotations

import sqlite3

import pytest

from app.repositories import SQLiteGameRepository


def completed_run(run_id: str, human_score: float, ai_score: float) -> dict:
    return {
        "run_id": run_id,
        "human": {"summary": {}},
        "candidates": [],
        "battle_analysis": {
            "judge": {
                "scorecards": [
                    {
                        "id": "human",
                        "score": human_score,
                        "summary": {"sharpe_ratio": 1.0},
                    }
                ]
            },
            "ai_champion": {
                "track": "Traditional",
                "score": ai_score,
                "summary": {"sharpe_ratio": 0.9},
            },
            "education_summary": {"risk_disclaimer": "historical only"},
        },
    }


def test_authentication_and_best_of_five_are_durable(tmp_path):
    repository = SQLiteGameRepository(tmp_path / "alphaforge.db")
    user = repository.create_user("alice_01", "correct-horse")
    assert repository.authenticate("ALICE_01", "correct-horse") == user
    assert repository.authenticate("alice_01", "wrong-password") is None

    token = repository.create_session(user["id"])
    assert repository.user_from_token(token) == user

    battle = repository.create_battle(user["id"], "Risk Budget Match")
    for number in range(1, 4):
        run_id = f"forge-round{number}"
        repository.attach_round(
            user_id=user["id"],
            battle_id=battle["id"],
            forge_run_id=run_id,
            settings={"symbols": ["A", "B", "C", "D", "E"]},
            human_strategy={"mode": "guided", "guided": {}},
        )
        repository.complete_round(completed_run(run_id, 80, 70))
        if number < 3:
            with pytest.raises(ValueError, match="Coach"):
                repository.validate_round_start(user["id"], battle["id"])
        repository.save_coach_memory(
            run_id,
            {
                "round_number": number,
                "round_summary": "AI-only evidence",
                "track_lessons": [],
                "overfitting_guard": "one change",
            },
        )
        if number == 1:
            with sqlite3.connect(tmp_path / "alphaforge.db") as connection:
                connection.execute(
                    "UPDATE battles SET contract_json = NULL WHERE id = ?",
                    (battle["id"],),
                )
            repository = SQLiteGameRepository(tmp_path / "alphaforge.db")
            assert repository.get_battle(user["id"], battle["id"])[
                "contract"
            ]["symbols"] == ["A", "B", "C", "D", "E"]
            with pytest.raises(ValueError, match="contract is frozen"):
                repository.attach_round(
                    user_id=user["id"],
                    battle_id=battle["id"],
                    forge_run_id="forge-invalid-contract",
                    settings={
                        "symbols": ["A", "B", "C", "D", "F"],
                    },
                    human_strategy={"mode": "guided", "guided": {}},
                )

    finished = repository.get_battle(user["id"], battle["id"])
    assert finished["state"] == "completed"
    assert finished["winner"] == "human"
    assert finished["human_wins"] == 3
    assert finished["round_count"] == 3
    assert finished["can_start_round"] is False
    assert len(finished["rounds"]) == 3
    assert finished["contract"]["symbols"] == ["A", "B", "C", "D", "E"]
    evidence = repository.completed_round_results(battle["id"])
    assert [item["round_number"] for item in evidence] == [1, 2, 3]
    assert evidence[0]["forge_run_id"] == "forge-round1"
    assert "battle_analysis" in evidence[0]["result"]

    repository.delete_battle(user["id"], battle["id"])
    with pytest.raises(ValueError, match="unknown battle"):
        repository.get_battle(user["id"], battle["id"])
