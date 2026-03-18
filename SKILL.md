---
name: skill-router
description: Use when the user explicitly asks to use an automatic dispatch or routing skill to decide which installed skills and visible MCP capabilities fit a task, or when a configured router is allowed to orchestrate complex multi-step work before execution.
---

# Skill Router

## Overview

`skill-router` is a unified orchestrator for two executor types:

- `skill`
- `mcp`

It does not decide the route by hardcoded local scoring.
Instead, it discovers available executors, asks the host model to propose candidate plans, validates the chosen plan against hard rules, and only then turns the result into an execution-ready route.
Before the host model sees the inventory, the router runs a lightweight stage-one narrowing pass to keep token usage under control. That pass compresses executor summaries and removes obviously irrelevant candidates, but it does not make the final route decision.
Its candidate limit is a soft target rather than an absolute hard wall: the router may keep a small extra set of cross-type candidates so the model still sees artifact, support, and MCP options together.

Its primary responsibility is orchestration planning, not runtime execution.
The normal path is:

- `skill-router` produces a validated plan
- the host model follows that plan and calls the selected skills or MCP capabilities

## Quick Start

1. Load `assets/router-config.json`.
2. Run `scripts/plan_route.py --task "<user request>"`.
3. If the output says `routing_status = requires_host_reasoning`, hand `host_reasoning_request` and `host_reasoning_contract` to the host model and let it produce the reflective routing JSON.
4. Feed that JSON back into `scripts/plan_route.py` with `--host-decision-file`.
5. Show the returned `user_summary` and `final_plan` to the user before invoking downstream skills.
6. Let the host model follow the validated `routing_decision.chosen_plan` only if `validation_result.is_valid = true`.
7. If `recommended_install_required` is non-empty, stop and wait for user approval before installing anything.

Example:

```powershell
python "$HOME/.codex/skills/skill-router/scripts/plan_route.py" --task "Create an editable architecture diagram and explain the flow"
```

If host reasoning is needed, the finalize step looks like:

```powershell
python "$HOME/.codex/skills/skill-router/scripts/plan_route.py" --task "Create an editable architecture diagram and explain the flow" --host-decision-file "decision.json"
```

## Workflow

### 1. Respect activation mode

- Default mode is `explicit`.
- In `explicit` mode, use this skill only when the user clearly asks for the automatic dispatch skill.
- `auto` mode is configuration-only and remains opt-in.

### Explicit-mode hard rule

When the user explicitly invokes `skill-router`, you must not jump straight into a downstream skill workflow.

You must do these steps in order:

1. run `scripts/plan_route.py` for the user's actual task
2. read `user_summary` and `final_plan`
3. show the routing result to the user in the current response
4. only after that, continue with the chosen route if it is valid and execution-ready

Do not skip step 3.
Do not open `brainstorming`, `writing-plans`, `drawio`, or any other downstream skill first and then retroactively claim that routing already happened.
For explicit invocations, the route itself is part of the user-visible result.
For explicit invocations, treat the route presentation as a pause point:

- show `user_summary` and `final_plan`
- wait for the user to confirm or continue
- end the current reply after showing the route
- do not ask optional browser, canvas, or visualization prompts before the route is visible
- do not start a downstream skill workflow in the same breath as if routing were invisible plumbing

### When to rerun the router

Treat `skill-router` as a stage orchestrator.
Do not use it only once at the beginning, but also do not rerun it on every message.

Recommended session behavior:

- the user explicitly invokes `skill-router` once to arm the session
- after that, the host should treat later reroutes as automatic follow-up behavior
- the user should not need to repeat `skill-router` on every turn
- the host should continue the accepted route by default and only reroute when a trigger is hit

Minimal host shortcut:

1. no accepted route yet -> `reroute-now`
2. reroute trigger hit -> `reroute-now`
3. otherwise -> `continue-current-route`

This shortcut is also emitted in the JSON output as `host_auto_routing_contract`.
Prefer consuming that structured contract directly instead of re-deriving the policy from the narrative text.
The key fields are:

- `default_action`
- `triggered_action`
- `decision_rules`
- `requires_first_explicit_activation`

