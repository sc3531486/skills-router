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

EXPECTED_REFLECTION_ROLE_IDS = [
    "delivery-role",
    "quality-critic-role",
    "design-editor-role",
]


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


def build_reflection_roles(task_info):
    use_chinese = prefers_chinese(task_info.get("task", ""))
    if use_chinese:
        return [
            {
                "role_id": "delivery-role",
                "title": "交付负责人",
                "responsibility": "先判断怎样才能稳定交付用户要的结果，确保主产物、执行顺序、依赖和可执行性都成立。",
                "questions": [
                    "当前路线是否真的能产出用户要的结果？",
                    "主执行器是否选对了？",
                    "步骤顺序、输入依赖、上下文来源是否完整？",
                ],
            },
            {
                "role_id": "quality-critic-role",
                "title": "质量审稿人",
                "responsibility": "主动挑战“只是能做”而不是“做到最好”的路线，找出隐藏质量要求、明显短板、遗漏验证和可补强点。",
                "questions": [
                    "这条路线是不是只满足了最低功能，而没有达到应有质量？",
                    "还有哪些清晰度、准确性、专业度、完整性或验收风险没有覆盖？",
                    "是否需要增加支持型 skill 或 MCP，才能明显提升结果质量？",
                ],
            },
            {
                "role_id": "design-editor-role",
                "title": "设计与编辑负责人",
                "responsibility": "从信息设计、表达结构、可读性、视觉质量和受众适配的角度审视路线，避免结果虽然完成但体验粗糙。",
                "questions": [
                    "结果是否足够清晰、易读、结构合理？",
                    "是否需要额外考虑版式、视觉层次、叙事顺序、受众理解成本或编辑体验？",
                    "有没有值得主动补强的地方，让最终结果更专业、更好用？",
                ],
            },
        ]
    return [
        {
            "role_id": "delivery-role",
            "title": "Delivery Lead",
            "responsibility": "Ensure the route can reliably produce the requested outcome, with the right primary executor, step order, dependencies, and execution feasibility.",
            "questions": [
                "Can this route actually produce the requested outcome?",
                "Is the primary executor the right one?",
                "Are the step order, inputs, and context dependencies complete?",
            ],
        },
        {
            "role_id": "quality-critic-role",
            "title": "Quality Critic",
            "responsibility": "Challenge routes that only satisfy the minimum functional bar and surface hidden quality requirements, weak spots, missing validation, and worthwhile upgrades.",
            "questions": [
                "Does this route only satisfy the minimum functional request instead of the best practical result?",
                "What quality gaps, risks, or validation holes are still uncovered?",
                "Would any support skill or MCP materially improve the output quality?",
            ],
        },
        {
            "role_id": "design-editor-role",
            "title": "Design and Editor",
            "responsibility": "Review the route for information design, readability, structure, visual polish, and audience fit so the outcome is not merely complete but well-shaped.",
            "questions": [
                "Will the result be clear, readable, and well-structured?",
                "Should layout, visual hierarchy, narrative flow, audience fit, or editability be improved?",
                "What is worth polishing proactively before calling the plan good enough?",
            ],
        },
    ]


def build_completion_directive(task_info):
    if prefers_chinese(task_info.get("task", "")):
        return {
            "quality_bar": "best-practical",
            "instruction": "请先分别以 delivery-role、quality-critic-role、design-editor-role 三个角色审视任务，再综合成最小但高质量的执行方案。不要只回答“哪个执行器能做”，而要回答“怎样编排才能把结果做到最好且不过度堆叠”。",
        }
    return {
        "quality_bar": "best-practical",
        "instruction": "Review the task through delivery-role, quality-critic-role, and design-editor-role before synthesizing the route. Do not stop at 'which executor can do it'; decide 'which orchestration yields the best practical result without unnecessary bloat'.",
    }


def is_quality_sensitive_task_profile(task_profile):
    task_profile = task_profile or {}
    actions = set(task_profile.get("actions", []))
    quality_goals = set(task_profile.get("quality_goals", []))
    if "optimize" in actions:
        return True
    if quality_goals & {"visual-polish", "clarity", "teachability"}:
        return True
    return bool(task_profile.get("deliverable") and len(quality_goals) >= 2)


def build_second_pass_directive(task_info):
    quality_sensitive = is_quality_sensitive_task_profile(task_info.get("task_profile", {}))
    if prefers_chinese(task_info.get("task", "")):
        return {
            "enabled": True,
            "quality_sensitive": quality_sensitive,
            "instruction": "先给出候选路线，再做第二轮反思：假设自己是高标准用户，检查这条路线是不是只是把任务做完，而没有把结果做得更好。如果仍有明显可补强点，就不要直接通过。",
            "questions": [
                "这条路线是不是只是功能上能做，而不是结果上够好？",
                "如果用户要求更专业、更清晰、更有完成度，当前路线还差什么？",
                "有没有低成本但高价值的补强动作，应该写进路线或写进每步验收检查？",
            ],
        }
    return {
        "enabled": True,
        "quality_sensitive": quality_sensitive,
        "instruction": "After drafting the route, run a second-pass review from the perspective of a demanding user. If the route is merely functional and still misses obvious quality upgrades, do not approve it yet.",
        "questions": [
            "Is this route only functionally sufficient rather than genuinely good enough?",
            "What would still feel underpowered to a demanding user who cares about quality and finish?",
            "Which low-cost, high-value improvements should be added to the route or to step-level review checks?",
        ],
    }


