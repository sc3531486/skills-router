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

The task seed is no longer limited to `deliverable + actions`.
It now also carries two lightweight orchestration hints:

- `task_stage`
  - for example `discovery`, `architecture`, `design`, `implementation`, `validation`, `delivery`
- `needed_capability_groups`
  - for example `product-definition`, `information-design`, `ui-design`, `frontend`, `backend`, `testing`, `documentation`

These are still heuristic hints rather than hard routing rules.
They exist to help the host model reflect on what kind of help the task really needs before selecting concrete skills or MCP capabilities.

In v3, that plan becomes a JSON-driven orchestration loop:

- route the task
- recommend and optionally auto-install missing skills or MCP executors after user approval
- rerun routing after installation
- execute one step at a time
- surface each step's acceptance summary to the user
- continue only after confirmation

## Host support status

Current status should be understood in two layers:

### 1. Where this repository is directly installable as a skill

Today, the documented first-class install target is:

- `Codex`

That is why the installation section below is written around the Codex skill directory.

### 2. Which tool ecosystems the router can discover and reason about

The router's discovery layer already supports cross-tool inventory collection for:

- `Codex`
- `Claude`
- `Cursor`
- `Kiro`
- `Agents`

That means when `skill-router` runs, it can normalize visible skills and MCP declarations from those tool homes into one executor inventory.

Important distinction:

- `supports discovery` does not automatically mean `already packaged as a native installable skill for that host`
- different AI coding tools have different conventions for loading local skills, agents, plugins, or MCP manifests

So the accurate statement is:

> `skill-router` is already a cross-tool orchestrator at the discovery and planning layer, but its documented first-class installation path is currently Codex.

For `Claude`, `Cursor`, `Kiro`, and `Agents`, support is currently best described as:

- discovery support: yes
- manifest/provider support: yes, with different maturity levels
- native host-specific installation guide in this README: not yet fully documented

## Installation

This repository is a single skill repository.
Install it by placing the whole repository folder under your Codex skills directory as `skill-router`.

### Prerequisites

- You have Codex installed.
- You can access your Codex home directory.
- Your custom skills live under `$CODEX_HOME/skills`.

Default Codex home:

- Windows: `C:\Users\<your-user>\.codex`
- macOS / Linux: `~/.codex`

### Option 1: Install with Git

#### Windows

1. Open PowerShell.
2. Make sure the skills directory exists:

```powershell
New-Item -ItemType Directory -Force "$HOME\.codex\skills" | Out-Null
```

3. If you already have an older `skill-router`, back it up first:

```powershell
if (Test-Path "$HOME\.codex\skills\skill-router") {
  Rename-Item "$HOME\.codex\skills\skill-router" "skill-router.bak"
}
```

4. Clone the repository:

```powershell
git clone https://github.com/sc3531486/skills-router.git "$HOME\.codex\skills\skill-router"
```

#### macOS / Linux

1. Open Terminal.
2. Make sure the skills directory exists:

```bash
mkdir -p "$HOME/.codex/skills"
```

3. If you already have an older `skill-router`, back it up first:

```bash
if [ -d "$HOME/.codex/skills/skill-router" ]; then
  mv "$HOME/.codex/skills/skill-router" "$HOME/.codex/skills/skill-router.bak"
fi
```

4. Clone the repository:

```bash
git clone https://github.com/sc3531486/skills-router.git "$HOME/.codex/skills/skill-router"
```

### Option 2: Manual install from ZIP

If you do not want to use `git`:

1. Download this repository as a ZIP.
2. Extract it.
3. Rename the extracted folder to `skill-router` if needed.
4. Move it into your Codex skills directory:
   - Windows: `C:\Users\<your-user>\.codex\skills\skill-router`
   - macOS / Linux: `~/.codex/skills/skill-router`

### Verify the final layout

The final folder should look like this:

```text
skill-router/
  SKILL.md
  README.md
  assets/
  references/
  scripts/
  tests/
```

Important:

- `SKILL.md` must be directly inside the `skill-router` folder
- do not end up with a nested path like `skill-router/skills-router/SKILL.md`

### Reload Codex

