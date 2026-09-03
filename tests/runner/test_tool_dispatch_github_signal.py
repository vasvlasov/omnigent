"""Unit tests for the runner's GitHub-activity invalidation signal.

Covers the ``sys_os_shell`` side of the GitHub auto-update: after a shell
command that pushes to a remote or mutates a PR, the runner publishes a
throttled ``session.github.invalidated`` so the web refetches the session's
GitHub context without waiting on the panel's poll.
"""

from __future__ import annotations

from typing import Any

from omnigent.runner import tool_dispatch
from omnigent.runner.tool_dispatch import (
    _maybe_signal_github_activity,
    _shell_command_from_arguments,
)


def test_shell_command_from_arguments_extracts_command() -> None:
    assert _shell_command_from_arguments('{"command": "git push"}') == "git push"


def test_shell_command_from_arguments_tolerates_bad_shapes() -> None:
    assert _shell_command_from_arguments("not json") is None
    assert _shell_command_from_arguments("[1, 2, 3]") is None  # not an object
    assert _shell_command_from_arguments("{}") is None  # no command
    assert _shell_command_from_arguments('{"command": 5}') is None  # wrong type


def _recorder() -> tuple[list[tuple[str, dict[str, Any]]], Any]:
    events: list[tuple[str, dict[str, Any]]] = []

    def publish(conversation_id: str, event: dict[str, Any]) -> None:
        events.append((conversation_id, event))

    return events, publish


def test_signal_published_on_push(monkeypatch: Any) -> None:
    """A ``git push`` publishes a github-invalidated event for the session."""
    monkeypatch.setattr(tool_dispatch, "_github_activity_last_signal", {})
    events, publish = _recorder()
    _maybe_signal_github_activity("conv_1", '{"command": "git push"}', publish, now=100.0)
    assert events == [("conv_1", {"type": "session.github.invalidated", "session_id": "conv_1"})]


def test_no_signal_on_read_only_command(monkeypatch: Any) -> None:
    """A non-remote-mutating command (``git status``) publishes nothing."""
    monkeypatch.setattr(tool_dispatch, "_github_activity_last_signal", {})
    events, publish = _recorder()
    _maybe_signal_github_activity("conv_1", '{"command": "git status"}', publish, now=100.0)
    assert events == []


def test_signal_is_throttled_then_refires(monkeypatch: Any) -> None:
    """A burst within the throttle window collapses to one signal; a later push refires."""
    monkeypatch.setattr(tool_dispatch, "_github_activity_last_signal", {})
    events, publish = _recorder()
    args = '{"command": "git push"}'
    _maybe_signal_github_activity("conv_1", args, publish, now=100.0)
    # Second push well within the throttle window — coalesced away.
    _maybe_signal_github_activity("conv_1", args, publish, now=100.1)
    assert len(events) == 1
    # Past the window — refires.
    _maybe_signal_github_activity(
        "conv_1",
        args,
        publish,
        now=100.0 + tool_dispatch._GITHUB_ACTIVITY_SIGNAL_THROTTLE_S + 0.01,
    )
    assert len(events) == 2


def test_no_op_without_session_or_publisher(monkeypatch: Any) -> None:
    """Missing conversation id or publisher is a safe no-op."""
    monkeypatch.setattr(tool_dispatch, "_github_activity_last_signal", {})
    events, publish = _recorder()
    _maybe_signal_github_activity(None, '{"command": "git push"}', publish, now=100.0)
    _maybe_signal_github_activity("conv_1", '{"command": "git push"}', None, now=100.0)
    assert events == []
