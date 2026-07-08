"""Tests for Yandex Disk browser automation configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from yandex_disk import YandexDiskUiAccessGrantor, YandexDiskUiConfig, YandexDiskUiError


def test_folder_url_encodes_yandex_disk_folder_path() -> None:
    grantor = YandexDiskUiAccessGrantor(
        config=YandexDiskUiConfig(base_url="https://disk.yandex.ru")
    )

    assert (
        grantor.folder_url("/events/test event")
        == "https://disk.yandex.ru/client/disk/events/test%20event"
    )


def test_folder_url_rejects_relative_path() -> None:
    grantor = YandexDiskUiAccessGrantor(config=YandexDiskUiConfig())

    with pytest.raises(ValueError, match="absolute folder path"):
        grantor.folder_url("event")


def test_yandex_disk_ui_config_from_env(monkeypatch, tmp_path: Path) -> None:
    profile_dir = tmp_path / "browser-profile"
    monkeypatch.setenv("YANDEX_DISK_UI_PROFILE_DIR", str(profile_dir))
    monkeypatch.setenv("YANDEX_DISK_UI_HEADLESS", "true")
    monkeypatch.setenv("YANDEX_DISK_UI_TIMEOUT_MS", "1234")
    monkeypatch.setenv("YANDEX_DISK_UI_SLOW_MO_MS", "5")
    monkeypatch.setenv("YANDEX_DISK_UI_BASE_URL", "https://example.test")

    config = YandexDiskUiConfig.from_env()

    assert config.profile_dir == profile_dir
    assert config.headless is True
    assert config.timeout_ms == 1234
    assert config.slow_mo_ms == 5
    assert config.base_url == "https://example.test"


def test_yandex_disk_ui_config_repr_hides_profile_dir(tmp_path: Path) -> None:
    config = YandexDiskUiConfig(profile_dir=tmp_path / "private-profile")

    assert "private-profile" not in repr(config)


def test_auth_redirect_gets_explicit_safe_error() -> None:
    grantor = YandexDiskUiAccessGrantor(config=YandexDiskUiConfig())
    page = _FakeAuthPage()

    with pytest.raises(YandexDiskUiError) as exc_info:
        grantor._grant_write_access_on_page(page, "/event", "person@example.test")

    assert "not authenticated" in exc_info.value.safe_message()


class _FakeAuthPage:
    url = "https://passport.yandex.ru/pwl-yandex?cause=auth"
