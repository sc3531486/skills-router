#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

from discovery_providers import discover_all_executors
from install_adapters import build_installation_plan
from model_router import build_host_reasoning_contract, decide_route
from orchestration_runner import build_initial_orchestration_state
from policy_validator import validate_orchestration_state, validate_route
from router_lib import (
    build_mcp_recommendations,
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


def build_user_summary(task_text, validation_result, routing_decision, mode, required_recommendations, mcp_recommendations):
    use_chinese = prefers_chinese(task_text)
    chosen_plan = validation_result.get("chosen_plan") or {}
    steps = chosen_plan.get("steps", [])
    if required_recommendations or mcp_recommendations:
        if use_chinese:
            return "计划：本地现有 skills 和 MCP 还不够，先向用户展示缺失能力与推荐安装项，并询问用户是否安装；如果批准安装，就自动调用对应安装执行器，安装后再用同一任务重新路由。"
        return "Plan: local skills and MCP are not sufficient yet, so first show the missing capabilities and recommended installs, ask the user for approval, auto-run the installation executor if approved, and rerun the route after installation."
    if not steps:
        return "计划：当前没有可直接执行的路线，先返回缺失能力与推荐项。" if use_chinese else "Plan: no executable route is available yet, so return gaps and recommendations first."
    ordered = " -> ".join(step["executor_id"].split(":", 2)[-1] for step in steps)
    if use_chinese:
        if mode == "explicit":
            return f"计划：建议按 {ordered} 的顺序协作。当前只展示编排结果，不进入第一步执行；等用户确认后再继续。"
        return f"计划：按顺序调用 {ordered}。当前路线已通过校验，可先直接执行；如需更强能力，再看可选推荐。"
    if mode == "explicit":
        return f"Plan: use {ordered} in order. For now, only show this orchestration result and do not start step one until the user confirms."
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


def build_host_handoff(task_text):
    if prefers_chinese(task_text):
        return {
            "summary": "由宿主模型基于 host_reasoning_request 完成反思式编排，再把结构化决策回传给 plan_route.py 做校验和落地。",
            "reflect": "宿主模型只能使用 host_reasoning_request.available_executors 里的 skill 和 MCP，先思考需要哪些能力，再输出符合 host_reasoning_contract 的 JSON。",
            "finalize_route": "将宿主模型产出的 JSON 保存为文件后，重新运行 plan_route.py，并传入 --host-decision-file <decision.json> 来完成最终路由。",
        }
    return {
        "summary": "The host model should perform the reflective routing from host_reasoning_request, then pass the structured decision back to plan_route.py for validation and finalization.",
        "reflect": "The host model must use only the executors listed in host_reasoning_request.available_executors, reflect on the needed capabilities, and emit JSON that matches host_reasoning_contract.",
        "finalize_route": "Save the host-produced JSON decision and rerun plan_route.py with --host-decision-file <decision.json> to finalize the route.",
    }


def build_installation_gate(task_info, required_recommendations, optional_recommendations, mcp_recommendations):
    needs_required_install = bool(required_recommendations)
    needs_required_mcp_install = bool(mcp_recommendations)
    needs_optional_install = bool(optional_recommendations)
    if not needs_required_install and not needs_optional_install and not needs_required_mcp_install:
        return {
            "requires_user_approval": False,
            "approval_scope": None,
            "recommended_targets": [],
            "approved_executor": None,
            "next_action_if_approved": None,
            "next_action_if_declined": None,
            "rerun_route_after_install": False,
            "rerun_task": task_info["task"],
        }

    approval_scope = "required" if (needs_required_install or needs_required_mcp_install) else "optional"
    recommended_targets = []
    if needs_required_install:
        recommended_targets.extend(required_recommendations)
    if needs_required_mcp_install:
        recommended_targets.extend(mcp_recommendations)
    if not recommended_targets:
        recommended_targets.extend(optional_recommendations)
    installation_plan = build_installation_plan(recommended_targets[0]) if recommended_targets else {
        "approved_executor": None,
        "host_action": None,
    }
    return {
        "requires_user_approval": True,
        "approval_scope": approval_scope,
        "recommended_targets": [
            {
                "name": item.get("name"),
                "source": item.get("source"),
                "repo": item.get("repo"),
                "install_url": item.get("install_url"),
                "matched_capabilities": item.get("matched_capabilities", []),
                "reasons": item.get("reasons", []),
                "provider_family": item.get("provider_family"),
                "install_mode": item.get("install_mode"),
                "supports_auto_install": item.get("supports_auto_install"),
            }
            for item in recommended_targets
        ],
        "approved_executor": installation_plan.get("approved_executor"),
        "host_action": installation_plan.get("host_action"),
        "next_action_if_approved": "install_and_rerun_route",
        "next_action_if_declined": "stay_with_current_route_or_rescope",
        "rerun_route_after_install": True,
        "rerun_task": task_info["task"],
    }


def build_final_plan(task_info, validation_result, routing_decision, required_recommendations, optional_recommendations, mcp_recommendations, mode):
    chosen_plan = validation_result.get("chosen_plan") or {}
    ordered_steps = [
        {
            "step_index": index + 1,
            "step_id": step.get("step_id"),
            "step_type": step.get("step_type"),
            "executor_id": step.get("executor_id"),
            "purpose": step.get("purpose"),
            "required_inputs": step.get("required_inputs", []),
            "expected_output": step.get("expected_output"),
            "reads_context_only": bool(step.get("reads_context_only", False)),
            "may_mutate": bool(step.get("may_mutate", False)),
        }
        for index, step in enumerate(chosen_plan.get("steps", []))
    ]
    installation_gate = build_installation_gate(task_info, required_recommendations, optional_recommendations, mcp_recommendations)
    route_valid = bool(validation_result["is_valid"] and not required_recommendations and not mcp_recommendations)
    must_pause_for_user = mode == "explicit"
    execution_ready = bool(route_valid and not must_pause_for_user)
    if must_pause_for_user and installation_gate["requires_user_approval"] and installation_gate["approval_scope"] == "required":
        next_action = "show_plan_and_ask_install_approval"
    elif must_pause_for_user:
        next_action = "show_plan_and_stop"
    elif installation_gate["requires_user_approval"] and installation_gate["approval_scope"] == "required":
        next_action = "ask_install_approval"
    else:
        next_action = "continue_execution" if execution_ready else "stop_for_required_capability_gap"
    return {
        "task": task_info["task"],
        "task_understanding": routing_decision.get("task_understanding"),
        "chosen_plan_id": chosen_plan.get("plan_id"),
        "summary": chosen_plan.get("summary"),
        "chosen_plan_reason": routing_decision.get("chosen_plan_reason"),
        "ordered_steps": ordered_steps,
        "validation": {
            "is_valid": validation_result["is_valid"],
            "errors": validation_result["errors"],
            "warnings": validation_result["warnings"],
        },
        "route_valid": route_valid,
        "execution_ready": execution_ready,
        "ready_after_user_confirmation": bool(route_valid and must_pause_for_user),
        "installation_gate": installation_gate,
        "presentation_contract": {
            "must_show_to_user_before_execution": must_pause_for_user,
            "must_show_fields": [
                "summary",
                "ordered_steps",
                "validation",
                "installation_gate",
                "recommended_install_required",
                "recommended_install_optional",
            ],
            "must_not_do_before_showing_plan": [
                "invoke downstream skills or MCP steps",
                "open browser or visual-assist prompts unrelated to the chosen plan",
                "ask optional execution questions before the route itself is visible",
                "start brainstorming or any other first-step workflow in the same reply",
            ] if must_pause_for_user else [],
        },
        "execution_gate": {
            "mode": mode,
            "requires_user_confirmation": must_pause_for_user,
            "next_action": next_action,
            "host_must_end_turn": must_pause_for_user,
        },
        "host_handoff_instructions": (
            (
                "Explicit router invocation: show the missing capabilities and recommended installs, ask whether to install them, auto-run the installer if approved, and rerun plan_route.py with the same task after installation."
                if installation_gate["requires_user_approval"] and installation_gate["approval_scope"] == "required"
                else "Explicit router invocation: show this plan to the user and end the turn. Do not invoke the first downstream step yet."
            )
            if not prefers_chinese(task_info["task"]) else
            (
                f"显式调用 Skill Router：先把缺失能力和推荐安装项展示给用户，询问用户是否安装；如果批准安装，由宿主模型调用 {installation_gate.get('approved_executor', {}).get('name', '对应安装执行器')} 自动完成安装，安装后用同一个任务重新运行 plan_route.py，再继续后续路线。"
                if installation_gate["requires_user_approval"] and installation_gate["approval_scope"] == "required"
                else "显式调用 Skill Router：先把这份计划展示给用户，然后结束当前回复。不要在这一条消息里直接进入第一个下游 skill。"
            )
        ),
        "missing_required_capabilities": routing_decision.get("missing_required_capabilities", []),
        "missing_optional_capabilities": routing_decision.get("missing_optional_capabilities", []),
        "recommended_install_required": required_recommendations,
        "recommended_install_optional": optional_recommendations,
    }


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
    parser.add_argument("--host-decision-file", help="Use a host-produced reasoning decision JSON file to finalize routing")
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
        host_decision_path=args.host_decision_file,
    )
    if routing_decision is None:
        host_handoff = build_host_handoff(task_info_seed["task"])
        output = {
            "mode": config.get("mode", "explicit"),
            "task": task_info_seed["task"],
            "task_profile": {
                **task_info_seed["task_profile"],
                "required_capabilities": task_info_seed["required_capabilities"],
                "optional_support_capabilities": task_info_seed["optional_support_capabilities"],
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
            "routing_status": "requires_host_reasoning",
            "next_host_action": "reflect_and_finalize_route",
            "host_reasoning_request": reasoning_input,
            "host_reasoning_contract": build_host_reasoning_contract(),
            "host_handoff_instructions": host_handoff,
            "user_summary": (
                "计划：已准备好反思式路由上下文，等待宿主模型基于这份上下文完成技能与 MCP 编排。"
                if prefers_chinese(args.task) else
                "Plan: the reflective routing context is ready; the host model should now choose the skill and MCP route."
            ),
            "remote_fetch_errors": [],
        }
        if args.include_reasoning_input:
            output["reasoning_input"] = reasoning_input
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return
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
    mcp_recommendations = build_mcp_recommendations(routing_decision.get("missing_executors", []))

    chosen_plan = validation_result.get("chosen_plan") or {}
    final_plan = build_final_plan(
        task_info=task_info,
        validation_result=validation_result,
        routing_decision=routing_decision,
        required_recommendations=required_recommendations,
        optional_recommendations=optional_recommendations,
        mcp_recommendations=mcp_recommendations,
        mode=config.get("mode", "explicit"),
    )
    output = {
        "routing_status": "completed",
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
            "minimal_high_quality_combo": routing_decision.get("minimal_high_quality_combo", []),
            "missing_executors": routing_decision.get("missing_executors", []),
            "step_acceptance_blueprint": routing_decision.get("step_acceptance_blueprint", []),
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
        "recommended_install_mcp": mcp_recommendations,
        "user_summary": build_user_summary(
            args.task,
            validation_result,
            routing_decision,
            config.get("mode", "explicit"),
            required_recommendations,
            mcp_recommendations,
        ),
        "final_plan": final_plan,
        "remote_fetch_errors": remote_fetch_errors,
    }
    output["orchestration_state"] = build_initial_orchestration_state(output)
    orchestration_validation = validate_orchestration_state(output["orchestration_state"])
    output["validation_result"]["is_valid"] = bool(
        output["validation_result"]["is_valid"] and orchestration_validation["is_valid"]
    )
    output["validation_result"]["errors"].extend(orchestration_validation["errors"])
    output["validation_result"]["warnings"].extend(orchestration_validation["warnings"])
    output["final_plan"]["validation"]["is_valid"] = output["validation_result"]["is_valid"]
    output["final_plan"]["validation"]["errors"] = output["validation_result"]["errors"]
    output["final_plan"]["validation"]["warnings"] = output["validation_result"]["warnings"]
    output["final_plan"]["route_valid"] = bool(
        output["validation_result"]["is_valid"]
        and not required_recommendations
        and not mcp_recommendations
    )
    output["final_plan"]["execution_ready"] = bool(
        output["final_plan"]["route_valid"] and not output["orchestration_state"].get("session_mode") == "explicit"
    )
    output["final_plan"]["ready_after_user_confirmation"] = bool(
        output["final_plan"]["route_valid"] and output["orchestration_state"].get("session_mode") == "explicit"
    )
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
