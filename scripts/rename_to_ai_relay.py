#!/usr/bin/env python3
"""Turn core's openai_conversation integration into the ai_relay custom component.

This script is the only place where the domain rename happens. It runs on the
`upstream` branch and must be deterministic: the same core checkout always
produces byte-identical output.

Usage:
    rename_to_ai_relay.py --core <core checkout> --tag <core tag> --out <repo root>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import sys
from typing import Any

# Repository coordinates, change them here only.
REPO_SLUG = "trapplab/ai-relay"
CODEOWNERS = ["@trapplab"]

REPO_URL = f"https://github.com/{REPO_SLUG}"
SRC_DOMAIN = "openai_conversation"
DST_DOMAIN = "ai_relay"
DST_NAME = "AI Relay"
SRC_DIR = Path("homeassistant/components") / SRC_DOMAIN
DST_DIR = Path("custom_components") / DST_DOMAIN
CORE_STRINGS = Path("homeassistant/strings.json")
MARKER = ".upstream-version"

# Plain text replacements, applied in order to every text file.
TEXT_REPLACEMENTS: list[tuple[str, str]] = [
    (f"https://www.home-assistant.io/integrations/{SRC_DOMAIN}", REPO_URL),
    (SRC_DOMAIN, DST_DOMAIN),
]

DEFAULT_NAME_RE = re.compile(r'^(DEFAULT_\w*NAME = ")OpenAI\b', re.MULTILINE)
REFERENCE_RE = re.compile(r"\[%key:([^%]+)%\]")


class RenameError(Exception):
    """Raised when the upstream input does not look as expected."""


def transform_text(text: str) -> str:
    """Apply the generic text replacements."""
    for old, new in TEXT_REPLACEMENTS:
        text = text.replace(old, new)
    return text


def transform_const(text: str) -> str:
    """Rename DOMAIN and the DEFAULT_*_NAME constants."""
    text = DEFAULT_NAME_RE.sub(rf"\g<1>{DST_NAME}", text)
    if f'DOMAIN = "{DST_DOMAIN}"' not in text:
        raise RenameError("const.py: DOMAIN assignment not found")
    return text


def transform_manifest(text: str, tag: str) -> str:
    """Rewrite manifest.json for a custom component."""
    manifest = json.loads(text)
    manifest.update(
        {
            "domain": DST_DOMAIN,
            "name": DST_NAME,
            "documentation": REPO_URL,
            "issue_tracker": f"{REPO_URL}/issues",
            "codeowners": CODEOWNERS,
            "version": tag,
        }
    )
    # hassfest wants domain and name first, the rest sorted.
    head = {key: manifest.pop(key) for key in ("domain", "name")}
    ordered = head | dict(sorted(manifest.items()))
    return dump_json(ordered)


def dump_json(data: Any) -> str:
    """Serialize JSON the same way every time."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def lookup(tree: dict[str, Any], path: list[str], ref: str) -> str:
    """Look up a translation key path."""
    node: Any = tree
    for part in path:
        if not isinstance(node, dict) or part not in node:
            raise RenameError(f"unresolvable translation reference {ref}")
        node = node[part]
    if not isinstance(node, str):
        raise RenameError(f"translation reference {ref} is not a string")
    return node


def resolve_references(
    strings: dict[str, Any], core_strings: dict[str, Any]
) -> dict[str, Any]:
    """Inline [%key:...%] references, which only core's build resolves."""

    def resolve(value: str, seen: tuple[str, ...]) -> str:
        def replace(match: re.Match[str]) -> str:
            ref = match.group(1)
            if ref in seen:
                raise RenameError(f"circular translation reference {ref}")
            parts = ref.split("::")
            if parts[0] == "common":
                target = lookup(core_strings, parts, ref)
            elif parts[:2] == ["component", DST_DOMAIN]:
                target = lookup(strings, parts[2:], ref)
            else:
                raise RenameError(f"unsupported translation reference {ref}")
            return resolve(target, (*seen, ref))

        return REFERENCE_RE.sub(replace, value)

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {key: walk(value) for key, value in node.items()}
        if isinstance(node, str):
            return resolve(node, ())
        return node

    return walk(strings)


def run(core: Path, tag: str, out: Path) -> None:
    """Generate the custom component from a core checkout."""
    src = core / SRC_DIR
    if not src.is_dir():
        raise RenameError(f"{src} does not exist")
    dst = out / DST_DIR

    shutil.rmtree(dst, ignore_errors=True)
    dst.mkdir(parents=True)

    # R4: take whatever the integration directory contains.
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = path.relative_to(src)
        if "__pycache__" in rel.parts:
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            target.write_bytes(raw)
            continue
        text = transform_text(text)
        if rel == Path("const.py"):
            text = transform_const(text)
        elif rel == Path("manifest.json"):
            text = transform_manifest(text, tag)
        target.write_text(text, encoding="utf-8", newline="")

    strings_file = dst / "strings.json"
    if strings_file.is_file():
        strings = json.loads(strings_file.read_text(encoding="utf-8"))
        core_strings = json.loads((core / CORE_STRINGS).read_text(encoding="utf-8"))
        translations = dst / "translations"
        translations.mkdir(exist_ok=True)
        (translations / "en.json").write_text(
            dump_json(resolve_references(strings, core_strings)), encoding="utf-8"
        )

    (out / MARKER).write_text(f"{tag}\n", encoding="utf-8")

    # R3: nothing may still refer to the old domain.
    leftovers = [
        str(p.relative_to(out))
        for p in sorted(dst.rglob("*"))
        if p.is_file() and SRC_DOMAIN.encode() in p.read_bytes()
    ]
    if leftovers:
        raise RenameError(f"'{SRC_DOMAIN}' still present in: {', '.join(leftovers)}")


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--core", type=Path, required=True, help="core checkout")
    parser.add_argument("--tag", required=True, help="core tag, e.g. 2026.9.3")
    parser.add_argument("--out", type=Path, required=True, help="repository root")
    args = parser.parse_args()
    try:
        run(args.core, args.tag, args.out)
    except RenameError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
