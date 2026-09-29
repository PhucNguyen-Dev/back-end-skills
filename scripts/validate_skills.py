#!/usr/bin/env python3
"""Validate skill directories against the Agent Skills spec.

Checks per skill directory:
  - SKILL.md exists
  - YAML frontmatter parses and has required fields
  - name matches directory name and spec regex (<=64 chars, lowercase/digits/hyphens)
  - description present, non-empty, <=1024 chars, mentions when-to-use
  - license / compatibility (if present) within spec limits
  - metadata is a string->string map
  - relative file links in SKILL.md resolve and stay one level deep
  - SKILL.md body stays under the recommended token budget

Usage: python scripts/validate_skills.py [root]
Exit code 0 = all skills valid.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)

MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500
# Spec recommends <5000 tokens for the body loaded on activation.
MAX_BODY_TOKENS = 5000

errors: list[str] = []
warnings: list[str] = []


def parse_frontmatter(text: str) -> tuple[dict[str, object] | None, str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None, text
    raw = match.group(1)
    body = text[match.end():]
    data: dict[str, object] = {}
    current_key: str | None = None
    in_metadata = False
    metadata: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        if not line.startswith((" ", "\t")) and ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            current_key = key
            in_metadata = key == "metadata"
            if in_metadata:
                continue
            data[key] = value
        elif in_metadata and ":" in stripped:
            mkey, _, mvalue = stripped.partition(":")
            metadata[mkey.strip()] = mvalue.strip().strip('"').strip("'")
        elif current_key and stripped.startswith("-") and isinstance(data.get(current_key), list):
            data[current_key].append(stripped.lstrip("- ").strip('"').strip("'"))  # type: ignore[union-attr]
    if in_metadata:
        data["metadata"] = metadata
    return data, body


def approx_tokens(text: str) -> int:
    # ~4 chars per token is a common rough estimate for English prose.
    return len(text) // 4


def validate_skill(skill_dir: Path) -> None:
    rel = skill_dir.name
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        errors.append(f"{rel}: missing SKILL.md")
        return

    text = skill_md.read_text(encoding="utf-8")
    data, body = parse_frontmatter(text)
    if data is None:
        errors.append(f"{rel}: missing YAML frontmatter")
        return

    name = str(data.get("name", ""))
    if not name:
        errors.append(f"{rel}: frontmatter missing 'name'")
    else:
        if not NAME_RE.match(name) or len(name) > MAX_NAME:
            errors.append(f"{rel}: invalid name '{name}' (regex {NAME_RE.pattern}, <= {MAX_NAME} chars)")
        if name != rel:
            errors.append(f"{rel}: name '{name}' must match directory name")

    description = str(data.get("description", ""))
    if not description:
        errors.append(f"{rel}: frontmatter missing 'description'")
    elif len(description) > MAX_DESCRIPTION:
        errors.append(f"{rel}: description {len(description)} chars > {MAX_DESCRIPTION}")
    elif not re.search(r"\b(use when|when to use|use for|use this)\b", description, re.IGNORECASE):
        warnings.append(f"{rel}: description lacks an explicit 'use when/for' trigger")

    compat = data.get("compatibility")
    if compat is not None and len(str(compat)) > MAX_COMPATIBILITY:
        errors.append(f"{rel}: compatibility {len(str(compat))} chars > {MAX_COMPATIBILITY}")

    metadata = data.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, dict):
            errors.append(f"{rel}: metadata must be a string->string map")
        else:
            for k, v in metadata.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    errors.append(f"{rel}: metadata entry {k!r} must be a string->string pair")

    for field in ("name", "description"):
        if field not in data:
            errors.append(f"{rel}: required field '{field}' missing")

    for link in LINK_RE.findall(body):
        if link.startswith(("http://", "https://", "mailto:", "#")):
            continue
        target = link.split("#", 1)[0]
        if not target:
            continue
        if target.startswith("/"):
            errors.append(f"{rel}: absolute link '{link}' must be relative")
            continue
        resolved = (skill_dir / target).resolve()
        depth = len(Path(target).parts)
        if depth > 2:
            errors.append(f"{rel}: link '{link}' deeper than one level from SKILL.md")
        if not resolved.exists():
            errors.append(f"{rel}: broken link '{link}'")

    body_tokens = approx_tokens(body)
    if body_tokens > MAX_BODY_TOKENS:
        errors.append(f"{rel}: body ~{body_tokens} tokens > {MAX_BODY_TOKENS}; move detail to references/")


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        print(f"ERROR: expected skills/ under {root}")
        return 2

    skill_dirs = sorted(p for p in skills_dir.iterdir() if p.is_dir())
    if not skill_dirs:
        print("ERROR: no skill directories found")
        return 2

    for skill_dir in skill_dirs:
        validate_skill(skill_dir)

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")

    print(f"\n{len(skill_dirs)} skill(s) checked, {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
