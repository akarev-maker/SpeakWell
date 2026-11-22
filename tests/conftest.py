import pytest

import storage


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Every test gets its own empty database file."""
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "test.db"))
    storage._initialized.clear()
    yield
    storage._initialized.clear()


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


class FakeResponse:
    def __init__(self, text, usage=None):
        self.text = text
        self.usage_metadata = usage


class FakeModels:
    """Stands in for client.models: returns queued responses per model name."""

    def __init__(self, script):
        self.script = script  # model -> list of (text | Exception)
        self.calls = []

    def generate_content(self, model, contents, config=None):
        self.calls.append(model)
        queue = self.script.get(model, [])
        if not queue:
            raise AssertionError(f"unexpected call to {model}")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResponse(item)


class FakeClient:
    def __init__(self, script):
        self.models = FakeModels(script)


@pytest.fixture
def fake_gemini(monkeypatch):
    """Install a scripted fake Gemini client. Usage: fake_gemini({model: [json, ...]})."""
    import models

    holder = {}

    def install(script):
        holder["client"] = FakeClient(script)
        monkeypatch.setattr(models, "client", lambda timeout_s, api_version="": holder["client"])
        return holder["client"]

    return install
