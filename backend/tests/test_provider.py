import sys
from types import SimpleNamespace

import pytest

from app.contracts import Analysis
from app.provider import Provider, ProviderFailure


def test_litellm_boundary_validates_and_retries(cfg, monkeypatch):
    cfg.llm_enabled, cfg.llm_model = True, "configured/service"
    calls = []

    def completion(**kw):
        calls.append(kw)
        content = "invalid" if len(calls) == 1 else '{"facts":[],"episodes":[],"dates":[]}'
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=completion))
    provider = Provider(cfg)
    assert isinstance(provider.analyze({"id": "one", "content": "Untrusted source text"}), Analysis)
    assert len(calls) == 2 and calls[0]["model"] == cfg.llm_model
    assert calls[0]["messages"][1]["role"] == "user" and calls[0]["timeout"] == 12


def test_invalid_model_output_is_not_manufactured(cfg, monkeypatch):
    cfg.llm_enabled, cfg.llm_model = True, "configured/service"
    calls = []

    def bad(**kw):
        calls.append(kw)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content='{"facts":[{"value":"unverified"}]}'))
            ]
        )

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=bad))
    with pytest.raises(ProviderFailure):
        Provider(cfg).analyze({"id": "x", "content": "data"})
    assert len(calls) == 2
