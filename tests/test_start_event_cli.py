"""Tests for the live event CLI boundary."""

from __future__ import annotations

from dataclasses import dataclass

import start_event as start_event_module


@dataclass(frozen=True)
class _FakeLiveEventResult:
    """Minimal live result used by CLI delegation tests."""

    def safe_summary(self) -> dict[str, object]:
        """Return counters expected by the live CLI logger."""

        return {
            "iterations_count": 1,
            "participants_count": 0,
            "local_artifacts_count": 0,
        }


def test_start_event_delegates_to_live_workflow(monkeypatch) -> None:
    calls: list[tuple[str, str | None, int, int]] = []

    def fake_run_live_event(form_id, cloud_event_folder, *, config):
        """Record CLI arguments and return a minimal live result."""

        calls.append(
            (
                form_id,
                cloud_event_folder,
                config.event_poll_seconds,
                config.form_poll_seconds,
            )
        )
        return _FakeLiveEventResult()

    monkeypatch.setattr(start_event_module, "configure_logging", lambda *, debug=False: None)
    monkeypatch.setattr(start_event_module, "run_live_event", fake_run_live_event)

    exit_code = start_event_module.main(
        [
            "form_1",
            "/event_name",
            "--event-poll-seconds",
            "30",
            "--form-poll-seconds",
            "5",
        ]
    )

    assert exit_code == 0
    assert calls == [("form_1", "/event_name", 30, 5)]


def test_start_event_allows_generated_cloud_event_folder(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []

    def fake_run_live_event(form_id, cloud_event_folder, *, config):
        """Record that the event folder path can be omitted."""

        calls.append((form_id, cloud_event_folder))
        return _FakeLiveEventResult()

    monkeypatch.setattr(start_event_module, "configure_logging", lambda *, debug=False: None)
    monkeypatch.setattr(start_event_module, "run_live_event", fake_run_live_event)

    exit_code = start_event_module.main(["form_1"])

    assert exit_code == 0
    assert calls == [("form_1", None)]
