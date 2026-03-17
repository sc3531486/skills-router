# Routing Rules

Use these rules to keep `skill-router` reflective, generic, and policy-safe.

## Core stance

- Treat the router as a unified orchestrator, not a single-skill dispatcher.
- Discover executors first, then let the model reason over the normalized inventory.
- Do not hardcode task-specific route templates as the final decision path.
- Prefer the smallest sufficient plan that still meets the user's requested quality bar.

## Orchestration flow

1. Discovery layer:
   - collect `skill`, `mcp_tool`, and `mcp_resource`
   - normalize them into one executor inventory
   - run stage-one narrowing to trim obviously irrelevant candidates and compress executor summaries
2. Reasoning layer:
   - accept a heuristic `task_profile_seed`
   - let the model correct the task profile if needed
   - ask the model which capabilities are needed
   - ask the model for multiple candidate plans and one chosen plan
3. Policy layer:
   - validate that the chosen plan respects hard constraints
4. Execution layer:
   - hand the validated route back to the host model
   - let the host model call the chosen skills and MCP capabilities
   - use local runner utilities only as optional debugging aids, not as the primary runtime

The program may help with inference and normalization, but it must not replace the model's final route choice with handcrafted route scoring.
The program's task inference is only a seed. The model is allowed to correct it before planning.

## Stage-One narrowing

Stage one is allowed to be heuristic because it is not the final chooser.
Its only job is to lower token cost and reduce noise before the reflective model call.
Its candidate limit should be treated as a soft target, not an excuse to over-prune the model's option space.

Stage one may:

- truncate long descriptions
- limit keyword and capability lists
- remove obviously irrelevant executors for the current task shape
- keep process-only skills out of bounded artifact requests unless process intent is explicit
- keep top candidate executors by coarse relevance score
- preserve candidate diversity across:
  - primary artifact executors
  - optional support executors
  - relevant MCP tools/resources
- use a small diversity overflow when necessary to keep cross-type options visible to the model
- record why candidates were selected or pruned for debugging

Stage one must not:

- claim that a route is chosen
- hide all candidates for a required capability
- let a narrow heuristic guess erase all meaningful support or MCP alternatives
- replace the model's final decision with script scoring

## Experimental runner v1

The local execution runner is optional and experimental.
It should help inspect route semantics, but it should not redefine the product boundary of `skill-router`.

It may:

- resolve local or provided `mcp_resource` content
- thread resolved context into later steps
- consume mock executor outputs for testing and development
- emit a structured host handoff request for `skill` and `mcp_tool` steps that need the host runtime

It must not:

- claim a host-only step already executed when it did not
- silently skip failed or missing context inputs
- mutate through blocked MCP tools
- be presented as the default execution path of the router

## Task profile contract

The planner should infer:

- `deliverable`
- `actions`
- `quality_goals`
- `bounded_request`
- `process_intents`
- `user_language`

From that profile it should derive:

- `required_capabilities`
- `optional_support_capabilities`

In v2, the program supplies only heuristic hints. The model should return the corrected profile that downstream validation and output will use.

## Capability model

Two executor families can satisfy route steps:

- `skill`
- `mcp`

Within MCP:

- `mcp_tool` can appear as an executable route step
- `mcp_resource` is context-only and should enrich later steps

Support capabilities should stay generic and reusable:

- `information-design`
- `visual-design`
- `research`
- `review`

## Reflective planning rules

- The model should first ask: "what capabilities would produce the best outcome for this task?"
- The model should also ask: "does the heuristic task profile need correction before I choose a route?"
- The model should then compare candidate plans, not just pick a familiar executor.
- Candidate plans should differ because of capability mix or execution order, not because of arbitrary route labels.
- A bounded artifact request should usually favor an artifact-producing route unless the task itself explicitly asks for planning, ideation, debugging, or review.
- Process skills may appear only in a real process-guided route, not as casual support add-ons.
- If a task can be completed by one strong executor, the chosen plan should stay simple.
- If quality goals such as clarity, visual polish, or accuracy materially change the best route, that should show up as additional support capabilities or MCP context steps.
- In explicit router mode, the chosen plan must be shown to the user before any downstream skill flow begins.
- Optional host UX prompts such as browser or visualization helpers must not appear before the route itself is visible.
- In explicit router mode, a valid route must still stop after presentation. Do not auto-run step 1 in the same reply.

## Validation rules

The validator must reject plans that violate hard policy:

- unknown `executor_id`
- step type does not match executor type
- bounded artifact request includes a `process_only` skill
- `mcp_resource` is used as the final artifact-producing step
- `mcp_resource` is not marked `reads_context_only = true`
- `mcp_resource` is marked as mutating
- mutating `mcp_tool` is selected while policy forbids it
- a step requires context that is only produced by a later step
- `missing_required_capabilities` is non-empty

Warnings are allowed for softer issues such as reading MCP resources after an executable step when no explicit dependency break is detected.

## Reflection trace

The model should keep an internal `reflection_trace` describing why it:

- corrected the task profile
- introduced a capability
- selected a skill or MCP executor
- rejected a competing route

This trace is for debugging and inspection. It should not be shown by default in normal user-facing output.

## Gap handling

Keep two gap classes:

- `missing_required_capabilities`
- `missing_optional_capabilities`

Rules:

- required gaps block execution
- optional gaps do not block execution
- optional gaps should still produce upgrade recommendations
- recommendations must never auto-install

## Recommendation order

Recommend in this order:

1. local bundled index
2. OpenAI curated skill list
3. approved GitHub indexes

The router should explain why a recommendation matches the missing capability instead of presenting a blind install suggestion.

## Generic examples

- `用自动调度 skill 画一个中文 Kubernetes draw.io 总览图，要求讲清楚关系`
  - likely chosen plan: `drawio`
  - likely optional gap: `information-design`
- `帮我规划一个功能开发方案，需要先梳理实现思路再落地`
  - likely process-guided route: `brainstorming -> writing-plans`
- `读取某个 MCP 资源，再生成总结文档`
  - valid pattern: `mcp_resource -> skill`
- `需要调用 MCP tool 获取设计上下文，再产出可编辑图`
  - valid pattern: `mcp_tool -> skill`
