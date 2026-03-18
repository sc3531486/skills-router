#!/usr/bin/env python3
from pathlib import Path


SUPPORTED_MCP_INSTALLERS = {
    "codex": {
        "approved_executor_name": "codex-mcp-installer",
        "config_target": str(Path.home() / ".codex" / "config.toml"),
    },
    "kiro": {
        "approved_executor_name": "kiro-mcp-installer",
        "config_target": str(Path.home() / ".kiro" / "settings" / "mcp.json"),
    },
}


def build_mcp_install_adapter(target):
    provider_family = (target or {}).get("provider_family") or "unknown"
    name = (target or {}).get("name") or "unknown-mcp"
    config = SUPPORTED_MCP_INSTALLERS.get(provider_family)
    if not config:
        return {
            "executor_type": "mcp_tool",
            "name": name,
            "provider_family": provider_family,
            "availability": "not_supported_yet",
            "supports_auto_install": False,
            "install_mode": "recommend-only",
            "host_action": None,
            "approved_executor": None,
            "config_target": None,
        }

    return {
        "executor_type": "mcp_tool",
        "name": name,
        "provider_family": provider_family,
        "availability": "supported",
        "supports_auto_install": True,
        "install_mode": "provider-adapter",
        "host_action": "invoke_mcp_installer",
        "approved_executor": {
            "executor_type": "mcp_tool",
            "name": config["approved_executor_name"],
            "invocation_ref": f"{provider_family}-mcp-installer:{name}",
            "host_action": "invoke_mcp_installer",
        },
        "config_target": config["config_target"],
    }