For hosts that want an even thinner integration path, the router also emits a derived `host_route_signal`:

- `router_state`
- `host_next_route_decision`
- `host_reroute_trigger_matched`
- `matched_trigger_label`
- `reason`

Use it as a convenience field only.
It should help the host quickly answer "continue current route or reroute now?" without replacing the fuller routing contract.

The router also emits a derived `host_turn_signal` for the current turn:

- `next_host_action`
- `requires_user_visible_message`
- `must_end_turn`
- `after_user_confirmation_action`
- `reason`

Use the split like this:

- `host_route_signal` decides whether to reroute
- `host_turn_signal` decides what the host should do right now

Both are convenience fields derived from the richer routing and orchestration outputs.

For user-facing rendering, the router also emits a derived `routing_status_card`:

- `phase`
- `headline`
- `user_action`
- `next_step`
- `waiting_for_user`
- `reason`

Use the split like this:

- `host_route_signal` answers route control
- `host_turn_signal` answers host turn control
- `routing_status_card` answers what short status the user should currently see

Use or rerun it at these boundaries:

- `initial-routing`
  - the first time a clear task needs an initial route
- `stage-rerouting`
  - the work changes phase and the best executor mix may change with it
- `post-install-rerouting`
  - a missing skill or MCP has just been installed
- `acceptance-rerouting`
  - a step was rejected, needs rollback, redo, or route rewrite
- `improvement-rerouting`
  - a worthwhile proactive improvement suggests adding or swapping support executors
- `goal-change-rerouting`
  - the user's target, audience, constraints, or quality bar materially change

Do not reroute when:

- the user is only making a small same-stage clarification
- the current route still fits and no new capability or quality risk has appeared

### 2. Discover executors

The router discovers four things before any reasoning:

- local `skill` executors
- visible session `mcp_tool` executors
- visible session `mcp_resource` executors
- manifest-level MCP executors from supported tool homes

Current tool-home discovery is designed for:

- `Codex`
- `Claude`
- `Cursor`
- `Kiro`
- `Agents`

The router normalizes all of them into one inventory before asking the model to choose.
It then runs a stage-one candidate selector:

- compress long descriptions and keyword lists
- prune obviously unrelated executors for the current task type
- preserve a balanced candidate mix across artifact skills, support skills, and relevant MCP executors
- allow a small diversity overflow when needed so stage one does not over-constrain the model
- pass only the narrowed candidate set into the final reflective routing prompt

### 3. Ask the model to plan

In default `host` mode, the router does not directly perform this final reasoning call itself.
It prepares a reasoning packet for the host model.

The host model receives:

- the task
- the heuristic seed task profile
- the heuristic `task_stage`
- the heuristic `needed_capability_groups`
- all discovered executors
- reflection roles for delivery, quality critic, and design/editor review
- a second-pass review directive
- a quality-gate policy
- policy constraints
- execution mode
- user language

The model must return JSON containing:

- `task_understanding`
- `task_profile`
- `needed_capabilities`
- `required_capabilities`
- `optional_support_capabilities`
- `role_findings`
- `completion_assessment`
- `quality_gate`
- `second_pass_review`
- `candidate_plans`
- `chosen_plan_id`
- `chosen_plan_reason`
- `why_not_others`
- `missing_required_capabilities`
- `missing_optional_capabilities`
- `reflection_trace`

When `plan_route.py` is waiting for the host model, the output includes:

- `routing_status = requires_host_reasoning`
- `next_host_action = reflect_and_finalize_route`
- `host_reasoning_request`
- `host_reasoning_contract`
- `host_handoff_instructions`

The point of these extra role fields is to prevent shallow routing.
The host model should not stop at "which executor can do this".
It should also ask:

- what will actually get the user to a good result
- what still looks underpowered or under-designed
- what deserves proactive strengthening before the route is considered good enough

For quality-sensitive tasks such as optimize/polish/improve requests, the host should not approve a bare single-executor route unless it also adds explicit proactive improvement checks.

### 4. Validate the route

The router never trusts the model blindly.
It validates the chosen plan against hard rules, including:

