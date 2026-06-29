"""Minimal Yandex Disk REST API client.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv


JsonObject = dict[str, Any]


class DiskApiError(RuntimeError):
    """Raised when Yandex Disk returns an error or cannot be reached."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class YandexDiskClient:
    """Small client for the Yandex Disk REST API."""

    token: str = field(repr=False)
    base_url: str = "https://cloud-api.yandex.net/v1/disk"
    timeout_seconds: int = 30

    @classmethod
    def from_env(cls) -> "YandexDiskClient":
        load_dotenv()
        token = os.environ.get("YANDEX_DISK_TOKEN")
        if not token:
            raise ValueError("YANDEX_DISK_TOKEN is not set.")
        return cls(token=token)

    def get_resource(self, path: str) -> JsonObject:
        """Return metadata for a Yandex Disk resource."""

        return self._request("GET", "/resources", {"path": path})

    def resource_exists(self, path: str) -> bool:
        """Return whether a Yandex Disk resource exists."""

        try:
            self.get_resource(path)
        except DiskApiError as exc:
            if exc.status_code == 404:
                return False
            raise
        return True

    def list_files(self, path: str, limit: int = 1000) -> list[JsonObject]:
        """Return top-level items from a Yandex Disk folder."""

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

    def create_folder(self, path: str) -> JsonObject:
        """Create a folder on Yandex Disk."""

        return self._request("PUT", "/resources", {"path": path})

    def copy_resource(
        self,
        from_path: str,
        to_path: str,
        *,
        overwrite: bool = False,
    ) -> JsonObject:
        """Copy a resource on Yandex Disk."""

        return self._request(
            "POST",
            "/resources/copy",
            {
                "from": from_path,
                "path": to_path,
                "overwrite": str(overwrite).lower(),
            },
        )

    def upload_file(
        self,
        local_path: str | Path,
        disk_path: str,
        *,
        overwrite: bool = False,
    ) -> JsonObject:
        """Upload a local file to Yandex Disk."""

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

    def download_file(
        self,
        disk_path: str,
        local_path: str | Path,
        *,
        overwrite: bool = False,
    ) -> Path:
        """Download a Yandex Disk file to a local path."""

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

    def delete_resource(self, path: str, *, permanently: bool = False) -> JsonObject:
        """Delete a Yandex Disk resource."""

        return self._request(
            "DELETE",
            "/resources",
            {"path": path, "permanently": str(permanently).lower()},
        )

    def publish_resource(
        self,
        path: str,
        *,
        emails: list[str] | None = None,
        rights: str = "read",
    ) -> JsonObject:
        """Publish a resource and optionally grant personal access by email."""

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
