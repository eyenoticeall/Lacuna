from __future__ import annotations

import pytest

import lacuna as lc
from lacuna.exceptions import ConfigurationError


def test_scoped_config_is_restored() -> None:
    original = lc.get_config()

    with lc.config(threads=2, seed=42) as active:
        assert active.threads == 2
        assert lc.get_config().seed == 42

    assert lc.get_config() == original


def test_config_rejects_invalid_threads() -> None:
    with pytest.raises(ConfigurationError, match="positive integer"):
        lc.Config(threads=0)


def test_configure_updates_the_current_context() -> None:
    original = lc.get_config()
    try:
        updated = lc.configure(log_level="info")
        assert updated.log_level == "info"
        assert lc.get_config() == updated
    finally:
        lc.configure(
            threads=original.threads,
            seed=original.seed,
            memory_limit=original.memory_limit,
            cache_dir=original.cache_dir,
            log_level=original.log_level,
        )
