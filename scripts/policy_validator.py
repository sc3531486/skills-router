#!/usr/bin/env python3

import re


def build_executor_map(executors):
    return {item["executor_id"]: item for item in executors}


def find_plan(decision, plan_id):
    for plan in decision.get("candidate_plans", []):
        if plan.get("plan_id") == plan_id:
            return plan
    return None


DEPENDENCY_TOKEN_RE = re.compile(r"[a-z0-9]+")


def normalize_dependency_label(value):
    text = " ".join(str(value or "").strip().lower().split())
    return text


def dependency_tokens(value):
    return set(DEPENDENCY_TOKEN_RE.findall(normalize_dependency_label(value)))


def labels_match(required_input, produced_output):
    required_norm = normalize_dependency_label(required_input)
    produced_norm = normalize_dependency_label(produced_output)
    if not required_norm or not produced_norm:
        return False
    if required_norm == produced_norm:
        return True
    if required_norm in produced_norm or produced_norm in required_norm:
        return True
    required_tokens = dependency_tokens(required_norm)
    produced_tokens = dependency_tokens(produced_norm)
    overlap = required_tokens & produced_tokens
    return len(overlap) >= 2 or (overlap and required_tokens == produced_tokens)


def build_step_output_labels(step, executor):
    labels = []
    for raw_value in (
        step.get("expected_output"),
        step.get("purpose"),
        executor.get("name"),
    ):
        normalized = normalize_dependency_label(raw_value)
        if normalized and normalized not in labels:
            labels.append(normalized)
    return labels


def validate_route(task_info, decision, executors, policy_constraints=None):
    policy_constraints = policy_constraints or {}
    errors = []
    warnings = []
    executor_map = build_executor_map(executors)

    chosen_plan = find_plan(decision, decision.get("chosen_plan_id"))
    if not chosen_plan:
        return {
            "is_valid": False,
            "errors": [f"Chosen plan '{decision.get('chosen_plan_id')}' does not exist."],
            "warnings": [],
            "chosen_plan": None,
        }

    steps = chosen_plan.get("steps", [])
    task_profile = task_info.get("task_profile", {})
    bounded_request = bool(task_profile.get("bounded_request"))
    has_deliverable = bool(task_profile.get("deliverable"))

    if decision.get("missing_required_capabilities"):
        errors.append("Chosen route still reports missing required capabilities.")

    step_output_labels = []
    for step in steps:
        executor = executor_map.get(step.get("executor_id"), {})
        step_output_labels.append(build_step_output_labels(step, executor))

    available_outputs = []
    for index, step in enumerate(steps):
        executor_id = step.get("executor_id")
        step_type = step.get("step_type")
        if executor_id not in executor_map:
            errors.append(f"Step {index + 1} references unknown executor '{executor_id}'.")
            continue
        executor = executor_map[executor_id]
        if step_type != executor.get("executor_type"):
            errors.append(
                f"Step {index + 1} type '{step_type}' does not match executor type '{executor.get('executor_type')}'."
            )
        constraints = executor.get("constraints", {})
        if bounded_request and has_deliverable and executor.get("executor_type") == "skill" and constraints.get("process_only"):
            errors.append(f"Bounded artifact route may not include process-only skill '{executor.get('name')}'.")
        if executor.get("executor_type") == "mcp_resource" and not step.get("reads_context_only", False):
            errors.append(f"MCP resource step '{executor.get('name')}' must be marked reads_context_only=true.")
        if executor.get("executor_type") == "mcp_resource" and step.get("may_mutate", False):
            errors.append(f"MCP resource step '{executor.get('name')}' may not mutate state.")
        if constraints.get("mutating") and not policy_constraints.get("allow_mutating_mcp_tools", False):
            errors.append(f"Mutating MCP tool '{executor.get('name')}' is not allowed by current policy.")
        if constraints.get("context_only") and not step.get("reads_context_only", False):
            errors.append(f"Context-only executor '{executor.get('name')}' must stay context-only in the route.")

        for raw_input in step.get("required_inputs", []):
            required_input = normalize_dependency_label(raw_input)
            if not required_input:
                continue
            if any(labels_match(required_input, produced_output) for produced_output in available_outputs):
                continue
            future_step = None
            for future_index in range(index + 1, len(steps)):
                if any(labels_match(required_input, produced_output) for produced_output in step_output_labels[future_index]):
                    future_step = future_index + 1
                    break
            if future_step is not None:
                errors.append(
                    f"Step {index + 1} requires input '{raw_input}' before it is produced by step {future_step}."
                )

        available_outputs.extend(step_output_labels[index])

    if steps:
        last_executor = executor_map.get(steps[-1].get("executor_id"))
        if last_executor and last_executor.get("executor_type") == "mcp_resource":
            errors.append("Chosen plan may not end with an mcp_resource step.")

    seen_context_after_action = False
    non_context_seen = False
    for step in steps:
        executor = executor_map.get(step.get("executor_id"))
        if not executor:
            continue
        if executor.get("executor_type") == "mcp_resource":
            if non_context_seen:
                seen_context_after_action = True
        else:
            non_context_seen = True
    if seen_context_after_action:
        warnings.append("Route reads MCP resources after executable steps; verify the order is intentional.")

    return {
        "is_valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "chosen_plan": chosen_plan,
    }
