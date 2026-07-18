from __future__ import annotations

from alphaforge.config import load_model_settings


def test_model_settings_use_generic_environment_names(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "API_KEY=file-key\nMODEL=file-model\nBASE_URL=https://file.invalid\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL", "runtime-model")
    settings = load_model_settings(env_file)
    assert settings.api_key == "file-key"
    assert settings.model == "runtime-model"
    assert settings.base_url == "https://file.invalid"
