"""Publish a Yandex Disk resource and grant personal access by email."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from privacy import redact_personal_data  # noqa: E402
from yandex_disk import DiskApiError, YandexDiskClient  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish a Yandex Disk resource with personal email access.",
    )
    parser.add_argument("path", help="Yandex Disk resource path to publish.")
    parser.add_argument("emails", nargs="+", help="Emails to grant personal access to.")
    parser.add_argument(
        "--rights",
        choices=("read", "write"),
        default="read",
        help="Access rights to grant.",
    )
    parser.add_argument(
        "--show-sensitive-output",
        action="store_true",
        help="Print path, public URL, public key, and API link.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        client = YandexDiskClient.from_env()
        result = client.publish_resource(args.path, emails=args.emails, rights=args.rights)
        resource = client.get_resource(args.path)
    except ValueError as exc:
        _print_error("Configuration error", exc)
        return 2
    except DiskApiError as exc:
        _print_error("Yandex Disk API error", exc)
        return 1

    recipient_count = len(args.emails)
    print("Resource published.")
    print(f"Recipients: {recipient_count}")
    print(f"Rights: {args.rights}")
    print(f"Public link returned: {bool(resource.get('public_url'))}")
    if args.show_sensitive_output:
        print(f"Path: {args.path}")
        print(f"API link: {result.get('href', '')}")
        print(f"Public URL: {resource.get('public_url', '')}")
        print(f"Public key: {resource.get('public_key', '')}")
    return 0


def _print_error(label: str, exc: Exception) -> None:
    print(f"{label}: {redact_personal_data(exc)}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
