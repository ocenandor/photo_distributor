"""Minimal Yandex Disk REST API client.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeVar
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from utils import redact_personal_data


JsonObject = dict[str, Any]
T = TypeVar("T")


class DiskApiError(RuntimeError):
    """Raised when Yandex Disk returns an error or cannot be reached.

    Attributes:
        status_code: HTTP status code when the failure came from the API, or
            `None` for local network/transport errors.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        """Create an API error while sanitizing obvious sensitive values."""

        super().__init__(redact_personal_data(message))
        self.status_code = status_code

    def safe_message(self) -> str:
        """Return a message safe for logs and console diagnostics."""

        return str(self)


def retry_yandex_disk_operation(method: Callable[..., T]) -> Callable[..., T]:
    """Retry one decorated Yandex Disk client method on transient failures.

    Args:
        method: `YandexDiskClient` method that performs a Yandex Disk API or
            upload/download operation.

    Returns:
        Wrapped method that retries 5xx API errors and local network errors.
    """

    @wraps(method)
    def wrapped(self: "YandexDiskClient", *args: Any, **kwargs: Any) -> T:
        attempt = 1
        while True:
            try:
                return method(self, *args, **kwargs)
            except DiskApiError as exc:
                if exc.status_code is not None and exc.status_code < 500:
                    raise
                if attempt >= self.retry_attempts:
                    raise
                time.sleep(attempt)
                attempt += 1
            except OSError:
                if attempt >= self.retry_attempts:
                    raise
                time.sleep(attempt)
                attempt += 1

    return wrapped


