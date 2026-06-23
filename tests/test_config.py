import pytest
import config


def test_get_api_key_returns_value(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
    assert config.get_api_key() == "test-key-123"


def test_get_api_key_missing_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        config.get_api_key()


def test_model_constant():
    assert config.GEMINI_MODEL == "gemini-2.0-flash"
