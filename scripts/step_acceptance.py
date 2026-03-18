#!/usr/bin/env python3
import json


def preview_text(text, max_chars=240):
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def normalize_payload(payload):
    if payload is None:
        return {"content": ""}
    if isinstance(payload, str):
        return {"content": payload}
    if isinstance(payload, dict):
        if "content" in payload:
            return {"content": str(payload.get("content", ""))}
        return {"content": json.dumps(payload, ensure_ascii=False)}
    return {"content": str(payload)}


def build_step_receipt(step, executor, payload, blueprint=None, artifacts=None, context_updates=None):
    blueprint = blueprint or {}
    normalized = normalize_payload(payload)
    content = normalized.get("content", "")
    visible_to_user = executor.get("executor_type") == "skill" or bool(content.strip())
    user_confirmation_required = executor.get("executor_type") == "skill" or (
        executor.get("executor_type", "").startswith("mcp_") and visible_to_user
    )
    return {
        "step_id": step.get("step_id"),
        "executor_id": step.get("executor_id"),
        "output_summary": preview_text(content) or blueprint.get("summary_template") or step.get("expected_output"),
        "artifacts": artifacts or [],
        "context_updates": context_updates or [],
        "visible_to_user": visible_to_user,
        "acceptance_criteria": list(blueprint.get("acceptance_criteria", [])) or [
            f"Output matches: {step.get('expected_output')}"
        ],
        "user_confirmation_required": user_confirmation_required,
    }


def build_acceptance_gate(step_receipt):
    required = bool(step_receipt.get("user_confirmation_required"))
    return {
        "status": "awaiting_user_confirmation" if required else "not_required",
        "step_id": step_receipt.get("step_id"),
        "output_summary": step_receipt.get("output_summary"),
        "acceptance_criteria": step_receipt.get("acceptance_criteria", []),
        "next_action_if_accepted": "continue_to_next_step",
        "next_action_if_rejected": "show_plan",
    }
