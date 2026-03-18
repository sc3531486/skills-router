#!/usr/bin/env python3
from pathlib import Path

from mcp_install_providers import build_mcp_install_adapter


def build_skill_install_adapter(target):
    target = target or {}
    return {
        "executor_type": "skill",
        "name": target.get("name"),
        "provider_family": target.get("provider_family") or target.get("source"),
        "supports_auto_install": True,
        "install_mode": "skill-installer",
        "host_action": "invoke_skill_installer",
        "approved_executor": {
            "executor_type": "skill",
            "name": "skill-installer",
            "invocation_ref": str(Path.home() / ".codex" / "skills" / ".system" / "skill-installer" / "SKILL.md"),
            "host_action": "invoke_skill_installer",
        },
        "install_url": target.get("install_url"),
    }


def build_installation_plan(target):
    target = target or {}
    if target.get("executor_type") == "skill":
        return build_skill_install_adapter(target)
    return build_mcp_install_adapter(target)