- bounded artifact requests cannot include `process_only` skills
- `mcp_resource` cannot be the final artifact-producing step
- mutating MCP tools are blocked unless policy explicitly allows them
- missing required capabilities block execution
- unknown executor ids invalidate the plan

The router also treats the program-generated task profile as a seed, not ground truth.
Final validation and user-facing output use the model-corrected `task_profile`, `required_capabilities`, and `optional_support_capabilities`.
Validation also checks step ordering when a route claims that one step depends on context produced by another step later in the plan.

That means:

- the program can lightly hint "this looks like discovery vs design vs implementation"
- and it can lightly hint "this probably needs product-definition vs ui-design vs frontend"
- but the host model still makes the final reflective orchestration decision

### 5. Hand off or stop

- If the plan is valid and there is no required install gap, hand the chosen plan back to the host model for execution.
- If only optional gaps remain, continue with the validated route and show optional recommendations as upgrades.
- If required gaps remain, stop and wait for user confirmation before installing anything.
- If the user approves a required install recommendation, install it first and then rerun `plan_route.py` for the same task before executing downstream steps.
- The host model should handle that install step by invoking `skill-installer`; the user should only need to approve, not manually perform the installation flow.

For explicit invocations, present the plan first in a compact visible format such as:

- `user_summary`
- chosen plan id or summary
- ordered steps
- validation status
- required or optional upgrade recommendations

If the user asked to use `skill-router`, they should be able to see what route was chosen before the downstream skill flow takes over.

The bundled runner in `scripts/execute_route.py` is experimental and exists mainly for debugging or local testing of route semantics:

- it resolves local `mcp_resource` context when content is available
- it can consume mock executor outputs for testing
- it stops at the first step that still requires host-side skill or MCP tool execution
- it returns a structured handoff request instead of pretending the host-only step already ran

Do not treat this experimental runner as the core product path.
The core product path is still reflective routing plus host-model execution.

## Output Contract

Default output is concise at the top level:

- compact `user_summary`
- user-visible `final_plan`
- structured `routing_decision`
- structured `validation_result`
- optional install recommendations

`final_plan` also carries an execution handoff contract:

- `presentation_contract`
- `execution_gate`
- `host_handoff_instructions`
- `installation_gate`
- `quality_reflection`
- `proactive_improvement_loop`

Use those fields as hard guidance for explicit invocations.

`quality_reflection` is intentionally user-visible.
It is the compact summary that shows the route was reviewed through the role-split reflection protocol rather than chosen only for baseline feasibility.

`proactive_improvement_loop` is also intentionally visible.
It carries:

- route-level follow-up actions produced by the second-pass review
- step-level improvement checks that should be revisited before user acceptance

The top-level output also includes `orchestration_state`.
Treat it as the authoritative loop state for the host:

- initial show-plan step
- install approval and installer invocation
- reroute after install
- per-step execution
- per-step acceptance
- finish

Internal reasoning payloads are not shown by default.
Only use `--include-reasoning-input` when debugging router behavior.
Only use `--include-reflection-trace` when you need to inspect why the model introduced a capability, skill, or MCP step.
The reasoning payload now also includes stage-one selection details and pruned details so you can inspect why a candidate was kept, overflowed in, or removed.

## User-Facing Behavior

- Keep the user-facing summary short.
- Use `user_summary` for the visible plan line.
- Use `final_plan` as the user-visible orchestration result when the caller wants to show the validated route itself.
- In explicit mode, always show `final_plan` before proceeding into downstream execution.
- In explicit mode, respect `final_plan.presentation_contract` and `final_plan.execution_gate` as a hard pause before execution.
- In explicit mode, treat `execution_ready = false` as intentional even when the route is valid; the missing piece is user confirmation, not route quality.
- In explicit mode, after showing the route, stop the current turn instead of auto-entering `brainstorming`, `drawio`, or any other first step.
- Do not ask "want to open a browser" or similar optional host UX questions until after the route has already been shown and the next step actually needs that capability.
- If `installation_gate.requires_user_approval = true`, first ask whether the user wants to install the recommended skill, then rerun routing after installation instead of forcing the old route forward.
- When approval is granted, use `installation_gate.approved_executor` to see that the host should call `skill-installer` automatically.
- If `recommended_install_mcp` is non-empty, use the MCP provider adapter data to decide whether the host can auto-install now or should stay in recommendation-only mode.
- When a step finishes, generate a `step_receipt`, surface the acceptance summary, and wait for the user's confirmation before moving to the next step.
- Do not dump the full model reasoning unless the user asks.
- Keep the user's language throughout the route summary.
- For bounded requests, do not add generic process skills unless the model chooses a valid process route and the policy allows it.

