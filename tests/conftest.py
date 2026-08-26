"""Repository-wide pytest policy for explicit optional-dependency skips."""

from __future__ import annotations

from typing import Any

import pytest

_SKIPPED: list[str] = []
_UNAPPROVED_SKIPS: list[str] = []


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--fail-on-skip",
        action="store_true",
        default=False,
        help="fail the suite when any test is skipped (used by full-extra CI)",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "optional_dependency(reason): test may skip in a core-only environment for the documented "
        "optional dependency",
    )
    _SKIPPED.clear()
    _UNAPPROVED_SKIPS.clear()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]) -> Any:
    outcome = yield
    report = outcome.get_result()
    if not report.skipped:
        return
    _SKIPPED.append(report.nodeid)
    marker = item.get_closest_marker("optional_dependency")
    reason = marker.kwargs.get("reason") if marker is not None else None
    if marker is None or not isinstance(reason, str) or not reason.strip():
        _UNAPPROVED_SKIPS.append(report.nodeid)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    del exitstatus
    fail_on_skip = bool(session.config.getoption("--fail-on-skip"))
    if not _UNAPPROVED_SKIPS and not (fail_on_skip and _SKIPPED):
        return
    terminal = session.config.pluginmanager.get_plugin("terminalreporter")
    if terminal is not None:
        heading = "unapproved skips" if _UNAPPROVED_SKIPS else "skips forbidden by --fail-on-skip"
        terminal.write_sep("=", heading)
        for nodeid in _UNAPPROVED_SKIPS or _SKIPPED:
            terminal.write_line(nodeid)
    session.exitstatus = pytest.ExitCode.TESTS_FAILED
