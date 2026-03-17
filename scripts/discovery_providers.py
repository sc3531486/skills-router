#!/usr/bin/env python3
import json
import os
import tomllib
from pathlib import Path

from router_lib import (
    PROCESS_SKILL_NAMES,
    dedupe_entries,
    enrich_executor,
    expand_path,
    parse_frontmatter,
)


KNOWN_TOOL_HOMES = {
    "codex": ".codex",
    "claude": ".claude",
    "cursor": ".cursor",
    "kiro": ".kiro",
    "agents": ".agents",
}


def normalize_warning(message, provider, path=None):
    return {
        "provider": provider,
        "path": str(path) if path else None,
        "message": message,
    }


def safe_load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, None
    except Exception as exc:
        return None, str(exc)


def safe_load_toml(path):
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle), None
    except FileNotFoundError:
        return None, None
    except Exception as exc:
        return None, str(exc)


def resolve_tool_homes(explicit_homes=None):
    homes = []
    seen = set()
    if explicit_homes:
        for item in explicit_homes:
            path = expand_path(item)
            key = str(path).lower()
            if key in seen:
                continue
            seen.add(key)
            homes.append(path)
    user_home = Path.home()
    for dirname in KNOWN_TOOL_HOMES.values():
        path = user_home / dirname
        key = str(path).lower()
        if key in seen or not path.exists():
            continue
        seen.add(key)
        homes.append(path)
    return homes


def infer_collection(path):
    path = Path(path)
    if path.name.lower() == "skills" and path.parent.name.lower() == "superpowers":
        return "superpowers"
    return path.name


def skill_root_entries_for_tool(tool_family, home_path):
    home_path = Path(home_path)
    entries = []
    if tool_family == "codex":
        for candidate in (home_path / "skills", home_path / "superpowers" / "skills"):
            if candidate.exists():
                entries.append(
                    {
                        "path": str(candidate),
                        "tool_family": tool_family,
                        "collection": infer_collection(candidate),
                    }
                )
    elif tool_family == "kiro":
        candidate = home_path / "skills"
        if candidate.exists():
            entries.append(
                {
                    "path": str(candidate),
                    "tool_family": tool_family,
                    "collection": infer_collection(candidate),
                }
            )
    elif tool_family == "agents":
        candidate = home_path / "skills"
        if candidate.exists():
            entries.append(
                {
                    "path": str(candidate),
                    "tool_family": tool_family,
                    "collection": infer_collection(candidate),
                }
            )
    elif tool_family in {"claude", "cursor"}:
        candidate = home_path / "skills"
        if candidate.exists():
            entries.append(
                {
                    "path": str(candidate),
                    "tool_family": tool_family,
                    "collection": infer_collection(candidate),
                }
            )
    return entries