@dataclass(frozen=True)
class YandexDiskClient:
    """Small client for the Yandex Disk REST API.

    Attributes:
        token: OAuth token used in API requests. Hidden from `repr`.
        base_url: Base Yandex Disk REST API URL.
        timeout_seconds: Network timeout for API and upload/download requests.
        retry_attempts: Number of attempts for methods decorated with
            `@retry_yandex_disk_operation`.
    """

    token: str = field(repr=False)
    base_url: str = "https://cloud-api.yandex.net/v1/disk"
    timeout_seconds: int = 30
    retry_attempts: int = 3

    @classmethod
    def from_env(cls) -> "YandexDiskClient":
        """Build a client from `YANDEX_DISK_TOKEN` loaded from `.env`.

        Returns:
            Authenticated client instance.

        Raises:
            ValueError: If `YANDEX_DISK_TOKEN` is not configured.
        """

        load_dotenv()
        token = os.environ.get("YANDEX_DISK_TOKEN")
        if not token:
            raise ValueError("YANDEX_DISK_TOKEN is not set.")
        return cls(token=token)

    @retry_yandex_disk_operation
    def get_resource(self, path: str) -> JsonObject:
        """Return metadata for a Yandex Disk resource.

        Args:
            path: Absolute Yandex Disk path.

        Returns:
            Raw JSON metadata returned by Yandex Disk.
        """

        return self._request("GET", "/resources", {"path": path})

    def resource_exists(self, path: str) -> bool:
        """Return whether a Yandex Disk resource exists.

        Args:
            path: Absolute Yandex Disk path.

        Returns:
            `True` when the resource exists, `False` for a 404 response.
        """

        try:
            self.get_resource(path)
        except DiskApiError as exc:
            if exc.status_code == 404:
                return False
            raise
        return True

    @retry_yandex_disk_operation
    def list_files(self, path: str, limit: int = 1000) -> list[JsonObject]:
        """Return top-level items from a Yandex Disk folder.

        Args:
            path: Absolute Yandex Disk folder path.
            limit: Page size for Yandex Disk metadata pagination.

        Returns:
            Raw metadata rows for direct children of the folder.
        """

        items: list[JsonObject] = []
        offset = 0

        while True:
            resource = self._request(
                "GET",
                "/resources",
                {"path": path, "limit": limit, "offset": offset},
            )
            embedded = resource.get("_embedded") or {}
            batch = embedded.get("items") or []
            items.extend(batch)

            total = embedded.get("total")
            if not isinstance(total, int) or offset + len(batch) >= total:
                return items
            if not batch:
                return items
            offset += len(batch)

    @retry_yandex_disk_operation
    def create_folder(self, path: str) -> JsonObject:
        """Create a folder on Yandex Disk.

        Args:
            path: Absolute Yandex Disk folder path to create.

        Returns:
            Raw JSON response from Yandex Disk.
        """

        return self._request("PUT", "/resources", {"path": path})

    def ensure_folder(self, path: str) -> None:
        """Create a Yandex Disk folder while treating an existing folder as success.

        Args:
            path: Absolute Yandex Disk folder path to ensure.

        Returns:
            None.
        """

        try:
            self.create_folder(path)
        except DiskApiError as exc:
            if exc.status_code != 409:
                raise

    @retry_yandex_disk_operation
    def copy_resource(
        self,
        from_path: str,
        to_path: str,
        *,
        overwrite: bool = False,
    ) -> JsonObject:
        """Copy a resource on Yandex Disk.

        Args:
            from_path: Existing Yandex Disk source path.
            to_path: Yandex Disk destination path.
            overwrite: Whether Yandex Disk may replace an existing destination.

        Returns:
            Raw JSON response from Yandex Disk.
        """

        return self._request(
            "POST",
            "/resources/copy",
            {
                "from": from_path,
                "path": to_path,
                "overwrite": str(overwrite).lower(),
            },
        )

    @retry_yandex_disk_operation
    def upload_file(
        self,
        local_path: str | Path,
        disk_path: str,
        *,
        overwrite: bool = False,
    ) -> JsonObject:
        """Upload a local file to Yandex Disk.

        Args:
            local_path: Existing local file path.
            disk_path: Destination Yandex Disk path.
            overwrite: Whether Yandex Disk may replace an existing destination.

        Returns:
            Raw JSON response from the upload endpoint.
        """

        path = Path(local_path)
        if not path.is_file():
            raise ValueError(f"Local file does not exist: {path}")

        upload_info = self._request(
            "GET",
            "/resources/upload",
            {"path": disk_path, "overwrite": str(overwrite).lower()},
        )
        href = upload_info.get("href")
        if not isinstance(href, str) or not href:
            raise DiskApiError("Upload link response does not contain href.")

        request = Request(href, method="PUT", data=path.read_bytes())
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return self._read_json(response.read())
        except HTTPError as exc:
            raise DiskApiError(self._format_http_error(exc), exc.code) from exc
        except URLError as exc:
            raise DiskApiError(f"upload failed: {exc.reason}") from exc

    @retry_yandex_disk_operation
    def download_file(
        self,
        disk_path: str,
        local_path: str | Path,
        *,
        overwrite: bool = False,
    ) -> Path:
        """Download a Yandex Disk file to a local path.

        Args:
            disk_path: Existing Yandex Disk file path.
            local_path: Local destination path.
            overwrite: Whether an existing local file may be replaced.

        Returns:
            Local path that was written.
        """

        path = Path(local_path)
        if path.exists() and not overwrite:
            raise ValueError(f"Local file already exists: {path}")

        download_info = self._request("GET", "/resources/download", {"path": disk_path})
        href = download_info.get("href")
        if not isinstance(href, str) or not href:
            raise DiskApiError("Download link response does not contain href.")

        path.parent.mkdir(parents=True, exist_ok=True)
        request = Request(href, method="GET")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                path.write_bytes(response.read())
        except HTTPError as exc:
            raise DiskApiError(self._format_http_error(exc), exc.code) from exc
        except URLError as exc:
            raise DiskApiError(f"download failed: {exc.reason}") from exc

        return path

    @retry_yandex_disk_operation
    def delete_resource(self, path: str, *, permanently: bool = False) -> JsonObject:
        """Delete a Yandex Disk resource.

        Args:
            path: Absolute Yandex Disk path to delete.
            permanently: Whether to bypass the trash when supported by the API.

        Returns:
            Raw JSON response from Yandex Disk.
        """

        return self._request(
            "DELETE",
            "/resources",
            {"path": path, "permanently": str(permanently).lower()},
        )

    @retry_yandex_disk_operation
    def publish_resource(
        self,
        path: str,
        *,
        emails: list[str] | None = None,
        rights: str = "read",
    ) -> JsonObject:
        """Publish a resource and optionally grant personal access by email.

        Args:
            path: Absolute Yandex Disk resource path.
            emails: Optional Yandex accounts that should receive direct access.
            rights: Access rights to grant, for example `read`.

        Returns:
            Raw JSON response from Yandex Disk.
        """

        body: JsonObject = {"public_settings": {}}
        params: dict[str, str | int] = {"path": path}
        if emails:
            params["allow_address_access"] = "true"
            body["public_settings"] = {
                "accesses": [
                    {
                        "emails": emails,
                        "rights": [rights],
                    }
                ]
            }

        return self._request("PUT", "/resources/publish", params, json_body=body)

    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, str | int] | None = None,
        json_body: JsonObject | None = None,
    ) -> JsonObject:
        """Send one JSON-oriented Yandex Disk API request."""

        query = urlencode(params or {})
        url = f"{self.base_url}{endpoint}"
        if query:
            url = f"{url}?{query}"
        data = None
        headers = {
            "Authorization": f"OAuth {self.token}",
            "Accept": "application/json",
        }
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(
            url,
            method=method,
            data=data,
            headers=headers,
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return self._read_json(response.read())
        except HTTPError as exc:
            raise DiskApiError(self._format_http_error(exc), exc.code) from exc
        except URLError as exc:
            raise DiskApiError(f"request failed: {exc.reason}") from exc

    @staticmethod
    def _read_json(raw: bytes) -> JsonObject:
        """Decode a JSON object response from Yandex Disk."""

        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise DiskApiError("API returned invalid JSON.") from exc
        if not isinstance(data, dict):
            raise DiskApiError("API returned an unexpected JSON payload.")
        return data

    @classmethod
    def _format_http_error(cls, exc: HTTPError) -> str:
        """Build a compact API error message from an HTTPError response."""

        raw = exc.read()
        if not raw:
            return f"HTTP {exc.code}: {exc.reason}"
        try:
            payload = cls._read_json(raw)
        except DiskApiError:
            return f"HTTP {exc.code}: {raw.decode('utf-8', errors='replace')}"
        message = payload.get("message") or payload.get("error") or exc.reason
        description = payload.get("description")
        if description:
            return f"HTTP {exc.code}: {message} ({description})"
        return f"HTTP {exc.code}: {message}"