After installation:

1. Fully restart Codex.
2. Start a new session.
3. Explicitly invoke the skill, for example:

```text
Use skill-router to decide which skills and MCP capabilities should handle this task.
```

### Quick verification

If installation is correct, Codex should be able to discover the skill and read its `SKILL.md`.

You can test with prompts like:

```text
Use skill-router to plan how to complete this task with the best mix of local skills and MCP.
```

```text
Use skill-router and tell me which skills or MCP capabilities you would involve before executing anything.
```

### Update to the latest version

If you installed with Git:

#### Windows

```powershell
git -C "$HOME\.codex\skills\skill-router" pull
```

#### macOS / Linux

```bash
git -C "$HOME/.codex/skills/skill-router" pull
```

Then restart Codex.

If you installed manually from ZIP, replace the folder contents with the latest release of this repository and restart Codex.

### Uninstall

Delete the installed folder:

- Windows: `C:\Users\<your-user>\.codex\skills\skill-router`
- macOS / Linux: `~/.codex/skills/skill-router`

Then restart Codex.

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
   - reflect through delivery, quality critic, and design/editor roles before choosing the route
   - compare candidate plans
   - choose the best route
4. Validate the route with hard policy rules
   - including step-order validation when a later step is the one that would produce required context
5. Return the validated plan to the host model
6. Let the host model execute the plan

That means `skill-router` is a planner-orchestrator, not the main executor.

## Host-Driven Reasoning Flow

The default reasoning mode is now `host`.

That means `plan_route.py` does not directly finalize the route by calling an upstream model endpoint when no host decision file is supplied.
Instead, the flow is:

1. run `plan_route.py --task "<task>"`
2. receive `routing_status = "requires_host_reasoning"`
3. pass `host_reasoning_request` and `host_reasoning_contract` to the host model
4. let the host model produce the reflective routing JSON
5. rerun `plan_route.py` with `--host-decision-file <decision.json>`
6. receive the validated `final_plan` and `orchestration_state`

The host model is expected to do more than basic executor matching.
It should explicitly ask:

- what route can actually deliver the requested result
- what route avoids a merely functional quality bar
- what route still deserves proactive strengthening for structure, readability, editability, or presentation

That is why the reasoning packet now includes explicit role-split reflection guidance instead of a single undifferentiated planning pass.
The packet also carries a second-pass quality review directive and a quality-gate policy so the host model cannot stop after the first plausible route.

## Minimal Host Signal

To avoid forcing the host to re-derive routing policy from multiple fields, `plan_route.py` now also emits a compact `host_route_signal`.

It is intentionally small:

- `router_state`
- `host_next_route_decision`
- `host_reroute_trigger_matched`
- `matched_trigger_label`
- `reason`

The intended read pattern is:

- if `host_next_route_decision = reroute-now`, the host should treat the current point as a routing boundary
- if `host_next_route_decision = continue-current-route`, the host should keep following the accepted route until a reroute trigger appears

This is only a derived shortcut over the richer routing contract; it does not replace the reflective planner itself.

Alongside that, the router also emits a compact `host_turn_signal`.
Its job is different:

- `host_route_signal` answers whether the host should reroute
- `host_turn_signal` answers what the host should do in this turn

`host_turn_signal` is intentionally minimal:

- `next_host_action`
- `requires_user_visible_message`
- `must_end_turn`
- `after_user_confirmation_action`
- `reason`

This lets the host avoid stitching together `next_host_action`, `execution_gate`, and `orchestration_state` manually for common cases.

For hosts or UI layers that want something even closer to direct user presentation, the router also emits a compact `routing_status_card`.

Its job is not to replace `user_summary` or `final_plan`.
Its job is to provide one small display-friendly status object:

- `phase`
- `headline`
- `user_action`
- `next_step`
- `waiting_for_user`
- `reason`

The intended split is:

- `host_route_signal`: should the host reroute?
- `host_turn_signal`: what should the host do in this turn?
- `routing_status_card`: what short status should the user or UI see right now?

In other words:

- `skill-router` prepares the reasoning packet
- the host model performs the reflection
- `plan_route.py` validates and materializes the resulting route

