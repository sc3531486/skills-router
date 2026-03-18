#!/usr/bin/env python3
from copy import deepcopy

from step_acceptance import build_acceptance_gate


def _chosen_plan(route_payload):
    return (route_payload.get("routing_decision") or {}).get("chosen_plan") or {}


def _steps(route_payload):
    return list(_chosen_plan(route_payload).get("steps", []))


def _after_show_action(route_payload):
    installation_gate = ((route_payload.get("final_plan") or {}).get("installation_gate") or {})
    if installation_gate.get("requires_user_approval") and installation_gate.get("approval_scope") == "required":
        return "ask_install_approval"
    if _steps(route_payload):
        return "execute_step"
    return "finish_route"


def build_initial_orchestration_state(route_payload):
    steps = _steps(route_payload)
    first_step_id = steps[0].get("step_id") if steps else None
    return {
        "session_mode": route_payload.get("mode", "explicit"),
        "route_phase": "planned",
        "chosen_plan": {
            "plan_id": _chosen_plan(route_payload).get("plan_id"),
            "steps": steps,
        },
        "minimal_high_quality_combo": (route_payload.get("routing_decision") or {}).get("minimal_high_quality_combo", []),
        "missing_executors": (route_payload.get("routing_decision") or {}).get("missing_executors", []),
        "installation_gate": ((route_payload.get("final_plan") or {}).get("installation_gate") or {}),
        "acceptance_gate": {
            "status": "pending_execution" if first_step_id else "not_required",
            "step_id": first_step_id,
        },
        "current_step_index": 0,
        "completed_step_ids": [],
        "next_host_action": "show_plan",
        "after_show_action": _after_show_action(route_payload),
    }


def advance_orchestration_state(state, event):
    state = deepcopy(state)
    event = event or {}
    event_type = event.get("type")
    steps = state.get("chosen_plan", {}).get("steps", [])

    if event_type == "plan_shown":
        if state.get("after_show_action") == "ask_install_approval":
            state["route_phase"] = "awaiting_install_approval"
            state["next_host_action"] = "ask_install_approval"
        elif state.get("after_show_action") == "execute_step":
            state["route_phase"] = "awaiting_step_execution"
            state["next_host_action"] = "execute_step"
        else:
            state["route_phase"] = "completed"
            state["next_host_action"] = "finish_route"
        return state

    if event_type == "step_executed":
        receipt = event.get("step_receipt", {})
        acceptance_gate = build_acceptance_gate(receipt)
        state["acceptance_gate"] = acceptance_gate
        if acceptance_gate["status"] == "awaiting_user_confirmation":
            state["route_phase"] = "awaiting_step_acceptance"
            state["next_host_action"] = "ask_step_acceptance"
        else:
            state["route_phase"] = "awaiting_step_execution"
            state["next_host_action"] = "continue_to_next_step"
        return state

    if event_type == "step_accepted":
        if not event.get("accepted", False):
            state["route_phase"] = "planned"
            state["next_host_action"] = "show_plan"
            return state
        current_index = int(state.get("current_step_index", 0))
        if current_index < len(steps):
            current_step = steps[current_index]
            state["completed_step_ids"].append(current_step.get("step_id"))
        next_index = current_index + 1
        state["current_step_index"] = next_index
        if next_index >= len(steps):
            state["route_phase"] = "completed"
            state["next_host_action"] = "finish_route"
            state["acceptance_gate"] = {"status": "completed"}
        else:
            state["route_phase"] = "awaiting_step_execution"
            state["next_host_action"] = "continue_to_next_step"
            state["acceptance_gate"] = {
                "status": "pending_execution",
                "step_id": steps[next_index].get("step_id"),
            }
        return state

    return state
