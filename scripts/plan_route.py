#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

from discovery_providers import discover_all_executors
from install_adapters import build_installation_plan
from model_router import build_host_reasoning_contract, build_reflection_roles, decide_route
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
    is_route_visible,
    load_router_assets,
    merge_executor_with_index,
    prefers_chinese,
)


def build_routing_usage_policy(task_text, config):
    use_chinese = prefers_chinese(task_text)
    session_routing = dict(config.get("session_routing", {}))
    sticky = bool(session_routing.get("sticky_after_explicit_activation", True))
    auto_reroute = bool(session_routing.get("auto_reroute_on_trigger", True))
    first_use_only = bool(session_routing.get("require_explicit_invocation_only_for_first_use", True))
    if use_chinese:
        return {
            "principle": "skill-router 不是只在第一次需求时使用，也不是整段对话每句话都重跑；它应在关键节点重新编排。",
            "session_activation": {
                "activation_mode": "explicit-first-then-sticky" if sticky and first_use_only else "explicit-every-time",
                "sticky_after_explicit_activation": sticky,
                "require_explicit_invocation_only_for_first_use": first_use_only,
                "host_instruction": (
                    "用户第一次明确说使用 skill-router 后，本会话应视为已启用自动调度；后续命中重路由触发条件时，宿主可自动再次调用 router，而不需要用户重复点名。"
                    if sticky and first_use_only else
                    "每次需要重新路由时，都要求用户再次明确点名使用 skill-router。"
                ),
            },
            "auto_reroute_policy": {
                "enabled": auto_reroute,
                "host_should_reroute_automatically_when_triggered": auto_reroute and sticky,
                "host_should_continue_current_route_by_default": True,
            },
            "run_router_now_when": [
                "第一次收到明确任务，需要决定最合适的 skills + MCP 组合时",
                "任务进入新阶段，主产物或主要工作类型发生变化时",
                "安装缺失 skill 或 MCP 之后，需要基于新能力重跑路线时",
                "某一步验收未通过，或需要改线、回退、重做时",
                "发现低成本高价值的补强空间，可能值得引入新的 support skill 或 MCP 时",
                "用户目标、质量要求、受众或约束明显变化时",
            ],
            "do_not_reroute_when": [
                "只是同一阶段内的小澄清、小修辞或轻微参数调整时",
                "当前路线仍然适配，而且没有新增能力缺口或质量风险时",
            ],
            "default_host_behavior": [
                "首次显式调用 skill-router 时先展示路线",
                "后续优先按当前已确认路线执行",
                "只有命中重新编排触发条件时才再次调用 skill-router",
            ],
            "reroute_labels": [
                "initial-routing",
                "stage-rerouting",
                "post-install-rerouting",
                "acceptance-rerouting",
                "improvement-rerouting",
                "goal-change-rerouting",
            ],
        }
    return {
        "principle": "skill-router should not run only once at the start, but it also should not rerun on every single turn; it should reroute at meaningful orchestration boundaries.",
        "session_activation": {
            "activation_mode": "explicit-first-then-sticky" if sticky and first_use_only else "explicit-every-time",
            "sticky_after_explicit_activation": sticky,
            "require_explicit_invocation_only_for_first_use": first_use_only,
            "host_instruction": (
                "After the user explicitly invokes skill-router once, treat the rest of the conversation as router-armed and rerun automatically on reroute triggers without requiring the user to repeat the skill name."
                if sticky and first_use_only else
                "Require the user to explicitly invoke skill-router again every time rerouting is needed."
            ),
        },
        "auto_reroute_policy": {
            "enabled": auto_reroute,
            "host_should_reroute_automatically_when_triggered": auto_reroute and sticky,
            "host_should_continue_current_route_by_default": True,
        },
        "run_router_now_when": [
            "A clear task arrives and the host needs the initial skill + MCP orchestration",
            "The work enters a new stage and the primary deliverable or work mode changes",
            "A missing skill or MCP has just been installed and the route should be rebuilt with the new capability",
            "A step fails acceptance or the host needs to redo, roll back, or rewrite the route",
            "A low-cost, high-value improvement opportunity suggests that another support skill or MCP should be added",
            "The user's goal, quality bar, audience, or constraints materially change",
        ],
        "do_not_reroute_when": [
            "The user is only making a small clarification or a minor same-stage tweak",
            "The current route still fits and no new capability gap or quality risk has appeared",
        ],
        "default_host_behavior": [
            "Show the route first on the initial explicit skill-router invocation",
            "Then continue executing the currently accepted route",
            "Only call skill-router again when a reroute trigger is hit",
        ],
        "reroute_labels": [
            "initial-routing",
            "stage-rerouting",
            "post-install-rerouting",
            "acceptance-rerouting",
            "improvement-rerouting",
            "goal-change-rerouting",
        ],
    }


