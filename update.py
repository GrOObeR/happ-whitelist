#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent
SOURCES_FILE = ROOT / "sources.txt"
OUTPUT_FILE = ROOT / "happ.txt"

PROFILE_TITLE = "WhiteList Auto"
UPDATE_INTERVAL_HOURS = 1

TIMEOUT_SECONDS = 30
MIN_CONFIGS = 5

USER_AGENT = (
    "Mozilla/5.0 (compatible; HappWhitelistAggregator/1.0; "
    "+https://github.com/)"
)


def load_source_groups() -> list[list[str]]:
    """
    sources.txt:
      - one independent source per line;
      - mirrors of the SAME source may be separated with |;
      - blank lines and lines beginning with # are ignored.

    Example:
      https://mirror1/list.txt | https://mirror2/list.txt
      https://another-source/list.txt
    """
    if not SOURCES_FILE.exists():
        raise RuntimeError(f"Missing {SOURCES_FILE.name}")

    groups: list[list[str]] = []

    for raw_line in SOURCES_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        mirrors = [part.strip() for part in line.split("|") if part.strip()]
        if mirrors:
            groups.append(mirrors)

    if not groups:
        raise RuntimeError("No sources configured in sources.txt")

    return groups


def download_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/plain,*/*;q=0.8",
            "Cache-Control": "no-cache",
        },
    )

    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        status = getattr(response, "status", 200)

        if status != 200:
            raise RuntimeError(f"HTTP {status}")

        raw = response.read()

    return raw.decode("utf-8", errors="replace")


def fetch_group(mirrors: list[str]) -> tuple[str, str]:
    """Try mirrors from left to right and return the first successful one."""
    errors: list[str] = []

    for url in mirrors:
        try:
            text = download_text(url)
            if text.strip():
                return url, text
            errors.append(f"{url}: empty response")
        except Exception as exc:
            errors.append(f"{url}: {exc}")

    raise RuntimeError(
        "All mirrors failed:\n  " + "\n  ".join(errors)
    )


def config_identity(vless_url: str) -> str:
    """
    Deduplicate the same VLESS configuration even when only the display
    name after # differs. Query parameters remain part of the identity.
    """
    parts = urlsplit(vless_url)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, parts.query, "")
    )


def extract_vless(text: str) -> list[str]:
    result: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if line.lower().startswith("vless://"):
            result.append(line)

    return result


def build_subscription(configs: list[str]) -> str:
    header = [
        f"#profile-title: {PROFILE_TITLE}",
        f"#profile-update-interval: {UPDATE_INTERVAL_HOURS}",
        "",
    ]

    return "\n".join(header + configs) + "\n"


def main() -> int:
    groups = load_source_groups()

    merged: list[str] = []
    seen: set[str] = set()

    successful_groups = 0

    for index, mirrors in enumerate(groups, start=1):
        try:
            used_url, text = fetch_group(mirrors)
            configs = extract_vless(text)

            if not configs:
                raise RuntimeError("source returned no VLESS configurations")

            before = len(merged)

            for config in configs:
                identity = config_identity(config)
                if identity in seen:
                    continue

                seen.add(identity)
                merged.append(config)

            successful_groups += 1
            added = len(merged) - before
            print(
                f"[OK] source #{index}: {used_url} "
                f"({len(configs)} found, {added} added)"
            )

        except Exception as exc:
            print(f"[WARN] source #{index}: {exc}", file=sys.stderr)

    # Safety guard: never replace a healthy subscription with an empty/
    # obviously broken result because an upstream source temporarily failed.
    if successful_groups == 0:
        print("[ERROR] No source groups could be downloaded.", file=sys.stderr)
        return 1

    if len(merged) < MIN_CONFIGS:
        print(
            f"[ERROR] Only {len(merged)} unique VLESS configs were collected; "
            f"minimum is {MIN_CONFIGS}. Existing happ.txt was left untouched.",
            file=sys.stderr,
        )
        return 1

    new_content = build_subscription(merged)

    old_content = ""
    if OUTPUT_FILE.exists():
        old_content = OUTPUT_FILE.read_text(encoding="utf-8")

    if old_content == new_content:
        print(f"[OK] No changes. {len(merged)} configs.")
        return 0

    temp_file = OUTPUT_FILE.with_suffix(".txt.tmp")
    temp_file.write_text(new_content, encoding="utf-8", newline="\n")
    os.replace(temp_file, OUTPUT_FILE)

    print(f"[OK] Updated {OUTPUT_FILE.name}: {len(merged)} unique configs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
