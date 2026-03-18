#!/usr/bin/env python3
import json
import re
import urllib.request
from pathlib import Path


DELIVERABLE_CAPABILITIES = {
    "diagram",
    "presentation",
    "document",
    "pdf",
    "spreadsheet",
    "browser",
    "image",
}
SUPPORT_CAPABILITIES = {
    "information-design",
    "visual-design",
    "research",
    "review",
}

DELIVERABLE_PATTERNS = {
    "diagram": [
        "draw.io",
        "drawio",
        "diagrams.net",
        "architecture diagram",
        "system diagram",
        "flowchart",
        "process map",
        "diagram",
        "架构图",
        "流程图",
        "总览图",
        "关系图",
        "示意图",
    ],
    "presentation": [
        ".pptx",
        "powerpoint",
        "presentation",
        "slide deck",
        "slides",
        "slide",
        "pptx",
        "ppt",
        "deck",
        "演示文稿",
        "幻灯片",
        "汇报",
    ],
    "document": [
        ".docx",
        "document",
        "report",
        "memo",
        "brief",
        "docx",
        "word",
        "文档",
        "报告",
        "资料",
        "说明",
        "材料",
    ],
    "pdf": [
        ".pdf",
        " pdf ",
        "pdf",
    ],
    "spreadsheet": [
        ".xlsx",
        ".csv",
        ".tsv",
        "spreadsheet",
        "excel",
        "xlsx",
        "csv",
        "tsv",
        "表格",
        "excel 表",
        "excel表",
    ],
    "browser": [
        "playwright",
        "browser",
        "website",
        "web page",
        "web",
        "网页",
        "浏览器",
        "网站",
    ],
    "image": [
        "screenshot",
        "screen capture",
        "image",
        "截图",
        "配图",
    ],
}

ACTION_PATTERNS = {
    "create": ["create", "make", "build", "draw", "generate", "做", "画", "生成", "制作"],
    "explain": ["introduce", "overview", "explain", "walk through", "介绍", "总览", "讲清楚", "说明"],
    "summarize": ["summarize", "summary", "提炼", "总结", "归纳"],
    "review": ["review", "check", "validate", "audit", "核对", "校验", "审校", "复核", "检查"],
    "convert": ["convert", "turn into", "export", "转换", "转成", "输出成"],
    "analyze": ["analyze", "analysis", "investigate", "分析", "梳理", "拆解"],
    "organize": ["organize", "clean up", "整理", "归类", "规范化"],
}

QUALITY_GOAL_PATTERNS = {
    "clarity": ["clear", "clarity", "structured", "structure", "清晰", "结构化", "条理", "讲清楚", "一页讲明白"],
    "speed": ["fast", "quick", "first draft", "先出首版", "快速", "先给首版", "尽快"],
    "accuracy": ["accurate", "accuracy", "correct", "精准", "准确", "核对", "校验"],
    "visual-polish": ["beautiful", "professional", "aesthetic", "visual", "layout", "好看", "专业", "美观", "审美", "视觉"],
    "teachability": ["overview", "teach", "training", "walk through", "introduce", "总览", "介绍", "培训", "汇报", "讲清楚"],
    "editability": ["editable", "draw.io", "drawio", ".pptx", ".docx", ".xlsx", "可编辑"],
}

PROCESS_INTENT_PATTERNS = {
    "planning": [
        "plan",
        "planning",
        "roadmap",
        "implementation plan",
        "multi-step",
        "规划",
        "方案",
        "计划",
        "实施计划",
        "分步",
        "步骤",
        "落地",
        "开发",
        "产品",
        "app",
        "应用",
    ],
    "brainstorming": [
        "brainstorm",
        "ideate",
        "think through",
        "梳理",
        "思路",
        "设计",
        "拆解",
        "想清楚",
        "构思",
    ],
    "debugging": [
        "debug",
        "bug",
        "failure",
        "unexpected",
        "调试",
        "排查",
        "故障",
        "报错",
    ],
    "reviewing": [
        "review",
        "verify",
        "feedback",
        "审查",
        "复核",
        "校验",
        "检查",
    ],
}

QUALITY_TO_SUPPORT = {
    "clarity": "information-design",
    "teachability": "information-design",
    "visual-polish": "visual-design",
    "accuracy": "review",
}