def build_host_auto_routing_contract(task_text, config):
    use_chinese = prefers_chinese(task_text)
    session_routing = dict(config.get("session_routing", {}))
    sticky = bool(session_routing.get("sticky_after_explicit_activation", True))
    auto_reroute = bool(session_routing.get("auto_reroute_on_trigger", True))
    if use_chinese:
        return {
            "summary": "给宿主的极简自动路由规则：先显式启用一次，后续默认继续当前路线，只有命中触发条件时才自动重路由。",
            "assumption": "当前会话已经在首次显式调用 skill-router 后进入 router-armed 状态。",
            "default_action": "continue-current-route",
            "triggered_action": "reroute-now",
            "requires_first_explicit_activation": True,
            "sticky_after_explicit_activation": sticky,
            "auto_reroute_enabled": auto_reroute and sticky,
            "decision_rules": [
                {
                    "if": "还没有已确认路线，或者这是本任务第一次正式编排",
                    "then": "reroute-now",
                    "label": "initial-routing",
                },
                {
                    "if": "出现阶段切换、安装完成、验收失败、需要主动补强、或用户目标/约束明显变化",
                    "then": "reroute-now",
                    "label": "reroute-trigger-hit",
                },
                {
                    "if": "以上情况都没有发生",
                    "then": "继续当前路线",
                    "label": "continue-current-route",
                },
            ],
        }
    return {
        "summary": "Minimal host-side auto-routing rules: explicitly arm skill-router once, continue the accepted route by default, and reroute only when a trigger is hit.",
        "assumption": "The conversation is already router-armed after the first explicit skill-router invocation.",
        "default_action": "continue-current-route",
        "triggered_action": "reroute-now",
        "requires_first_explicit_activation": True,
        "sticky_after_explicit_activation": sticky,
        "auto_reroute_enabled": auto_reroute and sticky,
        "decision_rules": [
            {
                "if": "There is no accepted route yet or this is the first formal orchestration for the task",
                "then": "reroute-now",
                "label": "initial-routing",
            },
            {
                "if": "A stage change, post-install refresh, failed acceptance, proactive improvement trigger, or goal/constraint change occurs",
                "then": "reroute-now",
                "label": "reroute-trigger-hit",
            },
            {
                "if": "None of the above happened",
                "then": "continue-current-route",
                "label": "continue-current-route",
            },
        ],
    }


def build_host_route_signal(task_text, routing_status):
    use_chinese = prefers_chinese(task_text)
    if routing_status == "requires_host_reasoning":
        return {
            "router_state": "armed",
            "host_next_route_decision": "reroute-now",
            "host_reroute_trigger_matched": True,
            "matched_trigger_label": "initial-routing",
            "reason": (
                "当前还没有可继续执行的已确认路线；宿主应先完成这次初始反思式路由，再进入后续执行。"
                if use_chinese else
                "There is no accepted route to continue yet; the host should finish this initial reflective routing pass before execution."
            ),
        }
    return {
        "router_state": "armed",
        "host_next_route_decision": "continue-current-route",
        "host_reroute_trigger_matched": False,
        "matched_trigger_label": None,
        "reason": (
            "当前已经有一条可展示的路线；宿主默认继续这条路线，只有命中重路由触发条件时才重新调用 router。"
            if use_chinese else
            "A route is already available; the host should continue it by default and rerun the router only when a reroute trigger is hit."
        ),
    }


