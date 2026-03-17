# Skill Router

Reflective orchestration for `skills + MCP`.

`skill-router` is not a fixed rule router and not a second runtime.
Its core idea is `reflective orchestration`:

- when a user request arrives, the model first reflects on which capabilities are actually needed to produce the best result
- it then maps those capabilities to currently available `skills` and `MCP`
- it turns that into a concrete plan with ordered steps
- the host model follows that plan and invokes the selected skills or MCP capabilities

In short:

> `skill-router` lets the model think first about which abilities should collaborate, then orchestrates them into a plan.

## Core Logic

The intended flow is:

1. Discover available executors
   - local `skill`
   - visible `mcp_tool`
   - visible `mcp_resource`
2. Build a minimal task seed
   - the program only extracts lightweight hints such as likely deliverable and constraints
   - stage one may compress the candidate pool, but its limit is a soft target so the model still sees cross-type options when they matter
3. Let the model reflect
   - correct the task understanding
   - decide which capabilities are required
   - compare candidate plans
   - choose the best route
4. Validate the route with hard policy rules
   - including step-order validation when a later step is the one that would produce required context
5. Return the validated plan to the host model
6. Let the host model execute the plan

That means `skill-router` is a planner-orchestrator, not the main executor.

## Why It Exists

Traditional routing usually looks like:

- see a diagram request
- pick `drawio`
- stop thinking

`skill-router` aims for a stronger behavior:

- ask what would produce the best outcome
- decide whether one executor is enough
- decide whether multiple `skills + MCP` should cooperate
- keep the plan minimal, but not simplistic

Examples:

- a bounded artifact request may only need one strong artifact skill
- a higher-quality task may benefit from `mcp_resource -> skill`
- a more complex workflow may need multiple executors in sequence

## Design Principles

- Model-led decision making
  - the model chooses the final route
- Programmatic guardrails
  - the program discovers, normalizes, narrows, and validates
- Unified executor inventory
  - `skill`, `mcp_tool`, and `mcp_resource` are reasoned over together
- Minimal seed, model correction
  - task profiling is a heuristic starting point, not the final truth
- Reflection before execution
  - the router plans first, the host model executes second

## What Counts As An Executor

`skill-router` currently orchestrates two executor families:

- `skill`
- `mcp`

Within MCP:

- `mcp_tool` can be an executable step
- `mcp_resource` is context-only and should enrich later steps

## Route Shape

The model returns a structured route decision that includes:

- task understanding
- corrected task profile
- needed capabilities
- candidate plans
- chosen plan
- why that plan wins
- missing required capabilities
- missing optional capabilities
- internal `reflection_trace`

`reflection_trace` exists for debugging and inspection, but it is hidden by default in normal user-facing output.

## Current Product Boundary

The core product path is:

- `skill-router` plans
- the host model executes

There is an experimental local runner in `scripts/execute_route.py`, but it is only for debugging route semantics and local testing.
It is not the main product path.

## Repository Layout

- [SKILL.md](./SKILL.md): installed skill instructions
- [references/routing-rules.md](./references/routing-rules.md): routing philosophy and hard rules
- [scripts/plan_route.py](./scripts/plan_route.py): unified planner entrypoint
- [scripts/discovery_providers.py](./scripts/discovery_providers.py): cross-tool executor discovery
- [scripts/model_router.py](./scripts/model_router.py): reflective model decision layer
- [scripts/policy_validator.py](./scripts/policy_validator.py): hard-route validation
- [tests/test_reflective_router.py](./tests/test_reflective_router.py): regression coverage

## Current Status

This repository already matches the intended logic at the core architecture level:

- it does not rely on handcrafted final route scoring
- it lets the model choose among candidate plans
- it supports `skill + MCP` in one inventory
- it keeps `task_profile` as a seed and lets the model correct it
- it keeps `reflection_trace` as an internal field
- it validates the chosen route before execution

The remaining direction is mainly product polish:

- improve presentation
- improve examples
- improve host-side adoption
- keep the orchestrator boundary clear
