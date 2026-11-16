#!/usr/bin/env python3
"""Aggregate curated VLESS whitelist subscriptions for Happ (Python 3.12 stdlib)."""
from __future__ import annotations

import json
import os
import socket
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parent
TITLE = 'WhiteList Auto'
INTERVAL_HOURS = 1
MAX_MAIN_CONFIGS = 350
MAX_FULL_CONFIGS = 3000
MAX_VARIANTS_PER_CONNECTION = 2
ENABLE_TCP_TEST = True
TCP_TIMEOUT_SECONDS = 2.0
TCP_WORKERS = 24
SOURCE_TIMEOUT_SECONDS = 25
MIN_CONFIGS = 10
MIN_PREVIOUS_RATIO = 0.40


def sources():
    groups = []
    for raw in (ROOT / 'sources.txt').read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        mirrors = [x.strip() for x in line.split('|') if x.strip()]
        for url in mirrors:
            if urlsplit(url).scheme != 'https':
                raise ValueError(f'Only HTTPS sources allowed: {url}')
        groups.append(mirrors)
    if not groups:
        raise ValueError('sources.txt is empty')
    return groups


def fetch(group):
    for url in group:
        try:
            request = urllib.request.Request(url, headers={
                'User-Agent': 'HappWhitelistBot/2.0',
                'Cache-Control': 'no-cache',
                'Accept': 'text/plain, */*;q=0.5',
            })
            with urllib.request.urlopen(request, timeout=SOURCE_TIMEOUT_SECONDS) as response:
                raw = response.read(4_000_001)
            if len(raw) > 4_000_000:
                raise ValueError('source too large (>4 MB)')
            value = raw.decode('utf-8-sig', errors='replace')
            valid = [line.strip() for line in value.splitlines() if line.strip().lower().startswith('vless://')]
            if not valid:
                raise ValueError('no VLESS configs (possible placeholder / HTML)')
            return url, valid
        except Exception as exc:
            print(f'  [MIRROR ERROR] {url}: {exc}', file=sys.stderr)
    return None, []


def parsed(line):
    try:
        parts = urlsplit(line)
        if parts.scheme.lower() != 'vless' or not parts.username or not parts.hostname:
            return None
        port = parts.port
        if not port or not 1 <= port <= 65535:
            return None
        if any(ord(c) < 32 for c in line):
            return None
        query = tuple(sorted(parse_qsl(parts.query, keep_blank_values=True)))
        return parts, query
    except (ValueError, TypeError):
        return None


def identity(line):
    """Distinct full config: preserve fingerprint and all query parameters, ignore name and query ordering."""
    p = parsed(line)
    if p is None:
        return None
    parts, query = p
    return (parts.username, parts.hostname.lower(), parts.port, parts.path, query)


def connection_identity(line):
    """Configurations differing only by TLS client fingerprint are one logical connection."""
    parts, query = parsed(line)
    filtered_query = tuple((k, v) for k, v in query if k.lower() != 'fp')
    return (parts.username, parts.hostname.lower(), parts.port, parts.path, filtered_query)


def endpoint(line):
    parts, _ = parsed(line)
    return (parts.hostname.lower(), parts.port)


def fingerprint_rank(line):
    """Prefer common portable fingerprints when choosing among alternate configs."""
    _, params = parsed(line)
    fp = next((v.lower() for k, v in params if k.lower() == 'fp'), '')
    return {'chrome': 0, 'ios': 1, 'firefox': 2, 'edge': 3, 'safari': 4}.get(fp, 5)


def profile(name, items):
    return '\n'.join((
        f'#profile-title: {name}',
        f'#profile-update-interval: {INTERVAL_HOURS}',
        '#subscription-auto-update-open-enable: 1',
        '',
        *items,
        '',
    ))


def count_old():
    file = ROOT / 'happ.txt'
    if not file.exists():
        return 0
    return sum(1 for line in file.read_text(encoding='utf-8').splitlines() if line.startswith('vless://'))


def write_if_changed(name, text):
    path = ROOT / name
    if path.exists() and path.read_text(encoding='utf-8') == text:
        return False
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text, encoding='utf-8', newline='\n')
    os.replace(tmp, path)
    return True