def build_host_turn_signal(
    task_text,
    routing_status,
    next_host_action,
    requires_user_visible_message,
    must_end_turn,
    after_user_confirmation_action=None,
):
    use_chinese = prefers_chinese(task_text)
    if routing_status == "requires_host_reasoning":
        reason = (
            "这一步先由宿主模型完成反思式路由，不需要先向用户展示下游执行内容。"
            if use_chinese else
            "The host should complete the reflective routing pass first before showing or executing downstream work."
        )
    else:
        reason = (
            "当前路线已经生成，宿主应按本轮信号推进，而不是自己重新拼接执行顺序。"
            if use_chinese else
            "A route is already available; the host should follow this turn signal instead of reconstructing the next step ad hoc."
        )
    return {
        "next_host_action": next_host_action,
        "requires_user_visible_message": bool(requires_user_visible_message),
        "must_end_turn": bool(must_end_turn),
        "after_user_confirmation_action": after_user_confirmation_action,
        "reason": reason,
    }


def build_routing_status_card(task_text, routing_status, host_turn_signal, final_plan=None, orchestration_state=None):
    use_chinese = prefers_chinese(task_text)
    if routing_status == "requires_host_reasoning":
        return {
            "phase": "reflective-routing",
            "headline": (
                "宿主正在完成反思式路由"
                if use_chinese else
                "The host is completing reflective routing"
            ),
            "user_action": "none",
            "next_step": "host-reflect",
            "waiting_for_user": False,
            "reason": host_turn_signal.get("reason", ""),
        }

    final_plan = final_plan or {}
    installation_gate = final_plan.get("installation_gate", {})
    execution_gate = final_plan.get("execution_gate", {})

    if installation_gate.get("requires_user_approval"):
        return {
            "phase": "install-approval",
            "headline": (
                "等待用户批准安装缺失能力"
                if use_chinese else
                "Waiting for user approval to install missing capability"
            ),
            "user_action": "approve-install",
            "next_step": "install-and-reroute",
            "waiting_for_user": True,
            "reason": host_turn_signal.get("reason", ""),
        }

    if execution_gate.get("requires_user_confirmation"):
        return {
            "phase": "plan-ready",
            "headline": (
                "路线已准备好，等待用户确认"
                if use_chinese else
                "The route is ready and waiting for user confirmation"
            ),
            "user_action": "confirm-route",
            "next_step": "execute-step",
            "waiting_for_user": True,
            "reason": host_turn_signal.get("reason", ""),
        }

    route_phase = (orchestration_state or {}).get("route_phase")
    if route_phase == "completed":
        return {
            "phase": "completed",
            "headline": (
                "当前路线已完成"
                if use_chinese else
                "The current route is completed"
            ),
            "user_action": "none",
            "next_step": "done",
            "waiting_for_user": False,
            "reason": host_turn_signal.get("reason", ""),
        }

    return {
        "phase": "executing",
        "headline": (
            "当前路线正在推进"
            if use_chinese else
            "The current route is in progress"
        ),
        "user_action": "none",
        "next_step": host_turn_signal.get("next_host_action"),
        "waiting_for_user": False,
        "reason": host_turn_signal.get("reason", ""),
    }


