#!/usr/bin/env python3
import json
import os
import tomllib
import urllib.request
from pathlib import Path


from router_lib import (
    expand_path,
    prefers_chinese,
    prepare_reasoning_executors,
    summarize_executor_for_reasoning,
)


def load_json(path_text):
    with open(expand_path(path_text), "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_toml(path_text):
    with open(expand_path(path_text), "rb") as handle:
        return tomllib.load(handle)


def get_nested(data, dotted_key, default=None):
    current = data
    for key in dotted_key.split("."):
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def normalize_reasoning_config(config):
    reasoning = dict(config.get("reasoning", {}))
    reasoning.setdefault("provider_mode", "host")
    reasoning.setdefault("host_tool_family", "codex")
    reasoning.setdefault("response_timeout_seconds", 45)
    stage_one = dict(reasoning.get("stage_one", {}))
    stage_one.setdefault("enabled", True)
    stage_one.setdefault("candidate_limit", 12)
    stage_one.setdefault("keep_all_under", 10)
    stage_one.setdefault("description_max_chars", 140)
    stage_one.setdefault("keywords_limit", 8)
    stage_one.setdefault("capabilities_limit", 8)
    reasoning["stage_one"] = stage_one
    return reasoning


def load_host_model_settings(reasoning_config):
    tool_family = reasoning_config.get("host_tool_family", "codex")
    if tool_family != "codex":
        raise RuntimeError(f"Host model adapter for '{tool_family}' is not implemented; switch to external mode.")

    config_path = reasoning_config.get("codex_config_path") or str(Path.home() / ".codex" / "config.toml")
    auth_path = reasoning_config.get("codex_auth_path") or str(Path.home() / ".codex" / "auth.json")
    config_toml = load_toml(config_path)
    auth_json = load_json(auth_path)

    provider_name = config_toml.get("model_provider") or config_toml.get("model_providers", {}).keys()
    model = config_toml.get("model")
    reasoning_effort = config_toml.get("model_reasoning_effort", "high")
    provider_key = config_toml.get("model_provider", "custom")
    provider_config = get_nested(config_toml, f"model_providers.{provider_key}", {})
    base_url = provider_config.get("base_url")
    if not base_url or not model:
        raise RuntimeError("Codex host model config is incomplete.")

    api_key = auth_json.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Codex auth.json does not contain OPENAI_API_KEY.")

    if base_url.endswith("/v1"):
        endpoint = f"{base_url}/responses"
    elif base_url.endswith("/responses"):
        endpoint = base_url
    else:
        endpoint = f"{base_url}/v1/responses"

    return {
        "endpoint": endpoint,
        "api_key": api_key,
        "model": model,
        "reasoning_effort": reasoning_effort,
    }


def build_reasoning_input(task_info, executors, policy_constraints, mode, stage_one_meta=None, summary_config=None):
    summary_config = summary_config or {}
    return {
        "task": task_info["task"],
        "task_profile_seed": task_info["task_profile"],
        "required_capability_hints": task_info.get("required_capabilities", []),
        "optional_support_capability_hints": task_info.get("optional_support_capabilities", []),
        "available_executors": [
            summarize_executor_for_reasoning(item, summary_config)
            for item in executors
        ],
        "stage_one_selection": stage_one_meta or {},
        "policy_constraints": policy_constraints,
        "missing_capabilities_if_any": [],
        "execution_mode": mode,
        "user_language": task_info["task_profile"].get("user_language", "zh" if prefers_chinese(task_info["task"]) else "en"),
    }


def build_model_messages(reasoning_input):
    system_prompt = """
You are the decision engine for a skill router.
You must select and sequence only the available executors you are given.
Do not invent executor ids.
Do not use process-only skills for bounded artifact requests.
Do not use mcp_resource as the final artifact-producing step.
Treat task_profile_seed and capability hints as weak heuristic inputs that you may correct.
Return valid JSON only.

Required JSON shape:
{
  "task_understanding": "string",
  "task_profile": {
    "deliverable": "string|null",
    "actions": ["string"],
    "quality_goals": ["string"],
    "bounded_request": true,
    "process_intents": ["string"],
    "user_language": "string"
  },
  "needed_capabilities": ["string"],
  "required_capabilities": ["string"],
  "optional_support_capabilities": ["string"],
  "minimal_high_quality_combo": [
    {
      "executor_id": "string",
      "role": "primary|support|context",
      "why": "string"
    }
  ],
  "missing_executors": [
    {
      "executor_type": "skill|mcp_tool|mcp_resource",
      "name": "string",
      "provider_family": "string",
      "reason": "string"
    }
  ],
  "step_acceptance_blueprint": [
    {
      "step_id": "string",
      "summary_template": "string",
      "acceptance_criteria": ["string"]
    }
  ],
  "candidate_plans": [
    {
      "plan_id": "string",
      "summary": "string",
      "steps": [
        {
          "step_id": "string",
          "step_type": "skill|mcp_tool|mcp_resource",
          "executor_id": "string",
          "purpose": "string",
          "required_inputs": ["string"],
          "expected_output": "string",
          "reads_context_only": true,
          "may_mutate": false
        }
      ],
      "pros": ["string"],
      "cons": ["string"]
    }
  ],
  "chosen_plan_id": "string",
  "chosen_plan_reason": "string",
  "why_not_others": ["string"],
  "missing_required_capabilities": ["string"],
  "missing_optional_capabilities": ["string"],
  "reflection_trace": [
    {
      "focus": "task-profile|capability|executor|plan",
      "subject": "string",
      "decision": "string",
      "reason": "string"
    }
  ]
}
""".strip()
    user_prompt = json.dumps(reasoning_input, ensure_ascii=False, indent=2)
    return system_prompt, user_prompt


def build_host_reasoning_contract():
    return {
        "required_keys": [
            "task_understanding",
            "task_profile",
            "needed_capabilities",
            "required_capabilities",
            "optional_support_capabilities",
            "minimal_high_quality_combo",
            "missing_executors",
            "step_acceptance_blueprint",
            "candidate_plans",
            "chosen_plan_id",
            "chosen_plan_reason",
            "why_not_others",
            "missing_required_capabilities",
            "missing_optional_capabilities",
            "reflection_trace",
        ],
        "notes": [
            "Use only the available executors from host_reasoning_request.available_executors.",
            "Do not invent executor ids.",
            "Open-ended tasks may choose a process route when appropriate.",
            "If required capabilities are missing locally, prefer an install-first route over pretending the executor already exists.",
        ],
    }


def extract_json_object(text):
    text = (text or "").strip()
    if not text:
        raise ValueError("Model returned empty response.")
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Model response did not contain a JSON object.")
    return json.loads(text[start : end + 1])


def extract_response_text(response_json):
    if isinstance(response_json.get("output_text"), str) and response_json["output_text"].strip():
        return response_json["output_text"]
    output_chunks = []
    for item in response_json.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if text:
                output_chunks.append(text)
    return "\n".join(output_chunks).strip()


def call_responses_api(model_settings, system_prompt, user_prompt, timeout_seconds):
    payload = {
        "model": model_settings["model"],
        "reasoning": {"effort": model_settings.get("reasoning_effort", "high")},
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
            {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
        ],
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        model_settings["endpoint"],
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {model_settings['api_key']}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def ensure_decision_shape(decision):
    required_top_level = [
        "task_understanding",
        "task_profile",
        "needed_capabilities",
        "required_capabilities",
        "optional_support_capabilities",
        "minimal_high_quality_combo",
        "missing_executors",
        "step_acceptance_blueprint",
        "candidate_plans",
        "chosen_plan_id",
        "chosen_plan_reason",
        "why_not_others",
        "missing_required_capabilities",
        "missing_optional_capabilities",
        "reflection_trace",
    ]
    for key in required_top_level:
        if key not in decision:
            if key in {"minimal_high_quality_combo", "missing_executors", "step_acceptance_blueprint"}:
                decision[key] = []
                continue
            raise ValueError(f"Model decision is missing required key '{key}'.")
    if not isinstance(decision["candidate_plans"], list) or not decision["candidate_plans"]:
        raise ValueError("Model decision must include at least one candidate plan.")
    chosen_plan = None
    for plan in decision["candidate_plans"]:
        if plan.get("plan_id") == decision.get("chosen_plan_id"):
            chosen_plan = plan
        for index, step in enumerate(plan.get("steps", []), start=1):
            step.setdefault("step_id", f"{plan.get('plan_id', 'plan')}-step-{index}")
    if not decision.get("minimal_high_quality_combo"):
        if chosen_plan is None:
            chosen_plan = next((plan for plan in decision["candidate_plans"] if plan.get("plan_id") == decision.get("chosen_plan_id")), None)
        if chosen_plan:
            decision["minimal_high_quality_combo"] = [
                {
                    "executor_id": step.get("executor_id"),
                    "role": "primary" if index == 0 else "support",
                    "why": step.get("purpose") or step.get("expected_output") or "Selected for the chosen plan.",
                }
                for index, step in enumerate(chosen_plan.get("steps", []))
            ]
    if not decision.get("step_acceptance_blueprint"):
        blueprints = []
        plans_by_id = {plan.get("plan_id"): plan for plan in decision["candidate_plans"]}
        chosen_plan = chosen_plan or plans_by_id.get(decision.get("chosen_plan_id"))
        for step in (chosen_plan or {}).get("steps", []):
            blueprints.append(
                {
                    "step_id": step.get("step_id"),
                    "summary_template": step.get("expected_output") or step.get("purpose") or "Review this step output.",
                    "acceptance_criteria": [
                        f"Matches expected output: {step.get('expected_output') or step.get('purpose') or 'step output'}"
                    ],
                }
            )
        decision["step_acceptance_blueprint"] = blueprints
    return decision


def choose_reasoning_backend(config, override=None):
    reasoning = normalize_reasoning_config(config)
    if override:
        reasoning["provider_mode"] = override
    return reasoning


def decide_route(task_info, executors, config, mode, mock_response_path=None, provider_override=None, host_decision_path=None):
    reasoning = choose_reasoning_backend(config, provider_override)
    reasoning_executors, stage_one_meta = prepare_reasoning_executors(task_info, executors, config)
    reasoning_input = build_reasoning_input(
        task_info=task_info,
        executors=reasoning_executors,
        policy_constraints=config.get("policy_constraints", {}),
        mode=mode,
        stage_one_meta=stage_one_meta,
        summary_config=reasoning.get("stage_one", {}),
    )

    if mock_response_path:
        decision = load_json(mock_response_path)
        return reasoning_input, ensure_decision_shape(decision)

    if host_decision_path:
        decision = load_json(host_decision_path)
        return reasoning_input, ensure_decision_shape(decision)

    provider_mode = reasoning.get("provider_mode", "host")
    if provider_mode == "host":
        return reasoning_input, None
    if provider_mode == "mock":
        inline_mock = reasoning.get("mock_response_path")
        if not inline_mock:
            raise RuntimeError("Mock reasoning mode requires mock_response_path.")
        decision = load_json(inline_mock)
        return reasoning_input, ensure_decision_shape(decision)

    if provider_mode == "external":
        endpoint = reasoning.get("endpoint")
        api_key = reasoning.get("api_key") or os.environ.get(reasoning.get("api_key_env", "OPENAI_API_KEY"))
        model = reasoning.get("model")
        if not endpoint or not api_key or not model:
            raise RuntimeError("External reasoning mode requires endpoint, model, and api_key/api_key_env.")
        model_settings = {
            "endpoint": endpoint,
            "api_key": api_key,
            "model": model,
            "reasoning_effort": reasoning.get("reasoning_effort", "high"),
        }
    else:
        model_settings = load_host_model_settings(reasoning)

    system_prompt, user_prompt = build_model_messages(reasoning_input)
    raw_response = call_responses_api(
        model_settings=model_settings,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        timeout_seconds=int(reasoning.get("response_timeout_seconds", 45)),
    )
    response_text = extract_response_text(raw_response)
    decision = extract_json_object(response_text)
    return reasoning_input, ensure_decision_shape(decision)