## When To Use The Router

`skill-router` should be treated as a stage orchestrator, not a one-shot opener and not a per-message interrupt.

Recommended session model:

- the user explicitly invokes `skill-router` once at the beginning
- after that, the host treats the conversation as `router-armed`
- the host continues the accepted route by default
- the host reruns the router automatically only when a reroute trigger is hit

So the ideal user experience is:

> use `skill-router` once, then let it quietly guard the rest of the workflow

The host can implement this with a 3-rule shortcut:

1. If there is no accepted route yet, `reroute-now`
2. If a reroute trigger is hit, `reroute-now`
3. Otherwise, `continue-current-route`

That shortcut is also emitted in the JSON output as `host_auto_routing_contract`.
The host does not need to reconstruct these rules from prose; it can read:

- `default_action`
- `triggered_action`
- `decision_rules`
- `requires_first_explicit_activation`

Use it at these moments:

- `initial-routing`
  - the first time a clear task arrives and the host needs the best initial `skills + MCP` plan
- `stage-rerouting`
  - the work changes stage, such as from research to writing, writing to slides, or analysis to implementation
- `post-install-rerouting`
  - a missing skill or MCP was installed and the plan should be rebuilt with the new capability
- `acceptance-rerouting`
  - a step fails acceptance, needs rollback, redo, or route rewrite
- `improvement-rerouting`
  - a low-cost, high-value improvement suggests that another support skill or MCP should now join the route
- `goal-change-rerouting`
  - the user changes the target, audience, quality bar, scope, or key constraints

Do not reroute just because the conversation continues.
Avoid rerunning the router when:

- the user is only clarifying a detail within the same stage
- the current route still fits and no new capability or quality issue has appeared

This split exists on purpose:

- it keeps routing aligned with the live host model that will actually execute the plan
- it avoids brittle direct API assumptions inside the router
- it makes the router usable even when the host model is available but raw scripted HTTP access is not

If you want to inspect the host handoff packet, run:

```powershell
python "$HOME/.codex/skills/skill-router/scripts/plan_route.py" --task "Write a document" --no-remote
```

You should see these top-level fields:

- `routing_status`
- `next_host_action`
- `host_reasoning_request`
- `host_reasoning_contract`
- `host_handoff_instructions`

## Explicit Mode UX Contract

When a user explicitly says to use `skill-router`, the route itself becomes part of the answer.

Expected order:

1. run `plan_route.py`
2. show `user_summary`
3. show `final_plan`
4. only then decide whether to continue with downstream execution

In explicit mode, `final_plan` now includes:

- `presentation_contract`
- `execution_gate`
- `host_handoff_instructions`
- `installation_gate`
- `quality_reflection`

The output also includes `orchestration_state`, which is the host-facing control protocol for the loop.

`quality_reflection` is the compact user-visible proof that the route was not chosen only because it is technically possible.
It summarizes:

- the quality bar the host model thinks this route reaches
- why that bar is acceptable
- remaining risks or optimization opportunities
- what each reflection role concluded

`final_plan` also carries `proactive_improvement_loop`.
This is where the router makes the "not just functional" behavior visible:

- route-level follow-up actions from the second-pass review
- step-level improvement checks that should be revisited before user acceptance

These fields are meant to reduce common host mistakes, especially:

- jumping straight into `brainstorming`, `drawio`, or another downstream skill
- treating routing as invisible internal plumbing
- asking optional browser or visualization prompts before the user has even seen the chosen orchestration plan

Important:

- in explicit mode, a valid route is not the same as "execute immediately"
- `execution_ready` should stay `false` until the route has been shown and the user has confirmed to continue
- the intended behavior is "show route and stop", not "show route and immediately start step 1"
- if required capabilities are missing, the intended behavior is "show route, show recommended installs, ask for approval, install, then rerun routing with the same task"
- once the user approves, the host model should automatically handle the install step through `skill-installer` rather than asking the user to manually run the install workflow
- skill installation uses `skill-installer`
- MCP installation uses provider adapters; v1 supports `Codex` and `Kiro`, while other hosts remain recommendation-only

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