def check_tcp(item):
    host, port = item
    try:
        with socket.create_connection((host, port), timeout=TCP_TIMEOUT_SECONDS):
            return True
    except (TimeoutError, OSError):
        return False


def main():
    all_items = []
    seen = set()
    source_stats = []
    success_count = 0
    for idx, group in enumerate(sources(), start=1):
        used_url, raw = fetch(group)
        added = 0
        valid = 0
        if used_url:
            success_count += 1
            for item in raw:
                key = identity(item)
                if key is None:
                    continue
                valid += 1
                if key not in seen:
                    seen.add(key)
                    all_items.append(item)
                    added += 1
        print(f'Source {idx}: valid={valid}, new={added}, used={used_url or "NONE"}')
        source_stats.append({'source': group[0], 'valid': valid, 'added': added, 'ok': bool(used_url)})

    if not success_count or len(all_items) < MIN_CONFIGS:
        raise RuntimeError('Insufficient valid VLESS configurations; existing files left intact')

    # Preserve the first encountered connection order, but prefer Chrome/iOS
    # over obscure TLS fingerprints for the at-most-two variants per connection.
    connection_groups = {}
    for item in all_items:
        connection_groups.setdefault(connection_identity(item), []).append(item)
    main_items = []
    for variants in connection_groups.values():
        ordered = sorted(variants, key=fingerprint_rank)
        main_items.extend(ordered[:MAX_VARIANTS_PER_CONNECTION])
        if len(main_items) >= MAX_MAIN_CONFIGS:
            main_items = main_items[:MAX_MAIN_CONFIGS]
            break

    prior_count = count_old()
    if prior_count >= MIN_CONFIGS and len(main_items) < max(MIN_CONFIGS, int(prior_count * MIN_PREVIOUS_RATIO)):
        raise RuntimeError(f'Suspicious drop: {prior_count} -> {len(main_items)}; existing files left intact')

    # Connectivity from GitHub runners is NOT equivalent to connecting from Russian mobile providers.
    # Keep this experimental list separate; never remove TCP-failed nodes from the primary list.
    tcp_pass = set()
    unique_endpoints = list(dict.fromkeys(endpoint(item) for item in main_items))
    if ENABLE_TCP_TEST:
        with ThreadPoolExecutor(max_workers=TCP_WORKERS) as pool:
            futures = {pool.submit(check_tcp, ep): ep for ep in unique_endpoints}
            for future in as_completed(futures):
                if future.result():
                    tcp_pass.add(futures[future])
    tcp_items = [item for item in main_items if endpoint(item) in tcp_pass]

    payloads = {
        'happ.txt': profile(TITLE, main_items),
        'happ_all.txt': profile(TITLE + ' FULL', all_items[:MAX_FULL_CONFIGS]),
        'happ_tcp.txt': profile(TITLE + ' TCP (GitHub)', tcp_items),
    }

    stats = {
        'sources': source_stats,
        'input_unique_configurations': len(all_items),
        'input_unique_endpoints_host_port': len({endpoint(x) for x in all_items}),
        'main_configurations': len(main_items),
        'main_unique_endpoints_host_port': len(unique_endpoints),
        'tcp_endpoints_reachable_from_github': len(tcp_pass),
        'tcp_endpoints_tested_from_github': len(unique_endpoints),
        'tcp_configs': len(tcp_items),
        'note': 'TCP success from GitHub is not a VLESS/Reality check and does not imply connectivity from mobile networks in Russia',
    }
    payloads['stats.json'] = json.dumps(stats, ensure_ascii=False, indent=2) + '\n'

    for path, content in payloads.items():
        changed = write_if_changed(path, content)
        print(f'{path}: {"updated" if changed else "unchanged"}')
    print(f'Unique endpoints: {stats["main_unique_endpoints_host_port"]}; '
          f'main: {len(main_items)}; full: {len(all_items)}; TCP reachable: {len(tcp_pass)}')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'[ERROR] {exc}', file=sys.stderr)
        sys.exit(1)
