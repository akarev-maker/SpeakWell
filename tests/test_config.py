import pytest
import config


def test_get_api_key_returns_value(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
    assert config.get_api_key() == "test-key-123"


def test_get_api_key_missing_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        config.get_api_key()


def test_model_default(monkeypatch):
    import importlib
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    try:
        importlib.reload(config)
        assert config.GEMINI_MODEL == "gemini-3.1-flash-lite"
    finally:
        importlib.reload(config)


def test_model_env_override(monkeypatch):
    import importlib
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    try:
        importlib.reload(config)
        assert config.GEMINI_MODEL == "gemini-2.5-flash"
    finally:
        monkeypatch.delenv("GEMINI_MODEL", raising=False)
        importlib.reload(config)


def test_retired_2_0_model_raises(monkeypatch):
    import importlib
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.0-flash")
    try:
        with pytest.raises(RuntimeError, match="retired"):
            importlib.reload(config)
    finally:
        monkeypatch.delenv("GEMINI_MODEL", raising=False)
        importlib.reload(config)


def test_retired_1_5_model_raises(monkeypatch):
    import importlib
    monkeypatch.setenv("GEMINI_MODEL", "gemini-1.5-flash")
    try:
        with pytest.raises(RuntimeError, match="audio-capable"):
            importlib.reload(config)
    finally:
        monkeypatch.delenv("GEMINI_MODEL", raising=False)
        importlib.reload(config)
