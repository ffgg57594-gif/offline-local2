#!/usr/bin/env python3
"""Stage K7a: network-policy gate.

The app may reach the network ONLY through the in-app model downloader.
Concretely: no Kotlin/Java source outside
app/src/main/java/com/medai/assistant/llm/download/ may reference
java.net, javax.net, okhttp, HttpURLConnection, openConnection, WebView,
or DownloadManager (comments are stripped before matching, so KDoc
mentions do not count as references; strings are still checked so a
token hidden in code fails loudly).

Also asserts the network security config forbids cleartext.

Writes build/reports/k7a/network_usage_check.{json,txt} and exits non-zero
on any violation.
"""
from __future__ import annotations

import json
import os
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "app/src/main/java"
DOWNLOAD_PACKAGE = "com/medai/assistant/llm/download"
NSC = ROOT / "app/src/main/res/xml/network_security_config.xml"
OUT = ROOT / "build/reports/k7a"

TOKENS = [
    r"java\.net",
    r"javax\.net",
    r"okhttp",
    r"HttpURLConnection",
    r"openConnection",
    r"DownloadManager",
    r"WebView",
]

TOKEN_RE = re.compile("|".join(TOKENS))


def strip_comments(text: str) -> str:
    """Removes /* */ block comments and // line comments (naive but
    sufficient: string contents are kept, so tokens inside code strings
    still fail)."""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "*":
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            out.append(" ")
        elif ch == "/" and nxt == "/":
            end = text.find("\n", i)
            i = n if end < 0 else end
            out.append("\n" if end >= 0 else "")
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    violations = []
    scanned = 0
    references_in_download_package = []

    for path in sorted(SRC.rglob("*.kt")) + sorted(SRC.rglob("*.java")):
        scanned += 1
        rel = path.relative_to(SRC).as_posix()
        is_download_package = rel.startswith(DOWNLOAD_PACKAGE)
        code = strip_comments(path.read_text(encoding="utf-8"))
        found = sorted(set(TOKEN_RE.findall(code)))
        if not found:
            continue
        if is_download_package:
            references_in_download_package.append({"file": rel, "tokens": found})
        else:
            violations.append({"file": rel, "tokens": found})

    # The manifest itself must ask for exactly INTERNET + POST_NOTIFICATIONS.
    manifest = (ROOT / "app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    permissions = sorted(re.findall(r'android:name="android\.permission\.([A-Z_]+)"', manifest))
    expected_permissions = ["INTERNET", "POST_NOTIFICATIONS"]
    permissions_ok = permissions == expected_permissions

    nsc_ok = False
    nsc_detail = ""
    if NSC.exists():
        nsc_text = NSC.read_text(encoding="utf-8")
        nsc_ok = 'cleartextTrafficPermitted="false"' in nsc_text
        nsc_detail = nsc_text.strip()
    else:
        nsc_detail = "network_security_config.xml missing"

    ok = not violations and permissions_ok and nsc_ok

    report = {
        "scanned_files": scanned,
        "download_package": f"app/src/main/java/{DOWNLOAD_PACKAGE}",
        "violations": violations,
        "allowed_download_package_references": references_in_download_package,
        "manifest_permissions": permissions,
        "manifest_permissions_ok": permissions_ok,
        "network_security_config_ok": nsc_ok,
        "network_security_config": nsc_detail,
        "status": "PASS" if ok else "FAIL",
    }
    (OUT / "network_usage_check.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "## K7a network usage check",
        "",
        f"- Scanned {scanned} source files under app/src/main/java.",
        "- Allowed network package: app/src/main/java/com/medai/assistant/llm/download/",
        f"- Violations outside the download package: {len(violations)}",
        f"- Manifest permissions: {', '.join(permissions)} "
        f"(expected exactly INTERNET + POST_NOTIFICATIONS: "
        f"{'YES' if permissions_ok else 'NO'})",
        f"- network_security_config.xml cleartextTrafficPermitted=false: "
        f"{'YES' if nsc_ok else 'NO'}",
        "",
    ]
    if references_in_download_package:
        lines.append("References inside the allowed download package:")
        for ref in references_in_download_package:
            lines.append(f"- {ref['file']}: {', '.join(ref['tokens'])}")
        lines.append("")
    if violations:
        lines.append("**VIOLATIONS (network references outside the download package):**")
        for violation in violations:
            lines.append(f"- {violation['file']}: {', '.join(violation['tokens'])}")
        lines.append("")
    lines.append(f"status={report['status']}")
    text = "\n".join(lines) + "\n"
    (OUT / "network_usage_check.txt").write_text(text, encoding="utf-8")
    print(text)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