def normalize_role_findings(task_text, routing_decision):
    role_titles = {
        item["role_id"]: item.get("title", item["role_id"])
        for item in build_reflection_roles({"task": task_text})
    }
    findings_by_id = {
        item.get("role_id"): item
        for item in routing_decision.get("role_findings", [])
        if item.get("role_id")
    }
    ordered = []
    for role_id in role_titles:
        finding = findings_by_id.get(role_id)
        if not finding:
            continue
        ordered.append(
            {
                "role_id": role_id,
                "title": role_titles[role_id],
                "conclusion": finding.get("conclusion", ""),
                "concerns": finding.get("concerns", []),
                "suggested_capabilities": finding.get("suggested_capabilities", []),
            }
        )
    for role_id, finding in findings_by_id.items():
        if role_id in role_titles:
            continue
        ordered.append(
            {
                "role_id": role_id,
                "title": role_id,
                "conclusion": finding.get("conclusion", ""),
                "concerns": finding.get("concerns", []),
                "suggested_capabilities": finding.get("suggested_capabilities", []),
            }
        )
    return ordered


def build_quality_summary(task_text, routing_decision):
    use_chinese = prefers_chinese(task_text)
    completion = routing_decision.get("completion_assessment", {})
    quality_bar = completion.get("quality_bar", "best-practical")
    second_pass_review = routing_decision.get("second_pass_review", {})
    proactive_actions = second_pass_review.get("follow_up_actions", [])
    if use_chinese:
        if quality_bar == "best-practical":
            base = "这条路线不是只按“能做”来选，还额外经过交付、质量、设计/编辑三个角色的反思，并且通过了第二轮高标准复查。"
            if proactive_actions:
                return f"{base} 还会主动补强：{'；'.join(proactive_actions)}。"
            return base
        if quality_bar == "strong":
            base = "这条路线已经过交付、质量、设计/编辑三个角色的补强检查，并且做了第二轮复查。"
            if proactive_actions:
                return f"{base} 还会主动补强：{'；'.join(proactive_actions)}。"
            return base
        return "这条路线已经过角色分工式反思，但当前仍以满足基本目标为主。"
    if quality_bar == "best-practical":
        base = "This route was not chosen only for basic feasibility; it was also reviewed through delivery, quality, and design/editor roles and passed a second-pass quality review."
        if proactive_actions:
            return f"{base} It will also proactively strengthen: {'; '.join(proactive_actions)}."
        return base
    if quality_bar == "strong":
        base = "This route was strengthened through delivery, quality, and design/editor reflection and a second-pass review before selection."
        if proactive_actions:
            return f"{base} It will also proactively strengthen: {'; '.join(proactive_actions)}."
        return base
    return "This route went through role-split reflection, but it currently focuses on the baseline outcome."


def build_quality_reflection(task_text, routing_decision):
    completion = routing_decision.get("completion_assessment", {})
    second_pass_review = routing_decision.get("second_pass_review", {})
    quality_gate = routing_decision.get("quality_gate", {})
    return {
        "quality_bar": completion.get("quality_bar", "best-practical"),
        "baseline_satisfied": bool(completion.get("baseline_satisfied", True)),
        "reason": completion.get("reason", ""),
        "quality_risks": completion.get("quality_risks", []),
        "optimization_opportunities": completion.get("optimization_opportunities", []),
        "quality_gate": {
            "status": quality_gate.get("status"),
            "reason": quality_gate.get("reason", ""),
            "blocking_issues": quality_gate.get("blocking_issues", []),
        },
        "second_pass_review": {
            "verdict": second_pass_review.get("verdict"),
            "reason": second_pass_review.get("reason", ""),
            "follow_up_actions": second_pass_review.get("follow_up_actions", []),
        },
        "role_highlights": normalize_role_findings(task_text, routing_decision),
    }


def build_proactive_improvement_loop(routing_decision):
    second_pass_review = routing_decision.get("second_pass_review", {})
    blueprint_by_step = []
    for item in routing_decision.get("step_acceptance_blueprint", []):
        checks = list(item.get("improvement_checks", []))
        if not checks:
            continue
        blueprint_by_step.append(
            {
                "step_id": item.get("step_id"),
                "improvement_checks": checks,
            }
        )
    return {
        "second_pass_follow_up_actions": second_pass_review.get("follow_up_actions", []),
        "step_level_improvement_checks": blueprint_by_step,
    }


