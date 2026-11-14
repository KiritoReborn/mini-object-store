"""Explicit isolation for A-only tests; production recovery tests do not opt in."""
import pytest


@pytest.fixture
def no_recovery_module(monkeypatch):
    from controller import main

    load_module = main._optional_module
    monkeypatch.setattr(main, "_optional_module", lambda name:
                        None if name == "controller.recovery" else load_module(name))
    return main