def discover_skill_roots(explicit_homes=None):
    roots = []
    for home_path in resolve_tool_homes(explicit_homes):
        tool_family = home_path.name.lstrip(".").lower()
        roots.extend(skill_root_entries_for_tool(tool_family, home_path))
    deduped = []
    seen = set()
    for root in roots:
        key = str(Path(root["path"]).resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(root)
    return deduped


def scan_skill_root(root_entry):
    root_path = Path(root_entry["path"])
    executors = []
    warnings = []
    for child in sorted(root_path.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.exists():
            continue
        try:
            frontmatter = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        except Exception as exc:
            warnings.append(normalize_warning(f"Failed to parse SKILL.md: {exc}", "skill-root", child))
            continue
        name = frontmatter.get("name", child.name)
        description = frontmatter.get("description", "")
        process_only = root_entry["collection"] == "superpowers" or name in PROCESS_SKILL_NAMES
        executors.append(
            enrich_executor(
                {
                    "executor_id": f"skill:{root_entry['tool_family']}:{name}",
                    "executor_type": "skill",
                    "name": name,
                    "description": description,
                    "source": "local-skill",
                    "tool_family": root_entry["tool_family"],
                    "skill_collection": root_entry["collection"],
                    "path": str(child),
                    "invocation_ref": str(child),
                    "process_only": process_only,
                    "constraints": {
                        "interactive": False,
                        "requires_network": False,
                    },
                }
            )
        )
    return executors, warnings


def discover_skill_executors(explicit_homes=None):
    roots = discover_skill_roots(explicit_homes)
    executors = []
    warnings = []
    for root in roots:
        items, root_warnings = scan_skill_root(root)
        executors.extend(items)
        warnings.extend(root_warnings)
    return dedupe_entries(executors, key_fields=("executor_id",)), roots, warnings


def build_server_level_mcp_executor(tool_family, source, server_name, description, invocation_ref, constraints=None, executor_type="mcp_tool"):
    return enrich_executor(
        {
            "executor_id": f"{executor_type}:{tool_family}:{server_name}",
            "executor_type": executor_type,
            "name": server_name,
            "description": description,
            "source": source,
            "tool_family": tool_family,
            "invocation_ref": invocation_ref,
            "constraints": constraints or {},
        }
    )


def codex_mcp_manifest_provider(home_path):
    config_path = Path(home_path) / "config.toml"
    config, err = safe_load_toml(config_path)
    if err:
        return [], [{"provider": "codex-mcp", "path": str(config_path), "message": err}]
    if not config:
        return [], []
    servers = config.get("mcp_servers", {})
    executors = []
    for server_name, server_config in servers.items():
        description = f"MCP server '{server_name}' declared in Codex config."
        constraints = {
            "requires_network": bool(server_config.get("url")),
            "interactive": False,
            "manifest_only": True,
        }
        executors.append(
            build_server_level_mcp_executor(
                tool_family="codex",
                source="mcp-manifest",
                server_name=server_name,
                description=description,
                invocation_ref=f"codex-config:{server_name}",
                constraints=constraints,
            )
        )
    return executors, []


def kiro_mcp_manifest_provider(home_path):
    config_path = Path(home_path) / "settings" / "mcp.json"
    data, err = safe_load_json(config_path)
    if err:
        return [], [{"provider": "kiro-mcp", "path": str(config_path), "message": err}]
    if not data:
        return [], []
    executors = []
    for server_name, server_config in data.get("mcpServers", {}).items():
        description = f"MCP server '{server_name}' declared in Kiro settings."
        constraints = {
            "requires_network": bool(server_config.get("url")),
            "interactive": False,
            "mutating": bool(server_config.get("autoApprove")),
            "manifest_only": True,
        }
        executors.append(
            build_server_level_mcp_executor(
                tool_family="kiro",
                source="mcp-manifest",
                server_name=server_name,
                description=description,
                invocation_ref=f"kiro-settings:{server_name}",
                constraints=constraints,
            )
        )
    return executors, []


def claude_mcp_manifest_provider(home_path):
    settings_path = Path(home_path) / "settings.json"
    data, err = safe_load_json(settings_path)
    if err:
        return [], [{"provider": "claude-mcp", "path": str(settings_path), "message": err}]
    if not data:
        return [], []
    executors = []
    for raw_name in data.get("enabledMcpjsonServers", []):
        server_name = str(raw_name).replace("mcp__", "").replace("MCP__", "")
        description = f"MCP capability '{server_name}' enabled in Claude settings."
        executors.append(
            build_server_level_mcp_executor(
                tool_family="claude",
                source="mcp-manifest",
                server_name=server_name,
                description=description,
                invocation_ref=f"claude-settings:{server_name}",
                constraints={"manifest_only": True},
            )
        )
    return executors, []


def cursor_mcp_manifest_provider(home_path):
    candidates = list(Path(home_path).rglob("*mcp*.json"))
    if not candidates:
        return [], []
    warnings = [
        normalize_warning("Cursor MCP manifest discovery is best-effort; no stable parser is implemented yet.", "cursor-mcp", path)
        for path in candidates[:3]
    ]
    return [], warnings


def agents_mcp_manifest_provider(home_path):
    return [], []


MANIFEST_PROVIDERS = {
    "codex": codex_mcp_manifest_provider,
    "claude": claude_mcp_manifest_provider,
    "cursor": cursor_mcp_manifest_provider,
    "kiro": kiro_mcp_manifest_provider,
    "agents": agents_mcp_manifest_provider,
}


def discover_manifest_mcp_executors(explicit_homes=None):
    executors = []
    warnings = []
    sources = []
    for home_path in resolve_tool_homes(explicit_homes):
        tool_family = home_path.name.lstrip(".").lower()
        provider = MANIFEST_PROVIDERS.get(tool_family)
        if not provider:
            continue
        provider_executors, provider_warnings = provider(home_path)
        if provider_executors or provider_warnings:
            sources.append(
                {
                    "provider": f"{tool_family}-manifest",
                    "tool_family": tool_family,
                    "path": str(home_path),
                }
            )
        executors.extend(provider_executors)
        warnings.extend(provider_warnings)
    return dedupe_entries(executors, key_fields=("executor_id",)), sources, warnings


def load_session_snapshot(path_text):
    if not path_text:
        return []
    path = expand_path(path_text)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def session_tool_entry_to_executor(item):
    server_name = item.get("server") or item.get("tool_family") or "session"
    name = item.get("name") or item.get("title") or item.get("tool_name")
    description = item.get("description") or item.get("title") or ""
    invocation_ref = item.get("invocation_ref") or name
    constraints = {
        "requires_network": item.get("requires_network", False),
        "interactive": item.get("interactive", False),
        "mutating": item.get("mutating", False),
    }
    return enrich_executor(
        {
            "executor_id": item.get("executor_id") or f"mcp_tool:{server_name}:{name}",
            "executor_type": "mcp_tool",
            "name": name,
            "description": description,
            "source": "mcp-session",
            "tool_family": server_name,
            "invocation_ref": invocation_ref,
            "constraints": constraints,
            "capabilities": item.get("capabilities", []),
            "keywords": item.get("keywords", []),
        }
    )


def session_resource_entry_to_executor(item):
    server_name = item.get("server") or item.get("tool_family") or "session"
    name = item.get("name") or item.get("title") or item.get("uri")
    description = item.get("description") or item.get("title") or ""
    return enrich_executor(
        {
            "executor_id": item.get("executor_id") or f"mcp_resource:{server_name}:{name}",
            "executor_type": "mcp_resource",
            "name": name,
            "description": description,
            "source": "mcp-session",
            "tool_family": server_name,
            "invocation_ref": item.get("uri") or item.get("invocation_ref") or name,
            "constraints": {
                "context_only": True,
                "read_only": True,
            },
            "capabilities": item.get("capabilities", []),
            "keywords": item.get("keywords", []),
        }
    )


def discover_session_mcp_executors(session_tools_file=None, session_resources_file=None):
    tool_items = load_session_snapshot(session_tools_file)
    resource_items = load_session_snapshot(session_resources_file)
    executors = []
    if tool_items:
        executors.extend(session_tool_entry_to_executor(item) for item in tool_items)
    if resource_items:
        executors.extend(session_resource_entry_to_executor(item) for item in resource_items)
    sources = []
    if tool_items:
        sources.append({"provider": "session-tools", "path": str(expand_path(session_tools_file))})
    if resource_items:
        sources.append({"provider": "session-resources", "path": str(expand_path(session_resources_file))})
    return dedupe_entries(executors, key_fields=("executor_id",)), sources, []


def discover_all_executors(base_dir, explicit_homes=None, session_tools_file=None, session_resources_file=None):
    skill_executors, skill_roots, skill_warnings = discover_skill_executors(explicit_homes=explicit_homes)
    manifest_executors, manifest_sources, manifest_warnings = discover_manifest_mcp_executors(explicit_homes=explicit_homes)
    session_executors, session_sources, session_warnings = discover_session_mcp_executors(
        session_tools_file=session_tools_file,
        session_resources_file=session_resources_file,
    )
    executors = dedupe_entries(skill_executors + session_executors + manifest_executors, key_fields=("executor_id",))
    mcp_sources = session_sources + manifest_sources
    warnings = skill_warnings + manifest_warnings + session_warnings
    return executors, skill_roots, mcp_sources, warnings