def build_quality_gate_policy(task_info):
    quality_sensitive = is_quality_sensitive_task_profile(task_info.get("task_profile", {}))
    if prefers_chinese(task_info.get("task", "")):
        return {
            "quality_sensitive": quality_sensitive,
            "require_quality_gate": True,
            "require_second_pass_review": True,
            "require_step_improvement_checks_for_bare_routes": quality_sensitive,
            "instruction": "如果这是优化类或质量敏感任务，就不能只因为某个执行器“能做”而通过。若路线仍然是单一裸执行器，必须额外给出明确的主动补强检查，或者重编排路线。",
        }
    return {
        "quality_sensitive": quality_sensitive,
        "require_quality_gate": True,
        "require_second_pass_review": True,
        "require_step_improvement_checks_for_bare_routes": quality_sensitive,
        "instruction": "For optimization or quality-sensitive tasks, do not approve a route only because one executor can technically do it. If the route stays bare and single-executor, add explicit proactive improvement checks or re-orchestrate it.",
    }


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
        "task_stage_seed": task_info["task_profile"].get("task_stage"),
        "needed_capability_group_hints": task_info.get(
            "needed_capability_groups",
            task_info["task_profile"].get("needed_capability_groups", []),
        ),
        "required_capability_hints": task_info.get("required_capabilities", []),
        "optional_support_capability_hints": task_info.get("optional_support_capabilities", []),
        "available_executors": [
            summarize_executor_for_reasoning(item, summary_config)
            for item in executors
        ],
        "stage_one_selection": stage_one_meta or {},
        "reflection_roles": build_reflection_roles(task_info),
        "completion_directive": build_completion_directive(task_info),
        "second_pass_directive": build_second_pass_directive(task_info),
        "quality_gate_policy": build_quality_gate_policy(task_info),
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
Do not confuse "can edit the artifact" with "can produce the best result".
For optimization, polishing, improvement, or refinement requests, explicitly reason about hidden quality dimensions such as information hierarchy, readability, layout, visual polish, professionalism, and audience fit before choosing the route.
If one executor can produce the artifact but optional support capabilities would materially improve quality, reflect that in candidate_plans and minimal_high_quality_combo instead of defaulting to a single bare functional executor.
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
    "task_stage": "string",
    "needed_capability_groups": ["string"],
    "user_language": "string"
  },
  "needed_capabilities": ["string"],
  "required_capabilities": ["string"],
  "optional_support_capabilities": ["string"],
  "role_findings": [
    {
      "role_id": "string",
      "conclusion": "string",
      "concerns": ["string"],
      "suggested_capabilities": ["string"]
    }
  ],
  "completion_assessment": {
    "quality_bar": "minimum|strong|best-practical",
    "baseline_satisfied": true,
    "quality_risks": ["string"],
    "optimization_opportunities": ["string"],
    "reason": "string"
  },
  "quality_gate": {
    "status": "pass|fail",
    "reason": "string",
    "blocking_issues": ["string"]
  },
  "second_pass_review": {
    "verdict": "good-enough|revise-route",
    "reason": "string",
    "follow_up_actions": ["string"]
  },
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
      "acceptance_criteria": ["string"],
      "improvement_checks": ["string"]
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
            "role_findings",
            "completion_assessment",
            "quality_gate",
            "second_pass_review",
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
            "For optimization or polishing tasks, reflect on hidden quality goals such as clarity, visual polish, readability, professionalism, and information design before choosing the route.",
            "Return role_findings for all reflection roles and a completion_assessment before choosing the final route.",
            "After choosing a tentative route, run a second-pass review and return quality_gate plus second_pass_review.",
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
        "role_findings",
        "completion_assessment",
        "quality_gate",
        "second_pass_review",
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
            if key in {"role_findings", "completion_assessment", "quality_gate", "second_pass_review"}:
                raise ValueError(
                    f"Model decision is missing required key '{key}'. Host reasoning must include role-split reflection output."
                )
            raise ValueError(f"Model decision is missing required key '{key}'.")
    if not isinstance(decision.get("role_findings"), list):
        raise ValueError("Model decision field 'role_findings' must be a list.")
    findings_by_role = {}
    for item in decision["role_findings"]:
        role_id = item.get("role_id")
        if not role_id:
            raise ValueError("Each role finding must include role_id.")
        findings_by_role[role_id] = item
    missing_roles = [role_id for role_id in EXPECTED_REFLECTION_ROLE_IDS if role_id not in findings_by_role]
    if missing_roles:
        raise ValueError(
            f"Model decision is missing role findings for: {', '.join(missing_roles)}."
        )
    if not isinstance(decision.get("completion_assessment"), dict):
        raise ValueError("Model decision field 'completion_assessment' must be an object.")
    for key in ("quality_bar", "baseline_satisfied", "quality_risks", "optimization_opportunities", "reason"):
        if key not in decision["completion_assessment"]:
            raise ValueError(
                f"Model decision completion_assessment is missing required key '{key}'."
            )
    quality_gate = decision.get("quality_gate")
    if not isinstance(quality_gate, dict):
        raise ValueError("Model decision field 'quality_gate' must be an object.")
    for key in ("status", "reason", "blocking_issues"):
        if key not in quality_gate:
            raise ValueError(f"Model decision quality_gate is missing required key '{key}'.")
    second_pass_review = decision.get("second_pass_review")
    if not isinstance(second_pass_review, dict):
        raise ValueError("Model decision field 'second_pass_review' must be an object.")
    for key in ("verdict", "reason", "follow_up_actions"):
        if key not in second_pass_review:
            raise ValueError(f"Model decision second_pass_review is missing required key '{key}'.")
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
                    "improvement_checks": [],
                }
            )
        decision["step_acceptance_blueprint"] = blueprints
    for blueprint in decision.get("step_acceptance_blueprint", []):
        blueprint.setdefault("improvement_checks", [])
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