## MCP Rules

- `mcp_tool` can be an executable step.
- `mcp_resource` is context-only and must stay read-only.
- Manifest-level MCP discovery is allowed to be best-effort.
- If the session provider has richer MCP visibility than manifests, session discovery wins.

## Common Operations

### List discovered skills

```powershell
python "$HOME/.codex/skills/skill-router/scripts/list_installed_skills.py"
```

### Plan a route

```powershell
python "$HOME/.codex/skills/skill-router/scripts/plan_route.py" --task "Read MCP context and then generate a document"
```

### Experimental: execute a validated route locally

```powershell
python "$HOME/.codex/skills/skill-router/scripts/execute_route.py" --route-file "route.json"
```

### Experimental: execute with local resource content or mock executor outputs

```powershell
python "$HOME/.codex/skills/skill-router/scripts/execute_route.py" --route-file "route.json" --resource-contents-file "resource-content.json" --mock-executor-results-file "mock-results.json"
```

### Plan without remote recommendations

```powershell
python "$HOME/.codex/skills/skill-router/scripts/plan_route.py" --task "Create an editable draw.io overview" --no-remote
```

### Test with a mock model response

```powershell
python "$HOME/.codex/skills/skill-router/scripts/plan_route.py" --task "Write a document" --mock-model-response "mock.json"
```

### Debug the reasoning payload

```powershell
python "$HOME/.codex/skills/skill-router/scripts/plan_route.py" --task "Write a document" --mock-model-response "mock.json" --include-reasoning-input
```

### Debug the internal reflection trace

```powershell
python "$HOME/.codex/skills/skill-router/scripts/plan_route.py" --task "Write a document" --mock-model-response "mock.json" --include-reflection-trace
```

### Inspect the narrowed reasoning payload

```powershell
python "$HOME/.codex/skills/skill-router/scripts/plan_route.py" --task "Write a document" --mock-model-response "mock.json" --include-reasoning-input
```

This debug payload now shows the stage-one candidate subset rather than the full discovered inventory.

## Common Mistakes

- Treating this as a skill-only router. It now routes both `skill` and `mcp`.
- Letting the script itself choose the route by handcrafted scores. The model must choose; the script only validates.
- Treating `skill-router` as a replacement runtime for the host model. Its main job is to produce the plan, not to become a second agent framework.
- Treating `mcp_resource` like an artifact executor. It is context-only.
- Allowing `process_only` skills to leak into bounded artifact routes.
- Silently installing missing skills. Installation still requires explicit user confirmation.
- Explicitly invoking `skill-router` but then immediately entering `brainstorming` or another downstream skill without first showing the chosen route.

## Resources

- `scripts/plan_route.py`: main unified route planner CLI.
- `scripts/discovery_providers.py`: skill and MCP discovery providers.
- `scripts/model_router.py`: host-model reasoning and decision parsing.
- `scripts/execution_runner.py`: experimental chosen-plan runner for debugging route semantics.
- `scripts/execute_route.py`: experimental CLI entrypoint for the runner.
- `scripts/policy_validator.py`: hard-route validation.
- `scripts/router_lib.py`: shared task inference, normalization, and recommendation helpers.
- `tests/test_reflective_router.py`: regression tests for discovery, validation, and route planning.
- `assets/router-config.json`: router behavior, reasoning mode, and policy settings.
- `assets/skill-index.json`: bundled recommendation index.
- `references/routing-rules.md`: routing model and validation rules.
- `references/source-management.md`: discovery and recommendation source order.
