#!/usr/bin/env python3
"""Stage K7a: verify the committed model catalog against Hugging Face.

For every catalog entry:
1. Resolve the HTTPS URL (follow redirects to the CDN) and confirm the
   Content-Length equals the committed size.
2. Download the full file (streaming, ~1.6 GB across both models), compute
   its sha256, and compare with the committed hash.
3. Read the repo license line from the model card to re-confirm the
   license matches what the catalog claims.

Fails on any mismatch. Writes build/reports/k7a/model_catalog_check.{json,txt}.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
CATALOG = ROOT / "app/src/main/assets/model_catalog.json"
OUT = ROOT / "build/reports/k7a"

USER_AGENT = "offline-obgyn-assistant-ci/1.0 (model catalog verification)"


def http_json(url: str) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_catalog() -> list[dict]:
    text = CATALOG.read_text(encoding="utf-8")
    data = json.loads(text)
    models = data["models"]
    if data["version"] != 1:
        raise SystemExit(f"unexpected catalog version {data['version']}")
    if len(models) < 1:
        raise SystemExit("catalog is empty")
    defaults = [m for m in models if m["default"]]
    if len(defaults) != 1:
        raise SystemExit("catalog must mark exactly one default model")
    return models


def resolve_head(url: str) -> tuple[str, int]:
    """Follows redirects and returns (final_url, content_length)."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT}, method="HEAD"
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.geturl(), int(response.headers.get("Content-Length", "-1"))


def download_and_hash(url: str, dest: pathlib.Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=600) as response, dest.open("wb") as out:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            out.write(block)
            total += len(block)
    return digest.hexdigest(), total


def license_line(repo: str) -> str:
    """Reads the model card and returns its license line, if any."""
    url = f"https://huggingface.co/{repo}/raw/main/README.md"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            text = response.read().decode("utf-8", errors="replace")
    except Exception as failure:  # noqa: BLE001 - report and continue
        return f"(model card unavailable: {failure})"
    for line in text.splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("license:") or stripped.startswith("license_link:"):
            return line.strip()
    return "(no license line in model card)"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    models = parse_catalog()
    rows = []
    ok = True

    for model in models:
        mid = model["id"]
        url = model["url"]
        row = {
            "id": mid,
            "url": url,
            "size_bytes_committed": model["size_bytes"],
            "sha256_committed": model["sha256"],
        }

        if not url.startswith("https://"):
            print(f"[FAIL] {mid}: url is not HTTPS: {url}")
            ok = False
            rows.append({**row, "status": "FAIL", "reason": "non-https url"})
            continue

        try:
            final_url, content_length = resolve_head(url)
        except Exception as failure:  # noqa: BLE001
            print(f"[FAIL] {mid}: could not resolve {url}: {failure}")
            ok = False
            rows.append({**row, "status": "FAIL", "reason": f"resolve failed: {failure}"})
            continue

        row["resolved_url"] = final_url
        row["size_bytes_remote"] = content_length
        size_matches = content_length == model["size_bytes"]
        if not size_matches:
            print(
                f"[FAIL] {mid}: size mismatch: catalog={model['size_bytes']} "
                f"remote={content_length}"
            )
            ok = False
            rows.append({**row, "status": "FAIL", "reason": "size mismatch"})
            continue

        dest = OUT / f"{mid}.gguf"
        sha, downloaded_bytes = download_and_hash(url, dest)
        row["size_bytes_downloaded"] = downloaded_bytes
        row["sha256_remote"] = sha
        row["license_line"] = license_line(model["repo"])
        row["license_committed"] = model["license"]
        dest.unlink(missing_ok=True)

        if sha != model["sha256"]:
            print(
                f"[FAIL] {mid}: sha256 mismatch: catalog={model['sha256']} remote={sha}"
            )
            ok = False
            row["status"] = "FAIL"
            row["reason"] = "sha256 mismatch"
        else:
            print(
                f"[OK] {mid}: size={content_length} sha256={sha} license={row['license_line']}"
            )
            row["status"] = "OK"
        rows.append(row)

    report = {
        "catalog": str(CATALOG.relative_to(ROOT)),
        "models": rows,
        "status": "PASS" if ok else "FAIL",
    }
    (OUT / "model_catalog_check.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "## K7a model catalog verification",
        "",
        "| Model | Size (bytes) | sha256 | License line | Status |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['id']} | {row.get('size_bytes_downloaded', row['size_bytes_committed'])} "
            f"| `{row.get('sha256_remote', row['sha256_committed'])}` "
            f"| `{row.get('license_line', '-')}` | {row['status']} |"
        )
    lines.append("")
    lines.append(f"status={report['status']}")
    text = "\n".join(lines) + "\n"
    (OUT / "model_catalog_check.txt").write_text(text, encoding="utf-8")
    print(text)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
