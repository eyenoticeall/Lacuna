"""Explicit global and scoped runtime configuration."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal, Self, TypedDict, Unpack

from lacuna.exceptions import ConfigurationError

ThreadCount = int | Literal["auto"]


def _thread_count_from_environment() -> ThreadCount:
    raw_value = os.getenv("LACUNA_NUM_THREADS", "auto").strip().lower()
    if raw_value == "auto":
        return "auto"
    try:
        return int(raw_value)
    except ValueError as error:
        message = "LACUNA_NUM_THREADS must be 'auto' or a positive integer"
        raise ConfigurationError(message) from error


@dataclass(frozen=True, slots=True)
class Config:
    """Runtime settings that affect execution and reproducibility."""

    threads: ThreadCount = "auto"
    seed: int | None = None
    memory_limit: str | None = None
    cache_dir: str | None = None
    log_level: str = "warning"

    def __post_init__(self) -> None:
        if self.threads != "auto" and self.threads < 1:
            raise ConfigurationError("threads must be 'auto' or a positive integer")
        if self.seed is not None and self.seed < 0:
            raise ConfigurationError("seed must be non-negative")
        if not self.log_level.strip():
            raise ConfigurationError("log_level must not be empty")

    @classmethod
    def from_environment(cls) -> Self:
        """Build configuration from Lacuna's documented environment variables."""

        return cls(
            threads=_thread_count_from_environment(),
            memory_limit=os.getenv("LACUNA_MEMORY_LIMIT"),
            cache_dir=os.getenv("LACUNA_CACHE_DIR"),
            log_level=os.getenv("LACUNA_LOG", "warning"),
        )


class _ConfigChanges(TypedDict, total=False):
    threads: ThreadCount
    seed: int | None
    memory_limit: str | None
    cache_dir: str | None
    log_level: str


_current_config: ContextVar[Config | None] = ContextVar("lacuna_config", default=None)


def get_config() -> Config:
    """Return the configuration active in the current execution context."""

    current = _current_config.get()
    if current is None:
        current = Config.from_environment()
        _current_config.set(current)
    return current


def _updated_config(**changes: Unpack[_ConfigChanges]) -> Config:
    current = get_config()
    return Config(
        threads=changes.get("threads", current.threads),
        seed=changes.get("seed", current.seed),
        memory_limit=changes.get("memory_limit", current.memory_limit),
        cache_dir=changes.get("cache_dir", current.cache_dir),
        log_level=changes.get("log_level", current.log_level),
    )


def configure(**changes: Unpack[_ConfigChanges]) -> Config:
    """Replace selected settings in the current execution context.

    Use :func:`config` when a temporary, automatically restored scope is safer.
    """

    updated = _updated_config(**changes)
    _current_config.set(updated)
    return updated


@contextmanager
def config(**changes: Unpack[_ConfigChanges]) -> Iterator[Config]:
    """Temporarily apply configuration within a ``with`` block."""

    updated = _updated_config(**changes)
    token = _current_config.set(updated)
    try:
        yield updated
    finally:
        _current_config.reset(token)
