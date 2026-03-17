#!/usr/bin/env python3
import json


def build_executor_map(route_payload):
    return {item["executor_id"]: item for item in route_payload.get("discovered_executors", [])}


def preview_text(text, max_chars=240):
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def resolve_step_content(step, executor, resource_contents, mock_executor_results):
    candidates = [
        step.get("executor_id"),
        executor.get("executor_id"),
        executor.get("invocation_ref"),
        executor.get("name"),
    ]
    for key in candidates:
        if key and key in mock_executor_results:
            return mock_executor_results[key]
    if executor.get("executor_type") == "mcp_resource":
        for key in candidates:
            if key and key in resource_contents:
                return resource_contents[key]
    return None


def normalize_content_payload(payload):
    if payload is None:
        return None
    if isinstance(payload, str):
        return {"content": payload}
    if isinstance(payload, dict):
        if "content" in payload:
            return payload
        return {"content": json.dumps(payload, ensure_ascii=False)}
    return {"content": str(payload)}


def build_context_item(step, executor, payload):
    content = normalize_content_payload(payload) or {"content": ""}
    return {
        "executor_id": step["executor_id"],
        "executor_type": executor["executor_type"],
        "name": executor.get("name"),
        "content": content.get("content", ""),
        "content_preview": preview_text(content.get("content", "")),
    }


def build_context_preview(aggregated_context):
    previews = [item["content_preview"] for item in aggregated_context if item.get("content_preview")]
    return preview_text("\n\n".join(previews), max_chars=400)


def build_host_execution_request(step, executor, aggregated_context):
    return {
        "executor_id": step["executor_id"],
        "executor_type": executor["executor_type"],
        "name": executor.get("name"),
        "invocation_ref": executor.get("invocation_ref"),
        "purpose": step.get("purpose"),
        "required_inputs": step.get("required_inputs", []),
        "expected_output": step.get("expected_output"),
        "context_preview": build_context_preview(aggregated_context),
    }


def execute_selected_plan(route_payload, resource_contents=None, mock_executor_results=None, stop_on_host_handoff=True):
    resource_contents = resource_contents or {}
    mock_executor_results = mock_executor_results or {}
    validation_result = route_payload.get("validation_result", {})
    if not validation_result.get("is_valid", False):
        return {
            "is_runnable": False,
            "stopped_reason": "route_invalid",
            "errors": validation_result.get("errors", ["Route is not valid."]),
            "step_results": [],
            "aggregated_context": [],
        }

    chosen_plan = route_payload.get("routing_decision", {}).get("chosen_plan") or {}
    steps = chosen_plan.get("steps", [])
    executor_map = build_executor_map(route_payload)
    step_results = []
    aggregated_context = []
    stopped_reason = None

    for index, step in enumerate(steps, start=1):
        executor = executor_map.get(step.get("executor_id"))
        if not executor:
            step_results.append(
                {
                    "step_index": index,
                    "executor_id": step.get("executor_id"),
                    "status": "failed",
                    "error": f"Unknown executor '{step.get('executor_id')}'.",
                }
            )
            stopped_reason = "unknown_executor"
            break

        resolved_payload = resolve_step_content(step, executor, resource_contents, mock_executor_results)
        executor_type = executor.get("executor_type")

        if executor_type == "mcp_resource":
            if resolved_payload is None:
                step_results.append(
                    {
                        "step_index": index,
                        "executor_id": step["executor_id"],
                        "status": "missing_context",
                        "error": "No resource content was provided for this mcp_resource step.",
                    }
                )
                stopped_reason = "missing_context"
                break
            context_item = build_context_item(step, executor, resolved_payload)
            aggregated_context.append(context_item)
            step_results.append(
                {
                    "step_index": index,
                    "executor_id": step["executor_id"],
                    "status": "completed",
                    "output_type": "context",
                    "context_preview": context_item["content_preview"],
                }
            )
            continue

        if resolved_payload is not None:
            context_item = build_context_item(step, executor, resolved_payload)
            aggregated_context.append(context_item)
            step_results.append(
                {
                    "step_index": index,
                    "executor_id": step["executor_id"],
                    "status": "completed",
                    "output_type": "mock_result",
                    "context_preview": context_item["content_preview"],
                }
            )
            continue

        if executor_type in {"skill", "mcp_tool"}:
            step_results.append(
                {
                    "step_index": index,
                    "executor_id": step["executor_id"],
                    "status": "requires_host_execution",
                    "host_execution_request": build_host_execution_request(step, executor, aggregated_context),
                }
            )
            stopped_reason = "host_execution_required"
            if stop_on_host_handoff:
                break
            continue

        step_results.append(
            {
                "step_index": index,
                "executor_id": step["executor_id"],
                "status": "failed",
                "error": f"Unsupported executor type '{executor_type}'.",
            }
        )
        stopped_reason = "unsupported_executor"
        break

    completed_steps = sum(1 for item in step_results if item["status"] == "completed")
    return {
        "is_runnable": validation_result.get("is_valid", False),
        "plan_id": chosen_plan.get("plan_id"),
        "completed_steps": completed_steps,
        "total_steps": len(steps),
        "stopped_reason": stopped_reason,
        "step_results": step_results,
        "aggregated_context": aggregated_context,
        "next_host_action": next(
            (item["host_execution_request"] for item in step_results if item["status"] == "requires_host_execution"),
            None,
        ),
        "errors": [],
    }
