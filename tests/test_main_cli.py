"""Tests for the CLI boundary."""

from __future__ import annotations

from dataclasses import dataclass

import main as main_module


@dataclass(frozen=True)
class _FakeDistributionResult:
    """Minimal distribution result used by CLI delegation tests."""

    def safe_summary(self) -> dict[str, object]:
        """Return counters expected by the CLI logger."""

        return {
            "participants_count": 1,
            "local_artifacts_count": 0,
        }


def test_main_delegates_yandex_client_creation_to_workflow(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_run_distribution(event_folder, form_id, *, config):
        """Record CLI arguments and return a minimal workflow result."""

        calls.append((event_folder, form_id))
        return _FakeDistributionResult()

    monkeypatch.setattr(main_module, "configure_logging", lambda *, debug=False: None)
    monkeypatch.setattr(main_module, "run_distribution", fake_run_distribution)

    exit_code = main_module.main(["/event", "form_1"])

    assert exit_code == 0
    assert calls == [("/event", "form_1")]