def build_user_summary(task_text, validation_result, routing_decision, mode, required_recommendations, mcp_recommendations):
    use_chinese = prefers_chinese(task_text)
    chosen_plan = validation_result.get("chosen_plan") or {}
    steps = chosen_plan.get("steps", [])
    quality_summary = build_quality_summary(task_text, routing_decision)
    if required_recommendations or mcp_recommendations:
        if use_chinese:
            return f"计划：本地现有 skills 和 MCP 还不够，先向用户展示缺失能力与推荐安装项，并询问用户是否安装；如果批准安装，就自动调用对应安装执行器，安装后再用同一任务重新路由。{quality_summary}"
        return f"Plan: local skills and MCP are not sufficient yet, so first show the missing capabilities and recommended installs, ask the user for approval, auto-run the installation executor if approved, and rerun the route after installation. {quality_summary}"
    if not steps:
        return (
            f"计划：当前没有可直接执行的路线，先返回缺失能力与推荐项。{quality_summary}"
            if use_chinese else
            f"Plan: no executable route is available yet, so return gaps and recommendations first. {quality_summary}"
        )
    ordered = " -> ".join(step["executor_id"].split(":", 2)[-1] for step in steps)
    if use_chinese:
        if mode == "explicit":
            return f"计划：建议按 {ordered} 的顺序协作。当前只展示编排结果，不进入第一步执行；等用户确认后再继续。{quality_summary}"
        return f"计划：按顺序调用 {ordered}。当前路线已通过校验，可先直接执行；如需更强能力，再看可选推荐。{quality_summary}"
    if mode == "explicit":
        return f"Plan: use {ordered} in order. For now, only show this orchestration result and do not start step one until the user confirms. {quality_summary}"
    return f"Plan: execute {ordered} in order. The route passed validation, and optional recommendations remain available as upgrades. {quality_summary}"


def build_executor_lookup_maps(entries):
    by_name = {}
    by_type_and_name = {}
    for entry in entries:
        name = entry.get("name")
        if not name:
            continue
        by_name[name] = entry
        by_type_and_name[(entry.get("executor_type"), name)] = entry
    return by_name, by_type_and_name


def merge_local_metadata(executors, local_index, executor_profiles):
    index_by_name, index_by_type_and_name = build_executor_lookup_maps(local_index)
    profile_by_name, profile_by_type_and_name = build_executor_lookup_maps(executor_profiles)
    merged = []
    for executor in executors:
        merged_executor = enrich_executor(executor)
        index_entry = index_by_type_and_name.get((executor.get("executor_type"), executor.get("name")))
        if index_entry is None and executor.get("executor_type") == "skill":
            index_entry = index_by_name.get(executor.get("name"))
        if index_entry is not None:
            merged_executor = merge_executor_with_index(merged_executor, index_entry)
        profile_entry = profile_by_type_and_name.get((executor.get("executor_type"), executor.get("name")))
        if profile_entry is None and executor.get("executor_type") == "skill":
            profile_entry = profile_by_name.get(executor.get("name"))
        if profile_entry is not None:
            merged_executor = merge_executor_with_index(merged_executor, profile_entry)
        if is_route_visible(merged_executor):
            merged.append(merged_executor)
    return dedupe_entries(merged, key_fields=("executor_id",))