SUPPORT_PATTERNS = {
    "information-design": [
        "information design",
        "storytelling",
        "outline",
        "structure",
        "structured",
        "storyline",
        "canvas",
        "讲清楚",
        "总览",
        "结构化",
    ],
    "visual-design": [
        "visual design",
        "brand",
        "layout",
        "visual",
        "aesthetic",
        "canvas",
        "ui",
        "ux",
        "好看",
        "专业",
        "美观",
    ],
    "research": [
        "research",
        "documentation",
        "docs",
        "reference",
        "brief",
        "writer",
        "资料",
        "调研",
        "研究",
    ],
    "review": [
        "review",
        "validate",
        "verification",
        "check",
        "audit",
        "审校",
        "核对",
        "校验",
    ],
}

LANGUAGE_PATTERNS = ["中文", "英文", "english", "chinese"]
LAYOUT_PATTERNS = ["横向", "纵向", "left to right", "top to bottom", "layout", "一页"]
EXPLICIT_PRESENTATION_ARTIFACT_PATTERNS = [
    ".pptx",
    "powerpoint",
    "presentation",
    "slide deck",
    "slides",
    "slide",
    "pptx",
    "ppt",
    "deck",
    "演示文稿",
    "幻灯片",
]
STOPWORDS = {
    "a",
    "an",
    "and",
    "or",
    "the",
    "to",
    "it",
    "of",
    "in",
    "on",
    "for",
    "with",
    "into",
    "from",
    "use",
    "using",
    "user",
    "when",
    "where",
    "while",
    "by",
    "as",
}
GENERIC_TOPIC_TOKENS = {
    "skill",
    "router",
    "drawio",
    "draw.io",
    "diagram",
    "architecture",
    "overview",
    "report",
    "ppt",
    "pdf",
    "excel",
    "中文",
    "英文",
    "专业",
    "汇报",
    "总览",
    "画图",
    "架构图",
}
PROCESS_SKILL_NAMES = {
    "brainstorming",
    "writing-plans",
    "executing-plans",
    "systematic-debugging",
    "requesting-code-review",
    "receiving-code-review",
    "verification-before-completion",
    "using-superpowers",
}
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-\.\+/#]*")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
CHINESE_CHUNK_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def expand_path(path_text):
    return Path(path_text).expanduser().resolve()


