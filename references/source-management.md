# Source Management

This skill uses a layered discovery strategy so it can orchestrate local skills and MCP capabilities without binding itself to one host tool.

## Discovery order

1. Session-visible MCP tools/resources when provided
2. Local skill roots from supported tool homes
3. Local MCP manifests from supported tool homes
4. Bundled local index in `assets/skill-index.json`
5. OpenAI curated remote list
6. GitHub whitelist remote indexes

## Why this order

- session-visible MCP is usually the richest live context
- local discovery is deterministic and offline-safe
- bundled index is reviewable and stable
- remote indexes enrich recommendations without blocking local routing
- stage-one narrowing keeps the model prompt small even when local discovery finds many executors

## Supported tool-home providers

Current first-pass providers:

- `Codex`
- `Claude`
- `Cursor`
- `Kiro`
- `Agents`

The provider contract is tool-agnostic:

- if a stable skills root exists, scan it
- if a stable MCP manifest exists, parse it
- if neither exists, return an empty result or warning instead of failing the router

## MCP sources

Two MCP sources are supported:

- `mcp-session`
  - preferred when the current session can expose tool/resource snapshots
- `mcp-manifest`
  - fallback to local config discovery when session visibility is unavailable

`mcp_resource` entries are context-only. They should enrich later route steps, not replace artifact executors.

## Remote recommendation lookups

Remote lookups are best-effort.

If a remote source fails:

- keep local routing working
- keep local recommendation working
- report that remote index enrichment was unavailable if needed

## Default remote sources

### OpenAI curated

Use the `openai/skills` GitHub repository and inspect `skills/.curated`.

### GitHub whitelist indexes

Default sources:

- `ComposioHQ/awesome-claude-skills`
- `numman-ali/n-skills`

The router may use lightweight repository inspection logic for these sources, but should treat the bundled local index as the stable fallback.

## Installation expectation

The router does not install directly.
It recommends installation candidates and expects a separate installer flow, such as the system `skill-installer`, after user confirmation.