def build_host_handoff(task_text):
    if prefers_chinese(task_text):
        return {
            "summary": "由宿主模型基于 host_reasoning_request 完成反思式编排，再把结构化决策回传给 plan_route.py 做校验和落地。",
            "reflect": "宿主模型只能使用 host_reasoning_request.available_executors 里的 skill 和 MCP，并先按 delivery-role、quality-critic-role、design-editor-role 三个角色完成反思，再输出符合 host_reasoning_contract 的 JSON。",
            "finalize_route": "将宿主模型产出的 JSON 保存为文件后，重新运行 plan_route.py，并传入 --host-decision-file <decision.json> 来完成最终路由。",
        }
    return {
        "summary": "The host model should perform the reflective routing from host_reasoning_request, then pass the structured decision back to plan_route.py for validation and finalization.",
        "reflect": "The host model must use only the executors listed in host_reasoning_request.available_executors, reflect through delivery-role, quality-critic-role, and design-editor-role first, then emit JSON that matches host_reasoning_contract.",
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
        "quality_summary": build_quality_summary(task_info["task"], routing_decision),
        "quality_reflection": build_quality_reflection(task_info["task"], routing_decision),
        "proactive_improvement_loop": build_proactive_improvement_loop(routing_decision),
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

    config, local_index, executor_profiles = load_router_assets(args.base_dir)
    executors, skill_roots, mcp_sources, discovery_warnings = discover_all_executors(
        base_dir=args.base_dir,
        explicit_homes=args.tool_home,
        session_tools_file=args.mcp_session_tools_file,
        session_resources_file=args.mcp_session_resources_file,
    )
    executors = merge_local_metadata(executors, local_index, executor_profiles)
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
            "routing_usage_policy": build_routing_usage_policy(task_info_seed["task"], config),
            "host_auto_routing_contract": build_host_auto_routing_contract(task_info_seed["task"], config),
            "host_route_signal": build_host_route_signal(task_info_seed["task"], "requires_host_reasoning"),
            "host_turn_signal": build_host_turn_signal(
                task_info_seed["task"],
                "requires_host_reasoning",
                "reflect_and_finalize_route",
                False,
                False,
            ),
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
                    "capability_groups": item.get("capability_groups", []),
                    "preferred_task_stages": item.get("preferred_task_stages", []),
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
                "计划：已准备好反思式路由上下文，等待宿主模型先以交付、质量、设计/编辑三个角色完成反思，再决定技能与 MCP 编排。"
                if prefers_chinese(args.task) else
                "Plan: the reflective routing context is ready; the host model should now reflect through delivery, quality, and design/editor roles before choosing the skill and MCP route."
            ),
            "remote_fetch_errors": [],
        }
        output["routing_status_card"] = build_routing_status_card(
            task_info_seed["task"],
            "requires_host_reasoning",
            output["host_turn_signal"],
        )
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
        "routing_usage_policy": build_routing_usage_policy(task_info["task"], config),
        "host_auto_routing_contract": build_host_auto_routing_contract(task_info["task"], config),
        "host_route_signal": build_host_route_signal(task_info["task"], "completed"),
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
                "capability_groups": item.get("capability_groups", []),
                "preferred_task_stages": item.get("preferred_task_stages", []),
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
            "role_findings": normalize_role_findings(task_info["task"], routing_decision),
            "completion_assessment": routing_decision.get("completion_assessment", {}),
            "quality_gate": routing_decision.get("quality_gate", {}),
            "second_pass_review": routing_decision.get("second_pass_review", {}),
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
    output["host_turn_signal"] = build_host_turn_signal(
        task_info["task"],
        "completed",
        output["orchestration_state"].get("next_host_action"),
        output["final_plan"]["presentation_contract"].get("must_show_to_user_before_execution", False)
        or output["final_plan"]["execution_gate"].get("requires_user_confirmation", False),
        output["final_plan"]["execution_gate"].get("host_must_end_turn", False),
        output["orchestration_state"].get("after_show_action"),
    )
    output["routing_status_card"] = build_routing_status_card(
        task_info["task"],
        "completed",
        output["host_turn_signal"],
        final_plan=output["final_plan"],
        orchestration_state=output["orchestration_state"],
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