def load_json(path_text):
    with open(expand_path(path_text), "r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize_text(text):
    return f" {(text or '').lower()} "


def tokenize(text):
    return {token for token in TOKEN_RE.findall((text or "").lower()) if token not in STOPWORDS}


def find_pattern_positions(text, patterns):
    haystack = normalize_text(text)
    positions = []
    for pattern in patterns:
        needle = pattern.lower()
        index = haystack.find(needle)
        if index >= 0:
            positions.append(index)
    return positions


def collect_ordered_matches(text, mapping):
    matches = []
    for name, patterns in mapping.items():
        positions = find_pattern_positions(text, patterns)
        if positions:
            matches.append((min(positions), name))
    matches.sort(key=lambda item: (item[0], item[1]))
    return [name for _, name in matches]


def contains_any(text, patterns):
    return bool(find_pattern_positions(text, patterns))


def prefers_chinese(text):
    return bool(CJK_RE.search(text or ""))


def parse_frontmatter(skill_md_text):
    match = FRONTMATTER_RE.match(skill_md_text)
    if not match:
        return {}
    fields = {}
    for raw_line in match.group(1).splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields


def infer_deliverables(text):
    deliverables = collect_ordered_matches(text, DELIVERABLE_PATTERNS)
    if "diagram" in deliverables and "presentation" in deliverables and not contains_any(text, EXPLICIT_PRESENTATION_ARTIFACT_PATTERNS):
        deliverables = [cap for cap in deliverables if cap != "presentation"]
    if "pdf" in deliverables and "presentation" in deliverables and contains_any(text, ACTION_PATTERNS["summarize"] + ACTION_PATTERNS["convert"]):
        ordered = ["pdf", "presentation"]
        ordered.extend(cap for cap in deliverables if cap not in ordered)
        return ordered
    return deliverables


def infer_actions(text, deliverables):
    actions = collect_ordered_matches(text, ACTION_PATTERNS)
    if not actions and deliverables:
        return ["create"]
    if not actions and contains_any(text, PROCESS_INTENT_PATTERNS["planning"] + PROCESS_INTENT_PATTERNS["brainstorming"]):
        return ["analyze"]
    return actions


def infer_quality_goals(text):
    return collect_ordered_matches(text, QUALITY_GOAL_PATTERNS)


def infer_process_intents(text):
    return collect_ordered_matches(text, PROCESS_INTENT_PATTERNS)


def detect_topic_signal(text):
    tokens = tokenize(text)
    if any(token not in GENERIC_TOPIC_TOKENS and len(token) > 3 for token in tokens):
        return True
    chinese_chunks = [chunk for chunk in CHINESE_CHUNK_RE.findall(text or "") if chunk not in GENERIC_TOPIC_TOKENS]
    return bool(chinese_chunks)


def infer_bounded_request(text, deliverables, actions, quality_goals):
    signals = 0
    if deliverables:
        signals += 1
    if actions:
        signals += 1
    if quality_goals:
        signals += 1
    if contains_any(text, LANGUAGE_PATTERNS) or contains_any(text, LAYOUT_PATTERNS):
        signals += 1
    if detect_topic_signal(text):
        signals += 1
    return signals >= 3


def infer_task(task_text):
    deliverables = infer_deliverables(task_text)
    actions = infer_actions(task_text, deliverables)
    quality_goals = infer_quality_goals(task_text)
    process_intents = infer_process_intents(task_text)
    primary_deliverable = deliverables[0] if deliverables else None

    required_capabilities = []
    if primary_deliverable:
        required_capabilities.append(primary_deliverable)
    for capability in deliverables[1:]:
        if capability not in required_capabilities:
            required_capabilities.append(capability)

    optional_support = []
    for goal in quality_goals:
        support_capability = QUALITY_TO_SUPPORT.get(goal)
        if support_capability and support_capability not in optional_support:
            optional_support.append(support_capability)

    bounded_request = infer_bounded_request(task_text, deliverables, actions, quality_goals)
    return {
        "task": task_text,
        "tokens": sorted(tokenize(task_text)),
        "task_profile": {
            "deliverable": primary_deliverable,
            "actions": actions,
            "quality_goals": quality_goals,
            "bounded_request": bounded_request,
            "process_intents": process_intents,
            "user_language": "zh" if prefers_chinese(task_text) else "en",
        },
        "required_capabilities": required_capabilities,
        "optional_support_capabilities": optional_support,
        "process_intents": process_intents,
    }


def finalize_task_info(task_info, decision):
    final_task_profile = dict(task_info.get("task_profile", {}))
    final_task_profile.update(decision.get("task_profile", {}))

    required_capabilities = list(decision.get("required_capabilities") or task_info.get("required_capabilities", []))
    optional_support_capabilities = list(
        decision.get("optional_support_capabilities") or task_info.get("optional_support_capabilities", [])
    )

    finalized = dict(task_info)
    finalized["task_profile"] = final_task_profile
    finalized["required_capabilities"] = required_capabilities
    finalized["optional_support_capabilities"] = optional_support_capabilities
    return finalized


def truncate_text(text, max_chars):
    text = (text or "").strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def compact_constraints_for_reasoning(constraints):
    important_keys = (
        "process_only",
        "context_only",
        "mutating",
        "read_only",
        "requires_network",
        "interactive",
        "manifest_only",
    )
    compact = {}
    for key in important_keys:
        if key in constraints and constraints[key]:
            compact[key] = constraints[key]
    return compact


def summarize_executor_for_reasoning(executor, summary_config=None):
    summary_config = summary_config or {}
    description_max_chars = int(summary_config.get("description_max_chars", 140))
    keywords_limit = int(summary_config.get("keywords_limit", 8))
    capabilities_limit = int(summary_config.get("capabilities_limit", 8))
    return {
        "executor_id": executor["executor_id"],
        "executor_type": executor["executor_type"],
        "name": executor["name"],
        "source": executor.get("source"),
        "tool_family": executor.get("tool_family"),
        "capabilities": list(executor.get("capabilities", []))[:capabilities_limit],
        "keywords": list(executor.get("keywords", []))[:keywords_limit],
        "description": truncate_text(executor.get("description", ""), description_max_chars),
        "constraints": compact_constraints_for_reasoning(executor.get("constraints", {})),
    }


def process_intent_match_score(executor, process_intents):
    if not process_intents:
        return 0
    haystack = " ".join(
        [
            executor.get("name", ""),
            executor.get("description", ""),
            " ".join(executor.get("keywords", [])),
        ]
    ).lower()
    score = 0
    for intent in process_intents:
        if intent == "planning" and any(token in haystack for token in ("plan", "planning", "方案", "计划")):
            score += 25
        if intent == "brainstorming" and any(token in haystack for token in ("brainstorm", "设计", "梳理", "思路")):
            score += 25
        if intent == "debugging" and any(token in haystack for token in ("debug", "bug", "调试", "排查")):
            score += 25
        if intent == "reviewing" and any(token in haystack for token in ("review", "校验", "复核", "检查")):
            score += 25
    return score


def score_executor_for_stage_one(task_info, executor):
    score = 0
    reasons = []
    required = set(task_info.get("required_capabilities", []))
    optional = set(task_info.get("optional_support_capabilities", []))
    process_intents = task_info.get("process_intents", [])
    task_profile = task_info.get("task_profile", {})
    bounded_request = bool(task_profile.get("bounded_request"))
    has_deliverable = bool(task_profile.get("deliverable"))
    open_ended_process_task = not has_deliverable and (
        bool(process_intents) or not task_profile.get("actions")
    )

    capabilities = set(executor.get("capabilities", []))
    deliverable_caps = set(executor.get("deliverable_capabilities", []))
    support_caps = set(executor.get("support_capabilities", []))
    constraints = executor.get("constraints", {})
    text_tokens = set(task_info.get("tokens", []))
    keyword_overlap = text_tokens & set(executor.get("keywords", []))
    description_overlap = text_tokens & tokenize(executor.get("description", ""))

    required_overlap = capabilities & required
    optional_overlap = (capabilities | support_caps) & optional

    if required_overlap:
        score += 80 + 25 * len(required_overlap)
        reasons.append("required-capability")
    if task_profile.get("deliverable") and task_profile["deliverable"] in deliverable_caps:
        score += 50
        reasons.append("deliverable-match")
    if optional_overlap:
        score += 24 * len(optional_overlap)
        reasons.append("support-capability")
    if keyword_overlap:
        score += 4 * len(keyword_overlap)
        reasons.append("keyword-overlap")
    if description_overlap:
        score += 2 * len(description_overlap)
        reasons.append("description-overlap")

    process_score = process_intent_match_score(executor, process_intents)
    if process_score:
        score += process_score
        reasons.append("process-intent")

    if constraints.get("process_only"):
        if bounded_request and has_deliverable:
            score -= 120
            reasons.append("bounded-process-penalty")
        elif open_ended_process_task:
            score += 30
            reasons.append("open-ended-process-boost")
        elif not process_intents:
            score -= 40
            reasons.append("unneeded-process-penalty")

    if executor.get("executor_type") == "mcp_resource":
        if required_overlap or optional_overlap:
            score += 20
            reasons.append("context-match")
        elif not keyword_overlap and not description_overlap:
            score -= 10
    elif executor.get("executor_type") == "mcp_tool":
        if required_overlap or optional_overlap:
            score += 18
            reasons.append("tool-capability")
        elif constraints.get("manifest_only") and not keyword_overlap and not description_overlap:
            score -= 8

    if executor.get("name", "").lower() in normalize_text(task_info.get("task", "")):
        score += 18
        reasons.append("explicit-name")

    return score, reasons


def classify_stage_one_bucket(task_info, executor):
    executor_type = executor.get("executor_type")
    if executor_type in {"mcp_tool", "mcp_resource"}:
        return "mcp"

    constraints = executor.get("constraints", {})
    if constraints.get("process_only"):
        return "process_skill"

    required = set(task_info.get("required_capabilities", []))
    optional = set(task_info.get("optional_support_capabilities", []))
    task_profile = task_info.get("task_profile", {})
    deliverable_caps = set(executor.get("deliverable_capabilities", []))
    support_caps = set(executor.get("support_capabilities", []))
    capabilities = set(executor.get("capabilities", []))

    if required & (capabilities | deliverable_caps):
        return "artifact_skill"
    if optional & (capabilities | support_caps):
        return "support_skill"
    if task_profile.get("deliverable") and task_profile["deliverable"] in deliverable_caps:
        return "artifact_skill"
    if support_caps:
        return "support_skill"
    return "fallback"


def prepare_reasoning_executors(task_info, executors, config):
    reasoning_config = (config or {}).get("reasoning", {})
    stage_one = dict(reasoning_config.get("stage_one", {}))
    if not stage_one.get("enabled", True):
        selected = list(executors)
        meta = {
            "enabled": False,
            "total_count": len(executors),
            "selected_count": len(selected),
            "pruned_count": 0,
            "overflow_count": 0,
            "selected_executor_ids": [item["executor_id"] for item in selected],
            "counts_by_type": {},
            "selected_details": [],
            "pruned_details": [],
        }
        return selected, meta

    keep_all_under = int(stage_one.get("keep_all_under", 10))
    candidate_limit = int(stage_one.get("candidate_limit", 12))
    artifact_skill_limit = int(stage_one.get("artifact_skill_limit", max(1, candidate_limit // 2 or 1)))
    support_skill_limit = int(stage_one.get("support_skill_limit", max(1, candidate_limit // 4 or 1)))
    mcp_limit = int(stage_one.get("mcp_limit", max(1, candidate_limit // 4 or 1)))
    diversity_overflow_limit = int(stage_one.get("diversity_overflow_limit", 1))
    if len(executors) <= keep_all_under and len(executors) <= candidate_limit:
        selected = list(executors)
        meta = {
            "enabled": True,
            "total_count": len(executors),
            "selected_count": len(selected),
            "pruned_count": 0,
            "overflow_count": 0,
            "selected_executor_ids": [item["executor_id"] for item in selected],
            "counts_by_type": build_counts_by_type(selected),
            "selected_details": [],
            "pruned_details": [],
        }
        return selected, meta

    scored_entries = []
    for executor in executors:
        score, reasons = score_executor_for_stage_one(task_info, executor)
        bucket = classify_stage_one_bucket(task_info, executor)
        scored_entries.append(
            {
                "score": score,
                "executor_id": executor["executor_id"],
                "reasons": reasons,
                "executor": executor,
                "bucket": bucket,
                "must_keep": (
                    (
                        executor.get("executor_type") == "skill"
                        and not executor.get("constraints", {}).get("process_only")
                        and bool(
                            set(executor.get("deliverable_capabilities", []))
                            & set(task_info.get("required_capabilities", []))
                        )
                    )
                    or "explicit-name" in reasons
                ),
            }
        )
    scored_entries.sort(
        key=lambda item: (
            -item["score"],
            item["executor"].get("executor_type") != "skill",
            item["executor"].get("source") != "local-skill",
            item["executor_id"],
        )
    )

    selected = []
    seen = set()
    selected_details = []

    def add_entry(entry, selected_because, allow_overflow=False):
        executor = entry["executor"]
        if executor["executor_id"] in seen:
            return False
        limit = candidate_limit + diversity_overflow_limit if allow_overflow else candidate_limit
        if len(selected) >= limit:
            return False
        seen.add(executor["executor_id"])
        selected.append(executor)
        selected_details.append(
            {
                "executor_id": executor["executor_id"],
                "bucket": entry["bucket"],
                "stage_one_score": entry["score"],
                "stage_one_reasons": list(entry["reasons"]),
                "selected_because": selected_because,
            }
        )
        return True

    for entry in scored_entries:
        if entry["must_keep"]:
            add_entry(entry, "must-keep")

    artifact_candidates = []
    support_candidates = []
    mcp_candidates = []
    fallback_candidates = []

    for entry in scored_entries:
        executor = entry["executor"]
        if executor["executor_id"] in seen:
            continue
        executor_type = executor.get("executor_type")
        if executor_type in {"mcp_tool", "mcp_resource"}:
            mcp_candidates.append(entry)
            continue
        if set(executor.get("deliverable_capabilities", [])) & set(task_info.get("required_capabilities", [])):
            artifact_candidates.append(entry)
            continue
        if set(executor.get("support_capabilities", [])) & set(task_info.get("optional_support_capabilities", [])):
            support_candidates.append(entry)
            continue
        if entry["bucket"] == "artifact_skill":
            artifact_candidates.append(entry)
            continue
        if entry["bucket"] == "support_skill":
            support_candidates.append(entry)
            continue
        fallback_candidates.append(entry)

    for entry in artifact_candidates[:artifact_skill_limit]:
        add_entry(entry, "artifact-slot")
    for entry in support_candidates[:support_skill_limit]:
        add_entry(entry, "support-slot", allow_overflow=len(selected) >= candidate_limit)
    for entry in mcp_candidates[:mcp_limit]:
        add_entry(entry, "mcp-slot", allow_overflow=len(selected) >= candidate_limit)
    for entry in fallback_candidates:
        if entry["score"] <= 0 and selected:
            continue
        add_entry(entry, "fallback-rank")

    if not selected:
        fallback_seed = scored_entries[:candidate_limit]
        selected = [item["executor"] for item in fallback_seed]
        selected_details = [
            {
                "executor_id": item["executor_id"],
                "bucket": item["bucket"],
                "stage_one_score": item["score"],
                "stage_one_reasons": list(item["reasons"]),
                "selected_because": "fallback-seed",
            }
            for item in fallback_seed
        ]
        seen = {item["executor_id"] for item in fallback_seed}

    pruned_details = []
    for entry in scored_entries:
        if entry["executor_id"] in seen:
            continue
        pruned_because = "candidate-limit"
        if entry["score"] <= 0 and selected:
            pruned_because = "low-score"
        pruned_details.append(
            {
                "executor_id": entry["executor_id"],
                "bucket": entry["bucket"],
                "stage_one_score": entry["score"],
                "stage_one_reasons": list(entry["reasons"]),
                "pruned_because": pruned_because,
            }
        )

    meta = {
        "enabled": True,
        "total_count": len(executors),
        "selected_count": len(selected),
        "pruned_count": max(0, len(executors) - len(selected)),
        "overflow_count": max(0, len(selected) - candidate_limit),
        "target_candidate_limit": candidate_limit,
        "selected_executor_ids": [item["executor_id"] for item in selected],
        "counts_by_type": build_counts_by_type(selected),
        "selected_details": selected_details,
        "pruned_details": pruned_details,
    }
    return selected, meta


def build_counts_by_type(executors):
    counts = {}
    for executor in executors:
        executor_type = executor.get("executor_type", "unknown")
        counts[executor_type] = counts.get(executor_type, 0) + 1
    return counts


def infer_capabilities_from_text(text):
    deliverable_caps = [cap for cap in DELIVERABLE_PATTERNS if contains_any(text, DELIVERABLE_PATTERNS[cap])]
    support_caps = [cap for cap in SUPPORT_PATTERNS if contains_any(text, SUPPORT_PATTERNS[cap])]
    capabilities = []
    for capability in deliverable_caps + support_caps:
        if capability not in capabilities:
            capabilities.append(capability)
    return capabilities, deliverable_caps, support_caps


def normalize_constraints(raw_constraints=None, process_only=False, read_only=None, context_only=False):
    constraints = {
        "process_only": bool(process_only),
        "read_only": True if read_only is None else bool(read_only),
        "context_only": bool(context_only),
        "requires_network": False,
        "interactive": False,
        "mutating": False,
    }
    for key, value in (raw_constraints or {}).items():
        constraints[key] = value
    if constraints["context_only"]:
        constraints["read_only"] = True
    return constraints


def enrich_executor(entry):
    name = entry.get("name", "")
    description = entry.get("description", "")
    keywords = sorted(set(entry.get("keywords", [])) | tokenize(f"{name} {description} {' '.join(entry.get('keywords', []))}"))
    seeded_capabilities = list(entry.get("capabilities", []))
    inferred_capabilities, inferred_deliverables, inferred_support = infer_capabilities_from_text(
        f"{name} {description} {' '.join(keywords)}"
    )

    capabilities = []
    for capability in seeded_capabilities + inferred_capabilities:
        if capability not in capabilities:
            capabilities.append(capability)

    deliverable_capabilities = []
    support_capabilities = []
    for capability in capabilities:
        if capability in DELIVERABLE_CAPABILITIES and capability not in deliverable_capabilities:
            deliverable_capabilities.append(capability)
        if capability in SUPPORT_CAPABILITIES and capability not in support_capabilities:
            support_capabilities.append(capability)
    for capability in inferred_deliverables:
        if capability not in deliverable_capabilities:
            deliverable_capabilities.append(capability)
    for capability in inferred_support:
        if capability not in support_capabilities:
            support_capabilities.append(capability)

    constraints = normalize_constraints(
        raw_constraints=entry.get("constraints"),
        process_only=entry.get("process_only", False),
        read_only=entry.get("read_only"),
        context_only=entry.get("context_only", False),
    )
    if entry.get("tool_family") == "superpowers" or name in PROCESS_SKILL_NAMES:
        constraints["process_only"] = True
    if entry.get("executor_type") == "mcp_resource":
        constraints["context_only"] = True
        constraints["read_only"] = True

    enriched = dict(entry)
    enriched["keywords"] = keywords
    enriched["capabilities"] = capabilities
    enriched["deliverable_capabilities"] = deliverable_capabilities
    enriched["support_capabilities"] = support_capabilities
    enriched["constraints"] = constraints
    return enriched


def dedupe_entries(entries, key_fields=None):
    key_fields = key_fields or ("executor_id", "name", "source", "path", "repo")
    seen = set()
    deduped = []
    for entry in entries:
        key = tuple(entry.get(field) for field in key_fields)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def merge_executor_with_index(executor, index_entry):
    merged = dict(executor)
    merged["keywords"] = sorted(set(executor.get("keywords", [])) | set(index_entry.get("keywords", [])))
    merged["capabilities"] = list(index_entry.get("capabilities", executor.get("capabilities", [])))
    if index_entry.get("description") and not executor.get("description"):
        merged["description"] = index_entry["description"]
    merged_constraints = dict(executor.get("constraints", {}))
    merged_constraints.update(index_entry.get("constraints", {}))
    merged["constraints"] = merged_constraints
    return enrich_executor(merged)


def load_router_assets(base_dir):
    base_path = expand_path(base_dir)
    assets_dir = base_path / "assets"
    config = load_json(assets_dir / "router-config.json")
    local_index = []
    for entry in load_json(assets_dir / "skill-index.json"):
        item = dict(entry)
        item.setdefault("executor_type", "skill")
        item.setdefault("executor_id", f"skill:{item.get('source', 'index')}:{item.get('name')}")
        item.setdefault("tool_family", "skill-index")
        item.setdefault("invocation_ref", item.get("path"))
        local_index.append(enrich_executor(item))
    return config, local_index


def build_install_url(entry):
    if entry.get("source") == "openai-curated":
        return f"https://github.com/openai/skills/tree/main/{entry['path']}"
    if entry.get("repo") == "ComposioHQ/awesome-claude-skills":
        return f"https://github.com/{entry['repo']}/tree/master/{entry['path']}"
    if entry.get("repo") == "numman-ali/n-skills":
        return f"https://github.com/{entry['repo']}/tree/main/{entry['path']}"
    if entry.get("repo") and entry.get("path"):
        return f"https://github.com/{entry['repo']}/tree/main/{entry['path']}"
    return None


def api_json(url, timeout):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "codex-skill-router",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def safe_fetch(url, timeout):
    try:
        return api_json(url, timeout), None
    except Exception as exc:
        return None, str(exc)


def fetch_openai_curated(timeout):
    data, err = safe_fetch("https://api.github.com/repos/openai/skills/contents/skills/.curated", timeout)
    entries = []
    if err or not isinstance(data, list):
        return entries, err
    for item in data:
        if item.get("type") != "dir":
            continue
        name = item["name"]
        entries.append(
            enrich_executor(
                {
                    "executor_id": f"skill:openai-curated:{name}",
                    "executor_type": "skill",
                    "name": name,
                    "source": "openai-curated",
                    "tool_family": "openai",
                    "path": f"skills/.curated/{name}",
                    "description": "",
                    "invocation_ref": f"skills/.curated/{name}",
                }
            )
        )
    return entries, None


def fetch_composio_index(timeout):
    data, err = safe_fetch("https://api.github.com/repos/ComposioHQ/awesome-claude-skills/contents", timeout)
    entries = []
    if err or not isinstance(data, list):
        return entries, err
    ignored = {".github", "docs", "scripts", "assets"}
    for item in data:
        name = item.get("name", "")
        if item.get("type") != "dir" or name.startswith(".") or name in ignored:
            continue
        entries.append(
            enrich_executor(
                {
                    "executor_id": f"skill:github-index:composio:{name}",
                    "executor_type": "skill",
                    "name": name,
                    "source": "github-index",
                    "tool_family": "claude",
                    "repo": "ComposioHQ/awesome-claude-skills",
                    "path": name,
                    "description": "",
                    "invocation_ref": name,
                }
            )
        )
    return entries, None


def fetch_n_skills_index(timeout):
    data, err = safe_fetch("https://api.github.com/repos/numman-ali/n-skills/contents/skills", timeout)
    entries = []
    if err or not isinstance(data, list):
        return entries, err
    for category in data:
        if category.get("type") != "dir":
            continue
        category_name = category.get("name")
        nested, nested_err = safe_fetch(category.get("url"), timeout)
        if nested_err or not isinstance(nested, list):
            continue
        for item in nested:
            if item.get("type") != "dir":
                continue
            name = item.get("name")
            path = f"skills/{category_name}/{name}"
            entries.append(
                enrich_executor(
                    {
                        "executor_id": f"skill:github-index:n-skills:{category_name}:{name}",
                        "executor_type": "skill",
                        "name": name,
                        "source": "github-index",
                        "tool_family": "agents",
                        "repo": "numman-ali/n-skills",
                        "path": path,
                        "description": "",
                        "invocation_ref": path,
                    }
                )
            )
    return entries, None


def fetch_remote_indexes(config):
    timeout = int(config.get("remote_fetch_timeout_seconds", 8))
    all_entries = []
    errors = []
    for fetcher in (fetch_openai_curated, fetch_composio_index, fetch_n_skills_index):
        entries, err = fetcher(timeout)
        if entries:
            all_entries.extend(entries)
        if err:
            errors.append(err)
    return dedupe_entries(all_entries, key_fields=("executor_id", "name", "source", "path", "repo")), errors


def recommendation_match_score(task_info, entry, missing_caps):
    score = 0
    reasons = []
    capability_overlap = sorted(set(entry.get("capabilities", [])) & set(missing_caps))
    if capability_overlap:
        score += 12 * len(capability_overlap)
        reasons.append(f"covers missing capabilities {capability_overlap}")
    keyword_overlap = sorted(set(entry.get("keywords", [])) & set(task_info.get("tokens", [])))
    if keyword_overlap:
        score += 3 * len(keyword_overlap)
        reasons.append(f"keywords match {keyword_overlap[:5]}")
    description_overlap = sorted(tokenize(entry.get("description", "")) & set(task_info.get("tokens", [])))
    if description_overlap:
        score += len(description_overlap)
        reasons.append(f"description overlap {description_overlap[:5]}")
    return score, reasons


def build_recommendations(task_info, missing_caps, local_index, remote_entries, installed_executor_ids):
    if not missing_caps:
        return []

    candidates = []
    all_entries = dedupe_entries(local_index + remote_entries, key_fields=("executor_id", "name", "source", "path", "repo"))
    for entry in all_entries:
        if entry.get("executor_id") in installed_executor_ids:
            continue
        if entry.get("executor_type") != "skill":
            continue
        score, reasons = recommendation_match_score(task_info, entry, missing_caps)
        if score <= 0:
            continue
        candidates.append(
            {
                "executor_type": "skill",
                "name": entry.get("name"),
                "source": entry.get("source"),
                "provider_family": entry.get("source"),
                "repo": entry.get("repo"),
                "path": entry.get("path"),
                "capabilities": entry.get("capabilities", []),
                "support_capabilities": entry.get("support_capabilities", []),
                "reasons": reasons,
                "matched_capabilities": sorted(set(entry.get("capabilities", [])) & set(missing_caps)),
                "install_url": build_install_url(entry),
                "score": score,
            }
        )
    candidates.sort(key=lambda item: (-item["score"], item["name"]))
    return candidates[:12]


def build_mcp_recommendations(missing_executors):
    recommendations = []
    for item in missing_executors or []:
        if item.get("executor_type") not in {"mcp_tool", "mcp_resource"}:
            continue
        provider_family = item.get("provider_family") or "unknown"
        supports_auto_install = provider_family in {"codex", "kiro"}
        recommendations.append(
            {
                "name": item.get("name"),
                "executor_type": item.get("executor_type"),
                "provider_family": provider_family,
                "reason": item.get("reason"),
                "install_mode": "provider-adapter" if supports_auto_install else "recommend-only",
                "supports_auto_install": supports_auto_install,
                "availability": "supported" if supports_auto_install else "not_supported_yet",
            }
        )
    return recommendations
