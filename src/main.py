"""Command-line entry point for the photo distributor prototype."""

from __future__ import annotations

import argparse
import sys

from yandex_disk import DiskApiError, YandexDiskClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python src/main.py",
        description="Probe access to a Yandex Disk event folder.",
    )
    parser.add_argument(
        "event_folder",
        help="Yandex Disk path to the shared event photo folder.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        client = YandexDiskClient.from_env()
        resource = client.get_resource(args.event_folder)
        items = client.list_files(args.event_folder)
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except DiskApiError as exc:
        print(f"Yandex Disk API error: {exc}", file=sys.stderr)
        return 1

    name = resource.get("name") or args.event_folder
    resource_type = resource.get("type", "unknown")
    path = resource.get("path", args.event_folder)

    print(f"Folder: {name}")
    print(f"Type: {resource_type}")
    print(f"Path: {path}")
    print(f"Items: {len(items)}")

    for item in items:
        item_type = item.get("type", "unknown")
        item_name = item.get("name", "")
        item_path = item.get("path", "")
        print(f"- {item_type}\t{item_name}\t{item_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
