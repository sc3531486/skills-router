#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

from discovery_providers import discover_all_executors
from model_router import decide_route
from policy_validator import validate_route
from router_lib import (
    finalize_task_info,
    build_recommendations,
    dedupe_entries,
    enrich_executor,
    fetch_remote_indexes,
    infer_task,
    load_router_assets,
    merge_executor_with_index,
    prefers_chinese,
)


def build_user_summary(task_text, validation_result, routing_decision):
    use_chinese = prefers_chinese(task_text)
    chosen_plan = validation_result.get("chosen_plan") or {}
    steps = chosen_plan.get("steps", [])
    if not steps:
        return "计划：当前没有可直接执行的路线，先返回缺失能力与推荐项。" if use_chinese else "Plan: no executable route is available yet, so return gaps and recommendations first."
    ordered = " -> ".join(step["executor_id"].split(":", 2)[-1] for step in steps)
    if use_chinese:
        return f"计划：按顺序调用 {ordered}。当前路线已通过校验，可先直接执行；如需更强能力，再看可选推荐。"
    return f"Plan: execute {ordered} in order. The route passed validation, and optional recommendations remain available as upgrades."


def load_local_index_by_name(local_index):
    by_name = {}
    for entry in local_index:
        if entry.get("name"):
            by_name[entry["name"]] = entry
    return by_name


def merge_local_metadata(executors, local_index):
    index_by_name = load_local_index_by_name(local_index)
    merged = []
    for executor in executors:
        if executor.get("executor_type") == "skill" and executor.get("name") in index_by_name:
            merged.append(merge_executor_with_index(executor, index_by_name[executor["name"]]))
        else:
            merged.append(enrich_executor(executor))
    return dedupe_entries(merged, key_fields=("executor_id",))


def main():
    parser = argparse.ArgumentParser(description="Plan a unified skill + MCP route.")
    parser.add_argument("--task", required=True, help="Task description to route")
    parser.add_argument(
        "--base-dir",
        default=str(Path.home() / ".codex" / "skills" / "skill-router"),
        help="Path to the skill-router directory",
    )
    parser.add_argument(
        "--tool-home",
        action="append",
        default=[],
        help="Additional tool home to scan for skills and MCP manifests. Repeat to add multiple homes.",
    )
    parser.add_argument("--mcp-session-tools-file", help="Optional JSON file describing currently visible MCP tools")
    parser.add_argument("--mcp-session-resources-file", help="Optional JSON file describing currently visible MCP resources")
    parser.add_argument("--no-remote", action="store_true", help="Disable live remote recommendation lookups")
    parser.add_argument("--mock-model-response", help="Use a local JSON file instead of calling the model")
    parser.add_argument("--reasoning-provider", help="Override reasoning provider mode for debugging/testing")
    parser.add_argument(
        "--include-reasoning-input",
        action="store_true",
        help="Include the internal reasoning payload in the JSON output for debugging.",
    )
    parser.add_argument(
        "--include-reflection-trace",
        action="store_true",
        help="Include the model's internal reflection trace in the routing_decision output for debugging.",
    )
    args = parser.parse_args()

    config, local_index = load_router_assets(args.base_dir)
    executors, skill_roots, mcp_sources, discovery_warnings = discover_all_executors(
        base_dir=args.base_dir,
        explicit_homes=args.tool_home,
        session_tools_file=args.mcp_session_tools_file,
        session_resources_file=args.mcp_session_resources_file,
    )
    executors = merge_local_metadata(executors, local_index)
    task_info_seed = infer_task(args.task)

    reasoning_input, routing_decision = decide_route(
        task_info=task_info_seed,
        executors=executors,
        config=config,
        mode=config.get("mode", "explicit"),
        mock_response_path=args.mock_model_response,
        provider_override=args.reasoning_provider,
    )
    task_info = finalize_task_info(task_info_seed, routing_decision)
    validation_result = validate_route(
        task_info=task_info,
        decision=routing_decision,
        executors=executors,
        policy_constraints=config.get("policy_constraints", {}),
    )

    remote_entries = []
    remote_fetch_errors = []
    if not args.no_remote:
        remote_entries, remote_fetch_errors = fetch_remote_indexes(config)

    installed_executor_ids = {item["executor_id"] for item in executors if item.get("executor_type") == "skill"}
    required_recommendations = build_recommendations(
        task_info=task_info,
        missing_caps=routing_decision.get("missing_required_capabilities", []),
        local_index=local_index,
        remote_entries=remote_entries,
        installed_executor_ids=installed_executor_ids,
    )
    optional_recommendations = build_recommendations(
        task_info=task_info,
        missing_caps=routing_decision.get("missing_optional_capabilities", []),
        local_index=local_index,
        remote_entries=remote_entries,
        installed_executor_ids=installed_executor_ids,
    )

    chosen_plan = validation_result.get("chosen_plan") or {}
    output = {
        "mode": config.get("mode", "explicit"),
        "task": task_info["task"],
        "task_profile": {
            **task_info["task_profile"],
            "required_capabilities": task_info["required_capabilities"],
            "optional_support_capabilities": task_info["optional_support_capabilities"],
        },
        "discovered_executors": [
            {
                "executor_id": item["executor_id"],
                "executor_type": item["executor_type"],
                "name": item["name"],
                "source": item["source"],
                "tool_family": item["tool_family"],
                "capabilities": item.get("capabilities", []),
                "keywords": item.get("keywords", []),
                "description": item.get("description", ""),
                "constraints": item.get("constraints", {}),
                "invocation_ref": item.get("invocation_ref"),
            }
            for item in executors
        ],
        "discovered_skill_roots": skill_roots,
        "discovered_mcp_sources": mcp_sources,
        "routing_decision": {
            "task_understanding": routing_decision.get("task_understanding"),
            "task_profile": task_info["task_profile"],
            "needed_capabilities": routing_decision.get("needed_capabilities", []),
            "candidate_plans": routing_decision.get("candidate_plans", []),
            "chosen_plan": chosen_plan,
            "chosen_plan_reason": routing_decision.get("chosen_plan_reason"),
            "why_not_others": routing_decision.get("why_not_others", []),
        },
        "validation_result": {
            "is_valid": validation_result["is_valid"],
            "errors": validation_result["errors"],
            "warnings": discovery_warnings + validation_result["warnings"],
        },
        "recommended_install_required": required_recommendations,
        "recommended_install_optional": optional_recommendations,
        "user_summary": build_user_summary(args.task, validation_result, routing_decision),
        "remote_fetch_errors": remote_fetch_errors,
    }
    if args.include_reflection_trace:
        output["routing_decision"]["reflection_trace"] = routing_decision.get("reflection_trace", [])
    if args.include_reasoning_input:
        output["reasoning_input"] = reasoning_input
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    main()
