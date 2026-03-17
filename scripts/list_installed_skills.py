#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

from discovery_providers import discover_skill_executors


def main():
    parser = argparse.ArgumentParser(description="List discovered local skill executors as JSON.")
    parser.add_argument(
        "--tool-home",
        action="append",
        default=[],
        help="Additional tool home to scan. Repeat to add multiple homes.",
    )
    parser.add_argument(
        "--base-dir",
        default=str(Path.home() / ".codex" / "skills" / "skill-router"),
        help="Path to the skill-router directory.",
    )
    args = parser.parse_args()

    skills, roots, warnings = discover_skill_executors(explicit_homes=args.tool_home)
    payload = {
        "skill_roots": roots,
        "skills": skills,
        "warnings": warnings,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    main()
