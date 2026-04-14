"""Smoke tests for main.py entry point."""

import importlib


def test_main_module_imports():
    """Verify main module imports without error."""
    mod = importlib.import_module("main")
    assert hasattr(mod, "main")
    assert callable(mod.main)


def test_main_has_entry_point():
    """Verify main module has the expected async main function."""
    from main import main
    import asyncio

    assert asyncio.iscoroutinefunction(main)
