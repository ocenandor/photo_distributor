"""Browser automation for Yandex Disk shared-folder access."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote


DEFAULT_PROFILE_DIR = Path("data/browser/yandex_disk_ui")
DEFAULT_DIAGNOSTICS_DIR = Path("data/browser/yandex_disk_ui_diagnostics")
DEFAULT_TIMEOUT_MS = 60_000
DEFAULT_SLOW_MO_MS = 150
DEFAULT_BASE_URL = "https://disk.yandex.ru"
MENU_SETTLE_MS = 300
AUTH_URL_MARKERS = ("passport.yandex.", "oauth.yandex.")
MORE_MENU_PATTERN = (
    r"\u0415\u0449\u0451|\u0415\u0449\u0435|"
    r"\u0414\u0435\u0439\u0441\u0442\u0432\u0438\u044f|More|Actions"
)
CONFIGURE_ACCESS_PATTERN = (
    r"\u041d\u0430\u0441\u0442\u0440\u043e\u0438\u0442\u044c "
    r"\u0434\u043e\u0441\u0442\u0443\u043f|"
    r"\u041e\u0431\u0449\u0438\u0439 \u0434\u043e\u0441\u0442\u0443\u043f|"
    r"\u0414\u043e\u0441\u0442\u0443\u043f|Configure access|Manage access"
)
EMAIL_INPUT_TEXT_PATTERN = "\u043f\u043e\u0447\u0442"
READ_ACCESS_PATTERN = (
    r"\u041f\u0440\u043e\u0441\u043c\u043e\u0442\u0440|"
    r"\u0427\u0442\u0435\u043d\u0438\u0435|Read|View"
)
WRITE_ACCESS_PATTERN = (
    r"\u0420\u0435\u0434\u0430\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u0435|"
    r"\u041c\u043e\u0436\u043d\u043e "
    r"\u0440\u0435\u0434\u0430\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u0442\u044c|"
    r"\u041f\u043e\u043b\u043d\u044b\u0439 \u0434\u043e\u0441\u0442\u0443\u043f|"
    r"Write|Edit"
)
SUBMIT_INVITE_PATTERN = (
    r"\u041f\u0440\u0438\u0433\u043b\u0430\u0441\u0438\u0442\u044c|"
    r"\u041e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c|"
    r"\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c|"
    r"\u0413\u043e\u0442\u043e\u0432\u043e|Invite|Send|Save|Done"
)


class YandexDiskUiError(RuntimeError):
    """Error raised by Yandex Disk UI automation.

    Args:
        message: Internal diagnostic message.
        safe_message: Optional path/email-safe message for CLI logs.
    """

    def __init__(self, message: str, *, safe_message: str | None = None) -> None:
        super().__init__(message)
        self._safe_message = safe_message or message

    def safe_message(self) -> str:
        """Return a safe diagnostic message for logs."""

        return self._safe_message


@dataclass(frozen=True, repr=False)
class YandexDiskUiConfig:
    """Configuration for browser-based Yandex Disk automation.

    Attributes:
        profile_dir: Local persistent browser profile used to keep the Yandex
            login session.
        diagnostics_dir: Local private directory where the latest failed UI
            page screenshot and HTML snapshot are saved.
        headless: Whether the automation browser runs without a visible window.
        timeout_ms: Playwright timeout for navigation and UI actions.
        slow_mo_ms: Delay between browser actions, useful for brittle UI flows.
        base_url: Yandex Disk web base URL.
    """

    profile_dir: Path = DEFAULT_PROFILE_DIR
    diagnostics_dir: Path = DEFAULT_DIAGNOSTICS_DIR
    headless: bool = False
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    slow_mo_ms: int = DEFAULT_SLOW_MO_MS
    base_url: str = DEFAULT_BASE_URL

    @classmethod
    def from_env(cls) -> "YandexDiskUiConfig":
        """Build browser automation config from environment variables.

        Reads:
            `YANDEX_DISK_UI_PROFILE_DIR`, `YANDEX_DISK_UI_DIAGNOSTICS_DIR`,
            `YANDEX_DISK_UI_HEADLESS`, `YANDEX_DISK_UI_TIMEOUT_MS`,
            `YANDEX_DISK_UI_SLOW_MO_MS`, and `YANDEX_DISK_UI_BASE_URL`.

        Returns:
            UI automation config with default values for missing environment
            variables.
        """

        return cls(
            profile_dir=Path(os.environ.get("YANDEX_DISK_UI_PROFILE_DIR", DEFAULT_PROFILE_DIR)),
            diagnostics_dir=Path(
                os.environ.get("YANDEX_DISK_UI_DIAGNOSTICS_DIR", DEFAULT_DIAGNOSTICS_DIR)
            ),
            headless=_env_bool("YANDEX_DISK_UI_HEADLESS", default=False),
            timeout_ms=_env_int("YANDEX_DISK_UI_TIMEOUT_MS", DEFAULT_TIMEOUT_MS),
            slow_mo_ms=_env_int("YANDEX_DISK_UI_SLOW_MO_MS", DEFAULT_SLOW_MO_MS),
            base_url=os.environ.get("YANDEX_DISK_UI_BASE_URL", DEFAULT_BASE_URL),
        )

    def safe_summary(self) -> dict[str, object]:
        """Return config values safe for logs."""

        return {
            "headless": self.headless,
            "timeout_ms": self.timeout_ms,
            "slow_mo_ms": self.slow_mo_ms,
            "base_url": self.base_url,
        }

    def __repr__(self) -> str:
        """Return a path-safe diagnostic representation."""

        return f"YandexDiskUiConfig({self.safe_summary()!r})"


@dataclass(frozen=True)
class YandexDiskUiAccessGrantor:
    """Grant write access to a Yandex Disk folder through browser UI.

    Attributes:
        config: Browser automation configuration.
    """

    config: YandexDiskUiConfig

    @classmethod
    def from_env(cls) -> "YandexDiskUiAccessGrantor":
        """Create an access grantor from environment variables."""

        return cls(config=YandexDiskUiConfig.from_env())

    def folder_url(self, folder_path: str) -> str:
        """Return the Yandex Disk browser URL for a canonical folder path.

        Args:
            folder_path: Canonical Yandex Disk folder path, for example
                `/event_001`.

        Returns:
            Browser URL opened by the UI automation.

        Raises:
            ValueError: If `folder_path` is not an absolute folder path.
        """

        if not folder_path.startswith("/") or folder_path == "/":
            raise ValueError("Yandex Disk UI folder path must be an absolute folder path.")
        encoded_path = "/".join(quote(part) for part in folder_path.strip("/").split("/"))
        return f"{self.config.base_url.rstrip('/')}/client/disk/{encoded_path}"

    def grant_write_access(self, folder_path: str, email: str) -> None:
        """Grant write access to one participant through the Yandex Disk UI.

        Args:
            folder_path: Canonical Yandex Disk folder path.
            email: Participant email from the accepted form answer.

        Raises:
            YandexDiskUiError: If Playwright is not installed or the UI flow
                cannot complete.

        Side effects:
            Opens a persistent browser profile, uses the current Yandex login
            session, and changes sharing settings in the Yandex Disk UI.
        """

        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise YandexDiskUiError(
                "Playwright is required for Yandex Disk UI automation.",
                safe_message=(
                    "Yandex Disk UI automation dependency is not installed. "
                    "Install the optional ui dependency and Playwright browser."
                ),
            ) from exc

        self.config.profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.config.profile_dir),
                    headless=self.config.headless,
                    slow_mo=self.config.slow_mo_ms,
                )
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    try:
                        page.goto(
                            self.folder_url(folder_path),
                            wait_until="domcontentloaded",
                            timeout=self.config.timeout_ms,
                        )
                        self._grant_write_access_on_page(page, folder_path, email)
                    except Exception as exc:
                        self._save_failure_diagnostics(page, exc)
                        raise
                finally:
                    context.close()
        except PlaywrightTimeoutError as exc:
            raise YandexDiskUiError(
                "Yandex Disk UI access grant timed out.",
                safe_message="Yandex Disk UI access grant timed out.",
            ) from exc
        except YandexDiskUiError:
            raise
        except Exception as exc:
            raise YandexDiskUiError(
                "Yandex Disk UI access grant failed.",
                safe_message="Yandex Disk UI access grant failed.",
            ) from exc

    def _grant_write_access_on_page(self, page: Any, folder_path: str, email: str) -> None:
        """Run the current best-effort Yandex Disk sharing UI sequence."""

        self._raise_if_auth_required(page)
        self._open_folder_access_dialog(page, _folder_name(folder_path))
        self._raise_if_auth_required(page)
        self._select_write_access(page)
        self._fill_first_visible(
            page,
            (
                "input[type='email']",
                "input[placeholder*='email' i]",
                f"input[placeholder*='{EMAIL_INPUT_TEXT_PATTERN}' i]",
                "input[aria-label*='email' i]",
                f"input[aria-label*='{EMAIL_INPUT_TEXT_PATTERN}' i]",
                "input[type='text']",
                "[role='textbox']",
                "textarea",
                "[contenteditable='true']",
            ),
            email,
            "Could not find Yandex Disk sharing email input.",
        )
        self._select_suggested_user(page, email)
        self._click_named_button(
            page,
            SUBMIT_INVITE_PATTERN,
            "Could not submit Yandex Disk sharing invite.",
        )

    def _open_folder_access_dialog(self, page: Any, folder_name: str) -> None:
        """Open the current folder's access dialog from the header menu."""

        self._click_folder_header_menu(page, folder_name)
        page.wait_for_timeout(MENU_SETTLE_MS)
        self._click_named_button(
            page,
            CONFIGURE_ACCESS_PATTERN,
            "Could not open Yandex Disk sharing dialog.",
        )

    def _raise_if_auth_required(self, page: Any) -> None:
        """Fail early when the persistent browser profile is not logged in."""

        current_url = str(getattr(page, "url", "")).lower()
        if any(marker in current_url for marker in AUTH_URL_MARKERS):
            raise YandexDiskUiError(
                "Yandex Disk UI browser profile is not authenticated.",
                safe_message=(
                    "Yandex Disk UI browser profile is not authenticated. "
                    "Log in once in the UI automation browser profile and rerun."
                ),
            )

    def _save_failure_diagnostics(self, page: Any, exc: Exception) -> None:
        """Save latest failed UI page diagnostics to a private ignored folder."""

        try:
            self.config.diagnostics_dir.mkdir(parents=True, exist_ok=True)
            (self.config.diagnostics_dir / "latest_error.txt").write_text(
                repr(exc),
                encoding="utf-8",
            )
            (self.config.diagnostics_dir / "latest_url.txt").write_text(
                f"url={page.url}\ntitle={page.title()}\n",
                encoding="utf-8",
            )
            page.screenshot(
                path=str(self.config.diagnostics_dir / "latest.png"),
                full_page=True,
                timeout=self.config.timeout_ms,
            )
            (self.config.diagnostics_dir / "latest.html").write_text(
                page.content(),
                encoding="utf-8",
            )
        except Exception:
            return

    def _select_write_access(self, page: Any) -> None:
        """Select write/editing rights in the sharing dialog."""

        self._click_named_button(
            page,
            READ_ACCESS_PATTERN,
            "Could not open Yandex Disk access-rights dropdown.",
        )
        self._click_named_button(
            page,
            WRITE_ACCESS_PATTERN,
            "Could not select write access in Yandex Disk UI.",
        )

    def _select_suggested_user(self, page: Any, email: str) -> None:
        """Select the Yandex account suggestion for a typed email address."""

        email_pattern = re.compile(re.escape(email), re.IGNORECASE)
        deadline = time.monotonic() + self.config.timeout_ms / 1_000
        while time.monotonic() < deadline:
            locators = (
                page.get_by_role("option", name=email_pattern).first,
                page.get_by_role("menuitem", name=email_pattern).first,
                page.get_by_text(email_pattern).nth(1),
                page.get_by_text(email_pattern).first,
            )
            for locator in locators:
                if self._click_optional_locator_with_timeout(locator, click_timeout=1_000):
                    page.wait_for_timeout(MENU_SETTLE_MS)
                    return
            page.wait_for_timeout(200)
        raise YandexDiskUiError(
            "Could not select Yandex Disk invite recipient suggestion.",
            safe_message="Could not select Yandex Disk invite recipient suggestion.",
        )

    def _click_named_button(self, page: Any, pattern: str, error_message: str) -> None:
        """Click the first visible named control or menu item matching `pattern`."""

        name_pattern = re.compile(pattern, re.IGNORECASE)
        deadline = time.monotonic() + self.config.timeout_ms / 1_000
        while time.monotonic() < deadline:
            locators = (
                page.get_by_role("button", name=name_pattern).first,
                page.get_by_role("menuitem", name=name_pattern).first,
                page.get_by_role("option", name=name_pattern).first,
                page.get_by_text(name_pattern).first,
            )
            for locator in locators:
                if self._click_optional_locator_with_timeout(locator, click_timeout=1_000):
                    return
            page.wait_for_timeout(200)
        raise YandexDiskUiError(error_message, safe_message=error_message)

    def _click_optional_named_button(self, page: Any, pattern: str) -> bool:
        """Try to click a button by accessible name."""

        locator = page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE)).first
        return self._click_optional_locator(locator)

    def _click_optional_text(self, page: Any, pattern: str) -> bool:
        """Try to click visible text by regular expression."""

        locator = page.get_by_text(re.compile(pattern, re.IGNORECASE)).first
        return self._click_optional_locator(locator)

    def _fill_first_visible(
        self,
        page: Any,
        selectors: tuple[str, ...],
        value: str,
        error_message: str,
    ) -> None:
        """Fill the first visible input matching one of `selectors`."""

        for selector in selectors:
            locator = page.locator(selector).first
            try:
                if locator.count() > 0 and locator.is_visible(timeout=1_000):
                    locator.fill(value, timeout=self.config.timeout_ms)
                    return
            except Exception:
                continue
        raise YandexDiskUiError(error_message, safe_message=error_message)

    def _click_optional_locator(self, locator: Any) -> bool:
        """Try to click a locator without leaking selector details to logs."""

        return self._click_optional_locator_with_timeout(locator, click_timeout=self.config.timeout_ms)

    def _click_optional_locator_with_timeout(self, locator: Any, *, click_timeout: int) -> bool:
        """Try to click a locator with an explicit click timeout."""

        try:
            if locator.count() == 0:
                return False
            if not locator.is_visible(timeout=1_000):
                return False
            locator.click(timeout=click_timeout)
            return True
        except Exception:
            return False

    def _click_required_locator(self, locator: Any) -> bool:
        """Try to click a required locator, allowing the page to finish loading."""

        try:
            locator.click(timeout=self.config.timeout_ms)
            return True
        except Exception:
            return False

    def _click_folder_header_menu(self, page: Any, folder_name: str) -> None:
        """Click the actions menu next to the current folder title."""

        folder_title = page.get_by_text(re.compile(f"^{re.escape(folder_name)}$")).first
        self._wait_for_required_locator(
            folder_title,
            "Could not find target folder title in Yandex Disk UI.",
        )
        menu_button = page.locator(
            "xpath=(//*[normalize-space()="
            f"{_xpath_string_literal(folder_name)}]/following::button)[1]"
        ).first
        if self._click_required_locator(menu_button):
            return
        if self._click_optional_named_button(page, MORE_MENU_PATTERN):
            return
        raise YandexDiskUiError(
            "Could not open Yandex Disk folder actions menu.",
            safe_message="Could not open Yandex Disk folder actions menu.",
        )

    def _wait_for_required_locator(self, locator: Any, error_message: str) -> None:
        """Wait until a required locator is visible."""

        try:
            locator.wait_for(state="visible", timeout=self.config.timeout_ms)
        except Exception as exc:
            raise YandexDiskUiError(error_message, safe_message=error_message) from exc


def _env_bool(name: str, *, default: bool) -> bool:
    """Parse a boolean environment variable."""

    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    """Parse an integer environment variable."""

    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc


def _folder_name(folder_path: str) -> str:
    """Return the last path component from a canonical Yandex Disk folder path."""

    return folder_path.rstrip("/").split("/")[-1]


def _xpath_string_literal(value: str) -> str:
    """Return an XPath string literal for a Python string."""

    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ', "\'", '.join(f"'{part}'" for part in parts) + ")"
