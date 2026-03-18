import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from discovery_providers import (
    discover_session_mcp_executors,
    discover_skill_roots,
    kiro_mcp_manifest_provider,
)
from execution_runner import execute_selected_plan
from install_adapters import build_installation_plan
from mcp_install_providers import build_mcp_install_adapter
from orchestration_runner import build_initial_orchestration_state, advance_orchestration_state
from plan_route import merge_local_metadata
from policy_validator import validate_route
from router_lib import infer_task, load_router_assets, prepare_reasoning_executors, summarize_executor_for_reasoning
from step_acceptance import build_acceptance_gate, build_step_receipt


class SkillRouterV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_dir = Path(__file__).resolve().parents[1]

    def test_infer_task_adds_quality_goals_for_generic_document_optimization(self):
        task_info = infer_task("工作区里有一份方案文档.docx，帮我优化一下。")

        self.assertEqual(task_info["task_profile"]["deliverable"], "document")
        self.assertIn("optimize", task_info["task_profile"]["actions"])
        self.assertIn("clarity", task_info["task_profile"]["quality_goals"])
        self.assertIn("visual-polish", task_info["task_profile"]["quality_goals"])
        self.assertIn("editability", task_info["task_profile"]["quality_goals"])
        self.assertIn("information-design", task_info["optional_support_capabilities"])
        self.assertIn("visual-design", task_info["optional_support_capabilities"])
        self.assertTrue(task_info["task_profile"]["bounded_request"])
        self.assertEqual(task_info["task_profile"]["process_intents"], [])
        self.assertEqual(task_info["task_profile"]["task_stage"], "delivery")
        self.assertIn("documentation", task_info["task_profile"]["needed_capability_groups"])

    def test_infer_task_adds_stage_and_capability_groups_for_app_requests(self):
        discovery_task = infer_task("我打算开发一款手机app，用于打卡健身的")
        design_task = infer_task("帮我设计一个手机app的登录页界面，并给出前端实现思路")

        self.assertEqual(discovery_task["task_profile"]["task_stage"], "discovery")
        self.assertEqual(discovery_task["task_profile"]["process_intents"], ["planning"])
        self.assertIn("product-definition", discovery_task["task_profile"]["needed_capability_groups"])
        self.assertIn("information-design", discovery_task["task_profile"]["needed_capability_groups"])
        self.assertNotIn("frontend", discovery_task["task_profile"]["needed_capability_groups"])

        self.assertEqual(design_task["task_profile"]["task_stage"], "design")
        self.assertEqual(design_task["task_profile"]["process_intents"], [])
        self.assertIn("ui-design", design_task["task_profile"]["needed_capability_groups"])
        self.assertIn("frontend", design_task["task_profile"]["needed_capability_groups"])

    def test_local_executor_profiles_override_noisy_heuristics_and_hide_meta_skills(self):
        _, local_index, executor_profiles = load_router_assets(self.base_dir)
        executors = [
            {
                "executor_id": "skill:codex:pdf",
                "executor_type": "skill",
                "name": "pdf",
                "source": "local-skill",
                "tool_family": "codex",
                "description": "Use when tasks involve reading, creating, or reviewing PDF files where rendering and layout matter.",
                "constraints": {},
            },
            {
                "executor_id": "skill:codex:using-superpowers",
                "executor_type": "skill",
                "name": "using-superpowers",
                "source": "local-skill",
                "tool_family": "codex",
                "description": "Use when starting any conversation.",
                "constraints": {"process_only": True},
            },
        ]

        merged = merge_local_metadata(executors, local_index, executor_profiles)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["name"], "pdf")
        self.assertEqual(merged[0]["capability_groups"], ["documentation", "information-design"])
        self.assertEqual(merged[0]["preferred_task_stages"], ["delivery"])
        self.assertNotIn("ui-design", merged[0]["capability_groups"])
        self.assertNotIn("validation", merged[0]["preferred_task_stages"])

    def test_stage_one_for_ui_design_task_prefers_design_executors_over_process_noise(self):
        _, local_index, executor_profiles = load_router_assets(self.base_dir)
        task_info = infer_task("帮我设计一个手机app的登录页界面，并给出前端实现思路")
        raw_executors = [
            {
                "executor_id": "skill:codex:playwright",
                "executor_type": "skill",
                "name": "playwright",
                "source": "local-skill",
                "tool_family": "codex",
                "description": "Use when the task requires automating a real browser from the terminal.",
                "constraints": {},
            },
            {
                "executor_id": "skill:codex:brainstorming",
                "executor_type": "skill",
                "name": "brainstorming",
                "source": "local-skill",
                "tool_family": "codex",
                "description": "Explore user intent and requirements before implementation.",
                "constraints": {"process_only": True},
            },
            {
                "executor_id": "skill:codex:writing-plans",
                "executor_type": "skill",
                "name": "writing-plans",
                "source": "local-skill",
                "tool_family": "codex",
                "description": "Turn confirmed ideas into execution plans.",
                "constraints": {"process_only": True},
            },
            {
                "executor_id": "skill:codex:pdf",
                "executor_type": "skill",
                "name": "pdf",
                "source": "local-skill",
                "tool_family": "codex",
                "description": "Read, create, or review PDF files.",
                "constraints": {},
            },
        ]
        executors = merge_local_metadata(raw_executors, local_index, executor_profiles)
        config = {
            "reasoning": {
                "stage_one": {
                    "enabled": True,
                    "keep_all_under": 0,
                    "candidate_limit": 2,
                    "artifact_skill_limit": 0,
                    "support_skill_limit": 1,
                    "mcp_limit": 0,
                    "description_max_chars": 80,
                    "keywords_limit": 6,
                }
            }
        }

        selected, _ = prepare_reasoning_executors(task_info, executors, config)
        selected_ids = {item["executor_id"] for item in selected}

        self.assertIn("skill:codex:playwright", selected_ids)
        self.assertNotIn("skill:codex:brainstorming", selected_ids)
        self.assertNotIn("skill:codex:writing-plans", selected_ids)

    def test_stage_one_open_product_discovery_avoids_explicit_capture_noise(self):
        _, local_index, executor_profiles = load_router_assets(self.base_dir)
        task_info = infer_task("我打算开发一款手机app，用于打卡健身的")
        raw_executors = [
            {
                "executor_id": "skill:codex:brainstorming",
                "executor_type": "skill",
                "name": "brainstorming",
                "source": "local-skill",
                "tool_family": "codex",
                "description": "Explore user intent and requirements before implementation.",
                "constraints": {"process_only": True},
            },
            {
                "executor_id": "skill:codex:writing-plans",
                "executor_type": "skill",
                "name": "writing-plans",
                "source": "local-skill",
                "tool_family": "codex",
                "description": "Turn confirmed ideas into execution plans.",
                "constraints": {"process_only": True},
            },
            {
                "executor_id": "skill:codex:screenshot",
                "executor_type": "skill",
                "name": "screenshot",
                "source": "local-skill",
                "tool_family": "codex",
                "description": "Capture screenshots when explicitly requested.",
                "constraints": {},
            },
        ]
        executors = merge_local_metadata(raw_executors, local_index, executor_profiles)
        config = {
            "reasoning": {
                "stage_one": {
                    "enabled": True,
                    "keep_all_under": 0,
                    "candidate_limit": 3,
                    "artifact_skill_limit": 0,
                    "support_skill_limit": 1,
                    "mcp_limit": 0,
                    "description_max_chars": 80,
                    "keywords_limit": 6,
                }
            }
        }

        selected, _ = prepare_reasoning_executors(task_info, executors, config)
        selected_ids = {item["executor_id"] for item in selected}

        self.assertIn("skill:codex:brainstorming", selected_ids)
        self.assertIn("skill:codex:writing-plans", selected_ids)
        self.assertNotIn("skill:codex:screenshot", selected_ids)

    def test_stage_one_open_product_discovery_avoids_manifest_mcp_noise(self):
        _, local_index, executor_profiles = load_router_assets(self.base_dir)
        task_info = infer_task("我打算开发一款手机app，用于打卡健身的")
        raw_executors = [
            {
                "executor_id": "mcp_tool:codex:notion",
                "executor_type": "mcp_tool",
                "name": "notion",
                "source": "mcp-manifest",
                "tool_family": "codex",
                "description": "MCP server 'notion' declared in Codex config.",
                "constraints": {"manifest_only": True},
            },
            {
                "executor_id": "mcp_tool:kiro:fetch",
                "executor_type": "mcp_tool",
                "name": "fetch",
                "source": "mcp-manifest",
                "tool_family": "kiro",
                "description": "MCP server 'fetch' declared in Kiro settings.",
                "constraints": {"manifest_only": True},
            },
            {
                "executor_id": "skill:codex:brainstorming",
                "executor_type": "skill",
                "name": "brainstorming",
                "source": "local-skill",
                "tool_family": "codex",
                "description": "Explore user intent and requirements before implementation.",
                "constraints": {"process_only": True},
            },
        ]
        executors = merge_local_metadata(raw_executors, local_index, executor_profiles)
        config = {
            "reasoning": {
                "stage_one": {
                    "enabled": True,
                    "keep_all_under": 0,
                    "candidate_limit": 3,
                    "artifact_skill_limit": 0,
                    "support_skill_limit": 0,
                    "mcp_limit": 2,
                    "description_max_chars": 80,
                    "keywords_limit": 6,
                }
            }
        }

        selected, _ = prepare_reasoning_executors(task_info, executors, config)
        selected_ids = {item["executor_id"] for item in selected}

        self.assertIn("skill:codex:brainstorming", selected_ids)
        self.assertNotIn("mcp_tool:codex:notion", selected_ids)
        self.assertNotIn("mcp_tool:kiro:fetch", selected_ids)

    def test_mcp_profiles_limit_manifest_noise_for_doc_optimization(self):
        _, local_index, executor_profiles = load_router_assets(self.base_dir)
        task_info = infer_task("工作工具里面有一份宋川 简历.docx，你帮我优化一下。")
        raw_executors = [
            {
                "executor_id": "mcp_tool:kiro:office-word",
                "executor_type": "mcp_tool",
                "name": "office-word",
                "source": "mcp-manifest",
                "tool_family": "kiro",
                "description": "MCP server 'office-word' declared in Kiro settings.",
                "constraints": {"manifest_only": True, "mutating": True},
            },
            {
                "executor_id": "mcp_tool:kiro:office-powerpoint",
                "executor_type": "mcp_tool",
                "name": "office-powerpoint",
                "source": "mcp-manifest",
                "tool_family": "kiro",
                "description": "MCP server 'office-powerpoint' declared in Kiro settings.",
                "constraints": {"manifest_only": True, "mutating": True},
            },
        ]
        executors = merge_local_metadata(raw_executors, local_index, executor_profiles)
        config = {
            "reasoning": {
                "stage_one": {
                    "enabled": True,
                    "keep_all_under": 0,
                    "candidate_limit": 2,
                    "artifact_skill_limit": 0,
                    "support_skill_limit": 0,
                    "mcp_limit": 2,
                    "description_max_chars": 80,
                    "keywords_limit": 6,
                }
            }
        }

        selected, _ = prepare_reasoning_executors(task_info, executors, config)
        selected_ids = {item["executor_id"] for item in selected}

        self.assertIn("mcp_tool:kiro:office-word", selected_ids)
        self.assertNotIn("mcp_tool:kiro:office-powerpoint", selected_ids)

    def test_stage_one_does_not_fill_irrelevant_support_slots_for_open_product_discovery(self):
        task_info = infer_task("我打算开发一款手机app，用于打卡健身的")
        executors = [
            {
                "executor_id": "skill:codex:brainstorming",
                "executor_type": "skill",
                "name": "brainstorming",
                "source": "local-skill",
                "tool_family": "codex",
                "capabilities": ["visual-design"],
                "keywords": ["brainstorm", "产品", "规划"],
                "description": "Explore product direction before implementation.",
                "constraints": {"process_only": True},
            },
            {
                "executor_id": "skill:codex:writing-plans",
                "executor_type": "skill",
                "name": "writing-plans",
                "source": "local-skill",
                "tool_family": "codex",
                "capabilities": ["planning"],
                "keywords": ["plan", "规划", "步骤"],
                "description": "Turn confirmed ideas into execution plans.",
                "constraints": {"process_only": True},
            },
            {
                "executor_id": "skill:codex:doc",
                "executor_type": "skill",
                "name": "doc",
                "source": "local-skill",
                "tool_family": "codex",
                "capabilities": ["document"],
                "keywords": ["doc", "report"],
                "description": "Document output skill.",
                "constraints": {"process_only": False},
            },
        ]
        config = {
            "reasoning": {
                "stage_one": {
                    "enabled": True,
                    "keep_all_under": 0,
                    "candidate_limit": 3,
                    "artifact_skill_limit": 1,
                    "support_skill_limit": 1,
                    "mcp_limit": 0,
                    "description_max_chars": 80,
                    "keywords_limit": 6,
                }
            }
        }

        selected, meta = prepare_reasoning_executors(task_info, executors, config)
        selected_ids = {item["executor_id"] for item in selected}

        self.assertIn("skill:codex:brainstorming", selected_ids)
        self.assertIn("skill:codex:writing-plans", selected_ids)
        self.assertNotIn("skill:codex:doc", selected_ids)
        self.assertGreater(meta["selected_count"], 0)

    def test_stage_one_selector_keeps_process_candidates_for_open_ended_product_task(self):
        task_info = infer_task("我打算开发一款手机app，用于打卡健身的")
        executors = [
            {
                "executor_id": "skill:codex:brainstorming",
                "executor_type": "skill",
                "name": "brainstorming",
                "source": "local-skill",
                "tool_family": "codex",
                "capabilities": ["planning", "information-design"],
                "keywords": ["brainstorm", "产品", "思路", "规划"],
                "description": "Explore product direction before implementation.",
                "constraints": {"process_only": True},
            },
            {
                "executor_id": "skill:codex:writing-plans",
                "executor_type": "skill",
                "name": "writing-plans",
                "source": "local-skill",
                "tool_family": "codex",
                "capabilities": ["planning"],
                "keywords": ["plan", "规划", "步骤"],
                "description": "Turn confirmed ideas into execution plans.",
                "constraints": {"process_only": True},
            },
            {
                "executor_id": "skill:codex:doc",
                "executor_type": "skill",
                "name": "doc",
                "source": "local-skill",
                "tool_family": "codex",
                "capabilities": ["document"],
                "keywords": ["doc", "report"],
                "description": "Document output skill.",
                "constraints": {"process_only": False},
            },
        ]
        config = {
            "reasoning": {
                "stage_one": {
                    "enabled": True,
                    "candidate_limit": 3,
                    "description_max_chars": 80,
                    "keywords_limit": 6,
                }
            }
        }

        selected, meta = prepare_reasoning_executors(task_info, executors, config)
        selected_ids = {item["executor_id"] for item in selected}

        self.assertIn("skill:codex:brainstorming", selected_ids)
        self.assertIn("skill:codex:writing-plans", selected_ids)
        self.assertGreater(meta["selected_count"], 0)

    def test_validate_route_rejects_quality_sensitive_bare_route_without_improvement_checks(self):
        task_info = infer_task("工作工具里面有一份宋川 简历.docx，你帮我优化一下。")
        executors = [
            {
                "executor_id": "skill:codex:doc",
                "executor_type": "skill",
                "name": "doc",
                "source": "local-skill",
                "tool_family": "codex",
                "capabilities": ["document", "visual-design", "review"],
                "keywords": ["docx", "layout", "formatting"],
                "description": "Edit and improve docx documents.",
                "constraints": {"process_only": False, "read_only": True},
            }
        ]
        decision = {
            "task_understanding": "Optimize the document for quality, readability, and presentation.",
            "task_profile": task_info["task_profile"],
            "needed_capabilities": ["document", "information-design", "visual-design"],
            "required_capabilities": ["document"],
            "optional_support_capabilities": ["information-design", "visual-design"],
            "role_findings": [
                {
                    "role_id": "delivery-role",
                    "conclusion": "The document skill can edit the file directly.",
                    "concerns": [],
                    "suggested_capabilities": ["document"],
                },
                {
                    "role_id": "quality-critic-role",
                    "conclusion": "A purely functional edit is not enough for an optimization request.",
                    "concerns": ["Information hierarchy and emphasis may still feel weak."],
                    "suggested_capabilities": ["information-design"],
                },
                {
                    "role_id": "design-editor-role",
                    "conclusion": "Layout polish and visual rhythm still need explicit attention.",
                    "concerns": ["Spacing and section hierarchy could remain flat."],
                    "suggested_capabilities": ["visual-design"],
                },
            ],
            "completion_assessment": {
                "quality_bar": "best-practical",
                "baseline_satisfied": True,
                "quality_risks": ["The route currently looks too close to a bare functional edit."],
                "optimization_opportunities": ["Add explicit polish checks before calling the step complete."],
                "reason": "This task is quality-sensitive and should not stop at artifact editability.",
            },
            "quality_gate": {
                "status": "pass",
                "reason": "The route can work if it includes explicit quality strengthening.",
                "blocking_issues": [],
            },
            "second_pass_review": {
                "verdict": "good-enough",
                "reason": "The route is acceptable only if it still carries proactive polish checks.",
                "follow_up_actions": [],
            },
            "minimal_high_quality_combo": [
                {
                    "executor_id": "skill:codex:doc",
                    "role": "primary",
                    "why": "Primary document editor.",
                }
            ],
            "missing_executors": [],
            "step_acceptance_blueprint": [
                {
                    "step_id": "optimize-doc-step-1",
                    "summary_template": "Review the optimized document draft.",
                    "acceptance_criteria": ["The document remains editable", "The content is improved"],
                    "improvement_checks": [],
                }
            ],
            "candidate_plans": [
                {
                    "plan_id": "direct-doc-optimize",
                    "summary": "Use the document skill directly.",
                    "steps": [
                        {
                            "step_id": "optimize-doc-step-1",
                            "step_type": "skill",
                            "executor_id": "skill:codex:doc",
                            "purpose": "Optimize the document",
                            "required_inputs": [],
                            "expected_output": "Optimized editable document",
                            "reads_context_only": False,
                            "may_mutate": False,
                        }
                    ],
                    "pros": ["Simple"],
                    "cons": ["May look too functional if no explicit polish pass is attached."],
                }
            ],
            "chosen_plan_id": "direct-doc-optimize",
            "chosen_plan_reason": "The document skill can edit the file directly.",
            "why_not_others": [],
            "missing_required_capabilities": [],
            "missing_optional_capabilities": [],
            "reflection_trace": [],
        }

        result = validate_route(task_info, decision, executors, {})

        self.assertFalse(result["is_valid"])
        self.assertTrue(any("bare-functional" in message for message in result["errors"]))

    def test_execution_runner_resolves_resource_context_then_hands_off_skill(self):
        route_payload = {
            "task": "读取资源后写总结",
            "task_profile": {"deliverable": "document", "bounded_request": True},
            "discovered_executors": [
                {
                    "executor_id": "mcp_resource:figma:intro",
                    "executor_type": "mcp_resource",
                    "name": "intro",
                    "invocation_ref": "file://figma/docs/intro.md",
                    "constraints": {"context_only": True, "read_only": True},
                },
                {
                    "executor_id": "skill:codex:doc",
                    "executor_type": "skill",
                    "name": "doc",
                    "invocation_ref": "C:\\Users\\super\\.codex\\skills\\doc",
                    "constraints": {"process_only": False, "read_only": True},
                },
            ],
            "routing_decision": {
                "chosen_plan": {
                    "plan_id": "resource-then-skill",
                    "steps": [
                        {
                            "step_type": "mcp_resource",
                            "executor_id": "mcp_resource:figma:intro",
                            "purpose": "Load reference context",
                            "required_inputs": [],
                            "expected_output": "Reference content",
                            "reads_context_only": True,
                            "may_mutate": False,
                        },
                        {
                            "step_type": "skill",
                            "executor_id": "skill:codex:doc",
                            "purpose": "Write the summary document",
                            "required_inputs": ["reference context"],
                            "expected_output": "Editable summary document",
                            "reads_context_only": False,
                            "may_mutate": False,
                        },
                    ],
                }
            },
            "validation_result": {"is_valid": True, "errors": [], "warnings": []},
        }
        resource_contents = {
            "mcp_resource:figma:intro": {
                "content": "Kubernetes schedules Pods onto Nodes."
            }
        }

        result = execute_selected_plan(route_payload, resource_contents=resource_contents)

        self.assertTrue(result["is_runnable"])
        self.assertEqual(result["step_results"][0]["status"], "completed")
        self.assertEqual(result["step_results"][1]["status"], "requires_host_execution")
        self.assertEqual(result["aggregated_context"][0]["executor_id"], "mcp_resource:figma:intro")
        self.assertIn("Kubernetes schedules Pods", result["step_results"][1]["host_execution_request"]["context_preview"])

    def test_step_acceptance_surfaces_proactive_improvement_questions(self):
        step = {
            "step_id": "doc-step-1",
            "step_type": "skill",
            "executor_id": "skill:codex:doc",
            "expected_output": "Optimized editable document",
        }
        executor = {
            "executor_id": "skill:codex:doc",
            "executor_type": "skill",
            "name": "doc",
        }
        blueprint = {
            "step_id": "doc-step-1",
            "summary_template": "Review the optimized document.",
            "acceptance_criteria": ["The document is clearer", "The document stays editable"],
            "improvement_checks": [
                "Would a stronger hierarchy make key achievements easier to scan?",
                "Is there any low-cost spacing or emphasis adjustment worth doing before acceptance?",
            ],
        }

        receipt = build_step_receipt(step=step, executor=executor, payload={"content": "Draft"}, blueprint=blueprint)
        gate = build_acceptance_gate(receipt)

        self.assertEqual(receipt["improvement_checks"], blueprint["improvement_checks"])
        self.assertEqual(gate["proactive_review_questions"], blueprint["improvement_checks"])

    def test_execution_runner_completes_mock_tool_before_handing_off_skill(self):
        route_payload = {
            "task": "先取设计上下文再画图",
            "task_profile": {"deliverable": "diagram", "bounded_request": True},
            "discovered_executors": [
                {
                    "executor_id": "mcp_tool:figma:get_design_context",
                    "executor_type": "mcp_tool",
                    "name": "get_design_context",
                    "invocation_ref": "mcp__figma__get_design_context",
                    "constraints": {"mutating": False, "read_only": True},
                },
                {
                    "executor_id": "skill:codex:drawio",
                    "executor_type": "skill",
                    "name": "drawio",
                    "invocation_ref": "C:\\Users\\super\\.codex\\skills\\drawio",
                    "constraints": {"process_only": False, "read_only": True},
                },
            ],
            "routing_decision": {
                "chosen_plan": {
                    "plan_id": "tool-then-skill",
                    "steps": [
                        {
                            "step_type": "mcp_tool",
                            "executor_id": "mcp_tool:figma:get_design_context",
                            "purpose": "Fetch design context",
                            "required_inputs": [],
                            "expected_output": "Design context",
                            "reads_context_only": False,
                            "may_mutate": False,
                        },
                        {
                            "step_type": "skill",
                            "executor_id": "skill:codex:drawio",
                            "purpose": "Create the editable diagram",
                            "required_inputs": ["design context"],
                            "expected_output": "Editable diagram",
                            "reads_context_only": False,
                            "may_mutate": False,
                        },
                    ],
                }
            },
            "validation_result": {"is_valid": True, "errors": [], "warnings": []},
        }
        mock_executor_results = {
            "mcp_tool:figma:get_design_context": {
                "content": "Control Plane contains API Server, Scheduler, and etcd."
            }
        }

        result = execute_selected_plan(route_payload, mock_executor_results=mock_executor_results)

        self.assertEqual(result["step_results"][0]["status"], "completed")
        self.assertEqual(result["step_results"][1]["status"], "requires_host_execution")
        self.assertEqual(len(result["aggregated_context"]), 1)

    def test_stage_one_selector_prunes_irrelevant_executors_for_document_task(self):
        task_info = infer_task("写一份结构化文档，并帮我总结重点")
        executors = [
            {
                "executor_id": "skill:codex:doc",
                "executor_type": "skill",
                "name": "doc",
                "source": "local-skill",
                "tool_family": "codex",
                "capabilities": ["document", "review"],
                "keywords": ["document", "docx", "report"],
                "description": "Document writer",
                "constraints": {"process_only": False},
            },
            {
                "executor_id": "skill:codex:drawio",
                "executor_type": "skill",
                "name": "drawio",
                "source": "local-skill",
                "tool_family": "codex",
                "capabilities": ["diagram"],
                "keywords": ["diagram", "drawio"],
                "description": "Diagram tool",
                "constraints": {"process_only": False},
            },
            {
                "executor_id": "skill:codex:brainstorming",
                "executor_type": "skill",
                "name": "brainstorming",
                "source": "local-skill",
                "tool_family": "codex",
                "capabilities": ["visual-design"],
                "keywords": ["brainstorm"],
                "description": "Process skill",
                "constraints": {"process_only": True},
            },
        ]
        config = {
            "reasoning": {
                "stage_one": {
                    "enabled": True,
                    "candidate_limit": 2,
                    "description_max_chars": 80,
                    "keywords_limit": 6,
                }
            }
        }

        selected, meta = prepare_reasoning_executors(task_info, executors, config)
        selected_ids = [item["executor_id"] for item in selected]

        self.assertIn("skill:codex:doc", selected_ids)
        self.assertNotIn("skill:codex:drawio", selected_ids)
        self.assertNotIn("skill:codex:brainstorming", selected_ids)
        self.assertEqual(meta["selected_count"], 1)
        self.assertEqual(meta["pruned_count"], 2)

    def test_reasoning_executor_summary_truncates_description_and_keywords(self):
        executor = {
            "executor_id": "skill:codex:doc",
            "executor_type": "skill",
            "name": "doc",
            "source": "local-skill",
            "tool_family": "codex",
            "capabilities": ["document", "review"],
            "keywords": ["document", "docx", "report", "memo", "writer", "structured", "formatting"],
            "description": "This is a very long description that should be truncated before it is sent to the model for route planning because only the compact summary matters.",
            "constraints": {"process_only": False, "mutating": False, "read_only": True},
            "invocation_ref": "C:\\Users\\super\\.codex\\skills\\doc",
        }
        summary = summarize_executor_for_reasoning(
            executor,
            {
                "description_max_chars": 60,
                "keywords_limit": 4,
                "capabilities_limit": 4,
            },
        )

        self.assertLessEqual(len(summary["description"]), 61)
        self.assertEqual(len(summary["keywords"]), 4)
        self.assertNotIn("invocation_ref", summary)

    def test_stage_one_selector_preserves_support_diversity_for_teaching_diagram(self):
        task_info = infer_task("画一个中文 Kubernetes 总览图，要讲清楚关系，适合培训")
        executors = [
            {
                "executor_id": "skill:codex:drawio",
                "executor_type": "skill",
                "name": "drawio",
                "source": "local-skill",
                "tool_family": "codex",
                "capabilities": ["diagram"],
                "deliverable_capabilities": ["diagram"],
                "support_capabilities": [],
                "keywords": ["diagram", "drawio", "architecture"],
                "description": "Diagram tool",
                "constraints": {"process_only": False},
            },
            {
                "executor_id": "skill:codex:canvas-design",
                "executor_type": "skill",
                "name": "canvas-design",
                "source": "local-skill",
                "tool_family": "codex",
                "capabilities": ["information-design", "visual-design"],
                "deliverable_capabilities": [],
                "support_capabilities": ["information-design", "visual-design"],
                "keywords": ["storytelling", "structure", "clarity"],
                "description": "Improve information design",
                "constraints": {"process_only": False},
            },
            {
                "executor_id": "mcp_resource:figma:k8s-refs",
                "executor_type": "mcp_resource",
                "name": "k8s-refs",
                "source": "mcp-session",
                "tool_family": "figma",
                "capabilities": ["diagram", "research"],
                "deliverable_capabilities": [],
                "support_capabilities": ["research"],
                "keywords": ["kubernetes", "diagram", "reference"],
                "description": "Reference material",
                "constraints": {"context_only": True, "read_only": True},
            },
            {
                "executor_id": "skill:codex:spreadsheet",
                "executor_type": "skill",
                "name": "spreadsheet",
                "source": "local-skill",
                "tool_family": "codex",
                "capabilities": ["spreadsheet"],
                "deliverable_capabilities": ["spreadsheet"],
                "support_capabilities": [],
                "keywords": ["excel", "table"],
                "description": "Spreadsheet tool",
                "constraints": {"process_only": False},
            },
        ]
        config = {
            "reasoning": {
                "stage_one": {
                    "enabled": True,
                    "candidate_limit": 3,
                    "keep_all_under": 2,
                    "description_max_chars": 80,
                    "keywords_limit": 6,
                    "artifact_skill_limit": 2,
                    "support_skill_limit": 1,
                    "mcp_limit": 1,
                }
            }
        }

        selected, meta = prepare_reasoning_executors(task_info, executors, config)
        selected_ids = {item["executor_id"] for item in selected}

        self.assertIn("skill:codex:drawio", selected_ids)
        self.assertIn("skill:codex:canvas-design", selected_ids)
        self.assertNotIn("skill:codex:spreadsheet", selected_ids)
        self.assertEqual(meta["selected_count"], 3)
        self.assertGreaterEqual(meta["counts_by_type"]["skill"], 2)

    def test_stage_one_selector_allows_small_overflow_to_preserve_cross_type_candidates(self):
        task_info = infer_task("做一个中文 Kubernetes 培训总览图，要讲清楚关系")
        executors = [
            {
                "executor_id": "skill:codex:drawio",
                "executor_type": "skill",
                "name": "drawio",
                "source": "local-skill",
                "tool_family": "codex",
                "capabilities": ["diagram"],
                "deliverable_capabilities": ["diagram"],
                "support_capabilities": [],
                "keywords": ["diagram", "drawio", "overview"],
                "description": "Diagram authoring skill",
                "constraints": {"process_only": False},
            },
            {
                "executor_id": "skill:codex:canvas-design",
                "executor_type": "skill",
                "name": "canvas-design",
                "source": "local-skill",
                "tool_family": "codex",
                "capabilities": ["information-design", "visual-design"],
                "deliverable_capabilities": [],
                "support_capabilities": ["information-design", "visual-design"],
                "keywords": ["storytelling", "clarity", "training"],
                "description": "Information design support",
                "constraints": {"process_only": False},
            },
            {
                "executor_id": "mcp_resource:figma:k8s-refs",
                "executor_type": "mcp_resource",
                "name": "k8s-refs",
                "source": "mcp-session",
                "tool_family": "figma",
                "capabilities": ["research", "diagram"],
                "deliverable_capabilities": [],
                "support_capabilities": ["research"],
                "keywords": ["kubernetes", "reference", "training"],
                "description": "Kubernetes reference context",
                "constraints": {"context_only": True, "read_only": True},
            },
        ]
        config = {
            "reasoning": {
                "stage_one": {
                    "enabled": True,
                    "candidate_limit": 2,
                    "keep_all_under": 1,
                    "artifact_skill_limit": 1,
                    "support_skill_limit": 1,
                    "mcp_limit": 1,
                    "diversity_overflow_limit": 2,
                }
            }
        }

        selected, meta = prepare_reasoning_executors(task_info, executors, config)
        selected_ids = {item["executor_id"] for item in selected}
        selected_details = {item["executor_id"]: item for item in meta["selected_details"]}

        self.assertIn("skill:codex:drawio", selected_ids)
        self.assertIn("skill:codex:canvas-design", selected_ids)
        self.assertIn("mcp_resource:figma:k8s-refs", selected_ids)
        self.assertGreater(meta["selected_count"], config["reasoning"]["stage_one"]["candidate_limit"])
        self.assertEqual(meta["overflow_count"], 1)
        self.assertEqual(selected_details["skill:codex:drawio"]["selected_because"], "must-keep")
        self.assertEqual(selected_details["skill:codex:canvas-design"]["selected_because"], "support-slot")
        self.assertEqual(selected_details["mcp_resource:figma:k8s-refs"]["selected_because"], "mcp-slot")
        self.assertTrue(meta["pruned_details"] == [])

    def test_discover_skill_roots_finds_parallel_codex_collections(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tool_home = Path(temp_dir) / ".codex"
            (tool_home / "skills").mkdir(parents=True)
            (tool_home / "superpowers" / "skills").mkdir(parents=True)

            roots = discover_skill_roots(explicit_homes=[str(tool_home)])
            root_paths = {Path(item["path"]) for item in roots}

            self.assertIn(tool_home / "skills", root_paths)
            self.assertIn(tool_home / "superpowers" / "skills", root_paths)

    def test_kiro_manifest_provider_discovers_mcp_servers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            kiro_home = Path(temp_dir) / ".kiro"
            (kiro_home / "settings").mkdir(parents=True)
            (kiro_home / "settings" / "mcp.json").write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "office-word": {
                                "command": "uvx",
                                "args": ["mcp-server-office"],
                                "disabled": False,
                                "autoApprove": ["read_docx"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            executors, warnings = kiro_mcp_manifest_provider(kiro_home)

            self.assertEqual(warnings, [])
            self.assertEqual(len(executors), 1)
            self.assertEqual(executors[0]["executor_type"], "mcp_tool")
            self.assertEqual(executors[0]["name"], "office-word")

    def test_session_mcp_snapshot_builds_tool_and_resource_executors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            tools_path = temp_path / "tools.json"
            resources_path = temp_path / "resources.json"
            tools_path.write_text(
                json.dumps(
                    [
                        {
                            "server": "figma",
                            "name": "get_design_context",
                            "description": "Fetch design context",
                            "capabilities": ["diagram", "research"],
                        }
                    ]
                ),
                encoding="utf-8",
            )
            resources_path.write_text(
                json.dumps(
                    [
                        {
                            "server": "figma",
                            "uri": "file://figma/docs/intro.md",
                            "name": "intro",
                            "description": "Figma MCP intro docs",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            executors, sources, warnings = discover_session_mcp_executors(
                session_tools_file=str(tools_path),
                session_resources_file=str(resources_path),
            )

            self.assertEqual(warnings, [])
            self.assertEqual(len(executors), 2)
            by_type = {item["executor_type"]: item for item in executors}
            self.assertIn("mcp_tool", by_type)
            self.assertIn("mcp_resource", by_type)
            self.assertTrue(by_type["mcp_resource"]["constraints"]["context_only"])
            self.assertEqual(len(sources), 2)

    def test_policy_validator_rejects_process_skill_in_bounded_artifact_route(self):
        task_info = infer_task("画一个中文 Kubernetes draw.io 总览图，要求讲清楚关系")
        executors = [
            {
                "executor_id": "skill:codex:drawio",
                "executor_type": "skill",
                "name": "drawio",
                "constraints": {"process_only": False, "context_only": False},
            },
            {
                "executor_id": "skill:codex:brainstorming",
                "executor_type": "skill",
                "name": "brainstorming",
                "constraints": {"process_only": True, "context_only": False},
            },
        ]
        decision = {
            "chosen_plan_id": "bad-plan",
            "candidate_plans": [
                {
                    "plan_id": "bad-plan",
                    "summary": "",
                    "steps": [
                        {
                            "step_type": "skill",
                            "executor_id": "skill:codex:drawio",
                            "reads_context_only": False,
                            "may_mutate": False,
                        },
                        {
                            "step_type": "skill",
                            "executor_id": "skill:codex:brainstorming",
                            "reads_context_only": False,
                            "may_mutate": False,
                        },
                    ],
                    "pros": [],
                    "cons": [],
                }
            ],
            "missing_required_capabilities": [],
        }

        result = validate_route(task_info, decision, executors, {"allow_mutating_mcp_tools": False})

        self.assertFalse(result["is_valid"])
        self.assertTrue(any("process-only" in message for message in result["errors"]))

    def test_policy_validator_rejects_mcp_resource_as_final_step(self):
        task_info = infer_task("读取一个 MCP 资源后生成总结文档")
        executors = [
            {
                "executor_id": "mcp_resource:figma:intro",
                "executor_type": "mcp_resource",
                "name": "intro",
                "constraints": {"context_only": True, "read_only": True},
            }
        ]
        decision = {
            "chosen_plan_id": "bad-resource-final",
            "candidate_plans": [
                {
                    "plan_id": "bad-resource-final",
                    "summary": "",
                    "steps": [
                        {
                            "step_type": "mcp_resource",
                            "executor_id": "mcp_resource:figma:intro",
                            "reads_context_only": True,
                            "may_mutate": False,
                        }
                    ],
                    "pros": [],
                    "cons": [],
                }
            ],
            "missing_required_capabilities": [],
        }

        result = validate_route(task_info, decision, executors, {})

        self.assertFalse(result["is_valid"])
        self.assertTrue(any("may not end with an mcp_resource" in message for message in result["errors"]))

    def test_policy_validator_rejects_mutating_mcp_tool_when_policy_disallows_it(self):
        task_info = infer_task("调用 MCP tool 获取设计上下文然后生成图")
        executors = [
            {
                "executor_id": "mcp_tool:figma:get_design_context",
                "executor_type": "mcp_tool",
                "name": "get_design_context",
                "constraints": {"mutating": True},
            }
        ]
        decision = {
            "chosen_plan_id": "bad-mutating-tool",
            "candidate_plans": [
                {
                    "plan_id": "bad-mutating-tool",
                    "summary": "",
                    "steps": [
                        {
                            "step_type": "mcp_tool",
                            "executor_id": "mcp_tool:figma:get_design_context",
                            "reads_context_only": False,
                            "may_mutate": True,
                        }
                    ],
                    "pros": [],
                    "cons": [],
                }
            ],
            "missing_required_capabilities": [],
        }

        result = validate_route(task_info, decision, executors, {"allow_mutating_mcp_tools": False})

        self.assertFalse(result["is_valid"])
        self.assertTrue(any("Mutating MCP tool" in message for message in result["errors"]))

    def test_policy_validator_rejects_step_that_requires_future_context(self):
        task_info = infer_task("读取一个 MCP 资源后生成总结文档")
        executors = [
            {
                "executor_id": "skill:codex:doc",
                "executor_type": "skill",
                "name": "doc",
                "constraints": {"process_only": False, "context_only": False},
            },
            {
                "executor_id": "mcp_resource:figma:intro",
                "executor_type": "mcp_resource",
                "name": "intro",
                "constraints": {"context_only": True, "read_only": True},
            },
        ]
        decision = {
            "chosen_plan_id": "bad-order",
            "candidate_plans": [
                {
                    "plan_id": "bad-order",
                    "summary": "",
                    "steps": [
                        {
                            "step_type": "skill",
                            "executor_id": "skill:codex:doc",
                            "required_inputs": ["reference content"],
                            "expected_output": "Editable summary document",
                            "reads_context_only": False,
                            "may_mutate": False,
                        },
                        {
                            "step_type": "mcp_resource",
                            "executor_id": "mcp_resource:figma:intro",
                            "required_inputs": [],
                            "expected_output": "Reference content",
                            "reads_context_only": True,
                            "may_mutate": False,
                        },
                    ],
                    "pros": [],
                    "cons": [],
                }
            ],
            "missing_required_capabilities": [],
        }

        result = validate_route(task_info, decision, executors, {})

        self.assertFalse(result["is_valid"])
        self.assertTrue(any("before it is produced" in message for message in result["errors"]))

    def test_plan_route_outputs_v2_shape_with_mock_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            tool_home = temp_path / ".agents"
            skill_dir = tool_home / "skills" / "doc-writer"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: doc-writer\ndescription: Use when writing structured documents.\n---\n",
                encoding="utf-8",
            )
            mock_response = temp_path / "mock-response.json"
            mock_response.write_text(
                json.dumps(
                    {
                        "task_understanding": "Write a document from the available skill.",
                        "task_profile": {
                            "deliverable": "document",
                            "actions": ["summarize"],
                            "quality_goals": ["accuracy"],
                            "bounded_request": False,
                            "process_intents": [],
                            "user_language": "zh",
                        },
                        "needed_capabilities": ["document"],
                        "required_capabilities": ["document"],
                        "optional_support_capabilities": ["review"],
                        "role_findings": [
                            {
                                "role_id": "delivery-role",
                                "conclusion": "The installed document skill can produce the requested document directly.",
                                "concerns": [],
                                "suggested_capabilities": ["document"],
                            },
                            {
                                "role_id": "quality-critic-role",
                                "conclusion": "Accuracy expectations should remain visible in the route output.",
                                "concerns": ["The route should not look purely mechanical."],
                                "suggested_capabilities": ["review"],
                            },
                            {
                                "role_id": "design-editor-role",
                                "conclusion": "The output should stay editable and readable.",
                                "concerns": [],
                                "suggested_capabilities": ["information-design"],
                            },
                        ],
                        "completion_assessment": {
                            "quality_bar": "best-practical",
                            "baseline_satisfied": True,
                            "quality_risks": [],
                            "optimization_opportunities": ["Keep the route explanation user-visible."],
                            "reason": "A direct route is enough, but it should still show proactive quality thinking.",
                        },
                        "quality_gate": {
                            "status": "pass",
                            "reason": "The route is acceptable for this document task.",
                            "blocking_issues": [],
                        },
                        "second_pass_review": {
                            "verdict": "good-enough",
                            "reason": "The route is not merely functional for this bounded document task.",
                            "follow_up_actions": ["在交付前再检查一次结构清晰度与可编辑性说明"],
                        },
                        "candidate_plans": [
                            {
                                "plan_id": "direct-doc",
                                "summary": "Use the document skill directly.",
                                "steps": [
                                    {
                                        "step_type": "skill",
                                        "executor_id": "skill:agents:doc-writer",
                                        "purpose": "Write the requested document",
                                        "required_inputs": [],
                                        "expected_output": "Editable document draft",
                                        "reads_context_only": False,
                                        "may_mutate": False,
                                    }
                                ],
                                "pros": ["Simple"],
                                "cons": [],
                            }
                        ],
                        "chosen_plan_id": "direct-doc",
                        "chosen_plan_reason": "The skill already covers the document task.",
                        "why_not_others": [],
                        "missing_required_capabilities": [],
                        "missing_optional_capabilities": [],
                        "reflection_trace": [
                            {
                                "focus": "task-profile",
                                "decision": "Treat the request as document summarization rather than freeform drafting.",
                                "reason": "The wording suggests producing a concise structured result."
                            },
                            {
                                "focus": "executor",
                                "subject": "skill:agents:doc-writer",
                                "decision": "Use the document skill as the direct artifact executor.",
                                "reason": "It already covers structured editable document output."
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            script_path = SCRIPTS_DIR / "plan_route.py"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    "--task",
                    "写一份结构化文档",
                    "--tool-home",
                    str(tool_home),
                    "--mock-model-response",
                    str(mock_response),
                    "--no-remote",
                    "--include-reasoning-input",
                    "--base-dir",
                    str(Path(__file__).resolve().parents[1]),
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            payload = json.loads(completed.stdout)

            self.assertIn("discovered_executors", payload)
            self.assertIn("routing_decision", payload)
            self.assertIn("validation_result", payload)
            self.assertIn("final_plan", payload)
            self.assertIn("orchestration_state", payload)
            self.assertIn("routing_usage_policy", payload)
            self.assertIn("host_auto_routing_contract", payload)
            self.assertIn("host_route_signal", payload)
            self.assertIn("host_turn_signal", payload)
            self.assertIn("routing_status_card", payload)
            self.assertIn("reasoning_input", payload)
            self.assertTrue(payload["validation_result"]["is_valid"])
            self.assertEqual(payload["routing_decision"]["chosen_plan"]["plan_id"], "direct-doc")
            self.assertEqual(payload["final_plan"]["chosen_plan_id"], "direct-doc")
            self.assertEqual(payload["final_plan"]["ordered_steps"][0]["executor_id"], "skill:agents:doc-writer")
            self.assertEqual(payload["final_plan"]["ordered_steps"][0]["step_id"], "direct-doc-step-1")
            self.assertTrue(payload["final_plan"]["validation"]["is_valid"])
            self.assertFalse(payload["final_plan"]["execution_ready"])
            self.assertTrue(payload["final_plan"]["ready_after_user_confirmation"])
            self.assertTrue(payload["final_plan"]["presentation_contract"]["must_show_to_user_before_execution"])
            self.assertTrue(payload["final_plan"]["execution_gate"]["requires_user_confirmation"])
            self.assertEqual(payload["final_plan"]["execution_gate"]["next_action"], "show_plan_and_stop")
            self.assertNotIn("The skill already covers the document task.", payload["user_summary"])
            self.assertIn("当前只展示编排结果", payload["user_summary"])
            self.assertIn("第二轮高标准复查", payload["user_summary"])
            self.assertEqual(payload["task_profile"]["actions"], ["summarize"])
            self.assertEqual(payload["task_profile"]["quality_goals"], ["accuracy"])
            self.assertFalse(payload["task_profile"]["bounded_request"])
            self.assertEqual(payload["task_profile"]["task_stage"], "delivery")
            self.assertIn("documentation", payload["task_profile"]["needed_capability_groups"])
            self.assertEqual(payload["task_profile"]["optional_support_capabilities"], ["review"])
            self.assertNotIn("reflection_trace", payload["routing_decision"])
            self.assertEqual(payload["routing_decision"]["quality_gate"]["status"], "pass")
            self.assertEqual(payload["routing_decision"]["second_pass_review"]["verdict"], "good-enough")
            self.assertTrue(payload["final_plan"]["proactive_improvement_loop"]["second_pass_follow_up_actions"])
            self.assertIn("run_router_now_when", payload["routing_usage_policy"])
            self.assertIn("do_not_reroute_when", payload["routing_usage_policy"])
            self.assertIn("stage-rerouting", payload["routing_usage_policy"]["reroute_labels"])
            self.assertEqual(payload["routing_usage_policy"]["session_activation"]["activation_mode"], "explicit-first-then-sticky")
            self.assertTrue(payload["routing_usage_policy"]["auto_reroute_policy"]["host_should_reroute_automatically_when_triggered"])
            self.assertEqual(payload["host_auto_routing_contract"]["default_action"], "continue-current-route")
            self.assertEqual(payload["host_auto_routing_contract"]["triggered_action"], "reroute-now")
            self.assertEqual(len(payload["host_auto_routing_contract"]["decision_rules"]), 3)
            self.assertEqual(payload["host_route_signal"]["router_state"], "armed")
            self.assertEqual(payload["host_route_signal"]["host_next_route_decision"], "continue-current-route")
            self.assertFalse(payload["host_route_signal"]["host_reroute_trigger_matched"])
            self.assertEqual(payload["host_turn_signal"]["next_host_action"], "show_plan")
            self.assertTrue(payload["host_turn_signal"]["requires_user_visible_message"])
            self.assertTrue(payload["host_turn_signal"]["must_end_turn"])
            self.assertEqual(payload["host_turn_signal"]["after_user_confirmation_action"], "execute_step")
            self.assertEqual(payload["routing_status_card"]["phase"], "plan-ready")
            self.assertEqual(payload["routing_status_card"]["user_action"], "confirm-route")
            self.assertEqual(payload["routing_status_card"]["next_step"], "execute-step")
            self.assertTrue(payload["routing_status_card"]["waiting_for_user"])
            self.assertIn("task_stage_seed", payload["reasoning_input"])
            self.assertIn("needed_capability_group_hints", payload["reasoning_input"])
            self.assertLess(len(payload["reasoning_input"]["available_executors"]), len(payload["discovered_executors"]))
            self.assertNotIn("invocation_ref", payload["reasoning_input"]["available_executors"][0])
            self.assertEqual(payload["orchestration_state"]["route_phase"], "planned")
            self.assertEqual(payload["orchestration_state"]["next_host_action"], "show_plan")
            self.assertEqual(payload["orchestration_state"]["after_show_action"], "execute_step")
            self.assertEqual(payload["orchestration_state"]["chosen_plan"]["steps"][0]["step_id"], "direct-doc-step-1")
            self.assertEqual(payload["orchestration_state"]["acceptance_gate"]["status"], "pending_execution")

    def test_plan_route_can_include_reflection_trace_for_debugging(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            tool_home = temp_path / ".agents"
            skill_dir = tool_home / "skills" / "doc-writer"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: doc-writer\ndescription: Use when writing structured documents.\n---\n",
                encoding="utf-8",
            )
            mock_response = temp_path / "mock-response.json"
            mock_response.write_text(
                json.dumps(
                    {
                        "task_understanding": "Write a document from the available skill.",
                        "task_profile": {
                            "deliverable": "document",
                            "actions": ["create"],
                            "quality_goals": [],
                            "bounded_request": True,
                            "process_intents": [],
                            "user_language": "zh",
                        },
                        "needed_capabilities": ["document"],
                        "required_capabilities": ["document"],
                        "optional_support_capabilities": [],
                        "role_findings": [
                            {
                                "role_id": "delivery-role",
                                "conclusion": "The document skill is sufficient for the bounded request.",
                                "concerns": [],
                                "suggested_capabilities": ["document"],
                            },
                            {
                                "role_id": "quality-critic-role",
                                "conclusion": "There is no major quality gap beyond showing the route clearly.",
                                "concerns": [],
                                "suggested_capabilities": [],
                            },
                            {
                                "role_id": "design-editor-role",
                                "conclusion": "The output should remain readable and editable.",
                                "concerns": [],
                                "suggested_capabilities": ["information-design"],
                            },
                        ],
                        "completion_assessment": {
                            "quality_bar": "strong",
                            "baseline_satisfied": True,
                            "quality_risks": [],
                            "optimization_opportunities": ["Keep the route concise and visible before execution."],
                            "reason": "The bounded request can stay direct after role-split reflection.",
                        },
                        "quality_gate": {
                            "status": "pass",
                            "reason": "The route is acceptable after explicit reflection.",
                            "blocking_issues": [],
                        },
                        "second_pass_review": {
                            "verdict": "good-enough",
                            "reason": "A direct route is fine here and does not need extra orchestration.",
                            "follow_up_actions": ["在验收前再看一遍是否还有低成本可读性优化"],
                        },
                        "candidate_plans": [
                            {
                                "plan_id": "direct-doc",
                                "summary": "Use the document skill directly.",
                                "steps": [
                                    {
                                        "step_type": "skill",
                                        "executor_id": "skill:agents:doc-writer",
                                        "purpose": "Write the requested document",
                                        "required_inputs": [],
                                        "expected_output": "Editable document draft",
                                        "reads_context_only": False,
                                        "may_mutate": False,
                                    }
                                ],
                                "pros": ["Simple"],
                                "cons": [],
                            }
                        ],
                        "chosen_plan_id": "direct-doc",
                        "chosen_plan_reason": "The skill already covers the document task.",
                        "why_not_others": [],
                        "missing_required_capabilities": [],
                        "missing_optional_capabilities": [],
                        "reflection_trace": [
                            {
                                "focus": "executor",
                                "subject": "skill:agents:doc-writer",
                                "decision": "Use the installed document skill.",
                                "reason": "It is sufficient for the bounded request."
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            script_path = SCRIPTS_DIR / "plan_route.py"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    "--task",
                    "写一份结构化文档",
                    "--tool-home",
                    str(tool_home),
                    "--mock-model-response",
                    str(mock_response),
                    "--no-remote",
                    "--include-reflection-trace",
                    "--base-dir",
                    str(Path(__file__).resolve().parents[1]),
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            payload = json.loads(completed.stdout)

            self.assertIn("reflection_trace", payload["routing_decision"])
            self.assertEqual(payload["routing_decision"]["reflection_trace"][0]["focus"], "executor")
            self.assertIn("final_plan", payload)
            self.assertNotIn("reflection_trace", payload["final_plan"])
            self.assertTrue(payload["final_plan"]["presentation_contract"]["must_show_to_user_before_execution"])
            self.assertFalse(payload["final_plan"]["execution_ready"])

    def test_plan_route_surfaces_install_approval_flow_for_missing_required_capabilities(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            mock_response = temp_path / "mock-response.json"
            mock_response.write_text(
                json.dumps(
                    {
                        "task_understanding": "The task needs research-oriented product discovery support before execution.",
                        "task_profile": {
                            "deliverable": None,
                            "actions": ["analyze"],
                            "quality_goals": ["clarity"],
                            "bounded_request": False,
                            "process_intents": ["planning"],
                            "user_language": "zh",
                        },
                        "needed_capabilities": ["research", "information-design"],
                        "required_capabilities": ["research"],
                        "optional_support_capabilities": ["information-design"],
                        "role_findings": [
                            {
                                "role_id": "delivery-role",
                                "conclusion": "No installed executor can reliably cover the required research step.",
                                "concerns": ["Pretending an executor exists would break execution."],
                                "suggested_capabilities": ["research"],
                            },
                            {
                                "role_id": "quality-critic-role",
                                "conclusion": "Research should stay a required capability before any serious planning output.",
                                "concerns": ["Skipping research would lower product-definition quality."],
                                "suggested_capabilities": ["research"],
                            },
                            {
                                "role_id": "design-editor-role",
                                "conclusion": "Information design remains an optional upgrade after the research gap is fixed.",
                                "concerns": ["Clarity support is useful but should not block the install-first route."],
                                "suggested_capabilities": ["information-design"],
                            },
                        ],
                        "completion_assessment": {
                            "quality_bar": "best-practical",
                            "baseline_satisfied": False,
                            "quality_risks": ["The route cannot start execution until research support is installed."],
                            "optimization_opportunities": ["Install a research-capable executor first, then reroute."],
                            "reason": "The best practical route is to install the missing required capability before execution.",
                        },
                        "quality_gate": {
                            "status": "pass",
                            "reason": "Install-first is the only quality-safe route.",
                            "blocking_issues": [],
                        },
                        "second_pass_review": {
                            "verdict": "good-enough",
                            "reason": "The route already rejects pretending that a local executor exists.",
                            "follow_up_actions": ["安装完成后重新路由，不复用旧路线"],
                        },
                        "missing_executors": [
                            {
                                "executor_type": "mcp_tool",
                                "name": "product-research",
                                "provider_family": "codex",
                                "reason": "Would improve research and discovery quality."
                            }
                        ],
                        "candidate_plans": [
                            {
                                "plan_id": "clarify-and-install-first",
                                "summary": "No suitable local executor is available yet; recommend installing one before execution.",
                                "steps": [],
                                "pros": ["Avoids pretending that a local route already exists."],
                                "cons": ["Needs user approval before installation."],
                            }
                        ],
                        "chosen_plan_id": "clarify-and-install-first",
                        "chosen_plan_reason": "A required capability is missing locally.",
                        "why_not_others": ["No local skill or MCP executor currently covers the required capability."],
                        "missing_required_capabilities": ["research"],
                        "missing_optional_capabilities": ["information-design"],
                        "reflection_trace": [
                            {
                                "focus": "capability",
                                "subject": "research",
                                "decision": "Treat research as required before execution.",
                                "reason": "The request is still in early product definition and needs discovery support."
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            script_path = SCRIPTS_DIR / "plan_route.py"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    "--task",
                    "我打算开发一款手机app，用于打卡健身的",
                    "--mock-model-response",
                    str(mock_response),
                    "--no-remote",
                    "--base-dir",
                    str(Path(__file__).resolve().parents[1]),
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            payload = json.loads(completed.stdout)

            self.assertFalse(payload["validation_result"]["is_valid"])
            self.assertFalse(payload["final_plan"]["execution_ready"])
            self.assertFalse(payload["final_plan"]["route_valid"])
            self.assertTrue(payload["final_plan"]["installation_gate"]["requires_user_approval"])
            self.assertEqual(payload["final_plan"]["installation_gate"]["approval_scope"], "required")
            self.assertEqual(payload["final_plan"]["execution_gate"]["next_action"], "show_plan_and_ask_install_approval")
            self.assertEqual(payload["final_plan"]["installation_gate"]["next_action_if_approved"], "install_and_rerun_route")
            self.assertEqual(payload["final_plan"]["installation_gate"]["approved_executor"]["executor_type"], "skill")
            self.assertEqual(payload["final_plan"]["installation_gate"]["approved_executor"]["name"], "skill-installer")
            self.assertEqual(payload["final_plan"]["installation_gate"]["approved_executor"]["host_action"], "invoke_skill_installer")
            self.assertTrue(payload["recommended_install_required"])
            self.assertTrue(payload["recommended_install_mcp"])
            self.assertEqual(payload["recommended_install_mcp"][0]["provider_family"], "codex")
            self.assertTrue(payload["recommended_install_mcp"][0]["supports_auto_install"])
            self.assertEqual(payload["recommended_install_required"][0]["name"], "content-research-writer")
            self.assertEqual(payload["routing_status_card"]["phase"], "install-approval")
            self.assertEqual(payload["routing_status_card"]["user_action"], "approve-install")
            self.assertEqual(payload["routing_status_card"]["next_step"], "install-and-reroute")
            self.assertTrue(payload["routing_status_card"]["waiting_for_user"])
            self.assertIn("询问用户是否安装", payload["user_summary"])
            self.assertIn("skill-installer", payload["final_plan"]["host_handoff_instructions"])
            self.assertIn("安装后", payload["final_plan"]["host_handoff_instructions"])
            self.assertEqual(payload["orchestration_state"]["after_show_action"], "ask_install_approval")
            self.assertEqual(payload["orchestration_state"]["installation_gate"]["recommended_targets"][0]["name"], "content-research-writer")

    def test_build_installation_plan_supports_skill_and_mcp_recommendations(self):
        skill_plan = build_installation_plan(
            {
                "executor_type": "skill",
                "name": "content-research-writer",
                "provider_family": "openai-curated",
                "install_url": "https://github.com/openai/skills/tree/main/skills/.curated/content-research-writer",
            }
        )
        mcp_plan = build_installation_plan(
            {
                "executor_type": "mcp_tool",
                "name": "office-word",
                "provider_family": "kiro",
            }
        )

        self.assertEqual(skill_plan["approved_executor"]["name"], "skill-installer")
        self.assertEqual(skill_plan["host_action"], "invoke_skill_installer")
        self.assertEqual(mcp_plan["host_action"], "invoke_mcp_installer")
        self.assertEqual(mcp_plan["approved_executor"]["name"], "kiro-mcp-installer")

    def test_mcp_install_provider_marks_supported_hosts_only(self):
        codex_adapter = build_mcp_install_adapter({"name": "figma", "provider_family": "codex"})
        cursor_adapter = build_mcp_install_adapter({"name": "figma", "provider_family": "cursor"})

        self.assertTrue(codex_adapter["supports_auto_install"])
        self.assertEqual(codex_adapter["install_mode"], "provider-adapter")
        self.assertFalse(cursor_adapter["supports_auto_install"])
        self.assertEqual(cursor_adapter["availability"], "not_supported_yet")

    def test_step_acceptance_and_orchestration_runner_form_single_step_loop(self):
        route_payload = {
            "task": "写一份结构化文档",
            "mode": "explicit",
            "final_plan": {
                "installation_gate": {"requires_user_approval": False},
            },
            "routing_decision": {
                "minimal_high_quality_combo": [
                    {"executor_id": "skill:agents:doc-writer", "role": "primary", "why": "Direct output"}
                ],
                "step_acceptance_blueprint": [
                    {
                        "step_id": "direct-doc-step-1",
                        "summary_template": "Review the generated editable document draft.",
                        "acceptance_criteria": ["The draft is editable", "The draft matches the request"],
                    }
                ],
                "chosen_plan": {
                    "plan_id": "direct-doc",
                    "steps": [
                        {
                            "step_id": "direct-doc-step-1",
                            "step_type": "skill",
                            "executor_id": "skill:agents:doc-writer",
                            "purpose": "Write the requested document",
                            "expected_output": "Editable document draft",
                            "required_inputs": [],
                            "reads_context_only": False,
                            "may_mutate": False,
                        }
                    ],
                },
            },
            "discovered_executors": [
                {
                    "executor_id": "skill:agents:doc-writer",
                    "executor_type": "skill",
                    "name": "doc-writer",
                    "invocation_ref": "C:\\temp\\doc-writer",
                    "constraints": {"process_only": False, "read_only": True},
                }
            ],
        }

        state = build_initial_orchestration_state(route_payload)
        self.assertEqual(state["next_host_action"], "show_plan")

        state = advance_orchestration_state(state, {"type": "plan_shown"})
        self.assertEqual(state["next_host_action"], "execute_step")
        self.assertEqual(state["route_phase"], "awaiting_step_execution")

        receipt = build_step_receipt(
            step=route_payload["routing_decision"]["chosen_plan"]["steps"][0],
            executor=route_payload["discovered_executors"][0],
            payload={"content": "Draft content"},
            blueprint=route_payload["routing_decision"]["step_acceptance_blueprint"][0],
        )
        acceptance_gate = build_acceptance_gate(receipt)
        self.assertEqual(acceptance_gate["status"], "awaiting_user_confirmation")

        state = advance_orchestration_state(state, {"type": "step_executed", "step_receipt": receipt})
        self.assertEqual(state["next_host_action"], "ask_step_acceptance")
        self.assertEqual(state["route_phase"], "awaiting_step_acceptance")

        state = advance_orchestration_state(state, {"type": "step_accepted", "accepted": True})
        self.assertEqual(state["next_host_action"], "finish_route")
        self.assertEqual(state["route_phase"], "completed")

    def test_plan_route_in_host_mode_emits_reasoning_packet_without_network_call(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            tool_home = temp_path / ".agents"
            skill_dir = tool_home / "skills" / "doc-writer"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: doc-writer\ndescription: Use when writing structured documents.\n---\n",
                encoding="utf-8",
            )

            script_path = SCRIPTS_DIR / "plan_route.py"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    "--task",
                    "写一份结构化文档",
                    "--tool-home",
                    str(tool_home),
                    "--no-remote",
                    "--base-dir",
                    str(Path(__file__).resolve().parents[1]),
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            payload = json.loads(completed.stdout)

            self.assertEqual(payload["routing_status"], "requires_host_reasoning")
            self.assertIn("host_reasoning_request", payload)
            self.assertIn("host_reasoning_contract", payload)
            self.assertIn("routing_usage_policy", payload)
            self.assertIn("host_auto_routing_contract", payload)
            self.assertIn("host_route_signal", payload)
            self.assertIn("host_turn_signal", payload)
            self.assertIn("routing_status_card", payload)
            self.assertEqual(payload["next_host_action"], "reflect_and_finalize_route")
            self.assertIn("host_handoff_instructions", payload)
            self.assertIn("--host-decision-file", payload["host_handoff_instructions"]["finalize_route"])
            self.assertIn("reflection_roles", payload["host_reasoning_request"])
            self.assertIn("completion_directive", payload["host_reasoning_request"])
            self.assertIn("second_pass_directive", payload["host_reasoning_request"])
            self.assertIn("quality_gate_policy", payload["host_reasoning_request"])
            self.assertEqual(
                [item["role_id"] for item in payload["host_reasoning_request"]["reflection_roles"]],
                ["delivery-role", "quality-critic-role", "design-editor-role"],
            )
            self.assertIn("role_findings", payload["host_reasoning_contract"]["required_keys"])
            self.assertIn("completion_assessment", payload["host_reasoning_contract"]["required_keys"])
            self.assertIn("quality_gate", payload["host_reasoning_contract"]["required_keys"])
            self.assertIn("second_pass_review", payload["host_reasoning_contract"]["required_keys"])
            self.assertIn("第一次收到明确任务", payload["routing_usage_policy"]["run_router_now_when"][0])
            self.assertIn("第一次明确说使用 skill-router 后", payload["routing_usage_policy"]["session_activation"]["host_instruction"])
            self.assertIn("继续当前路线", payload["host_auto_routing_contract"]["decision_rules"][2]["then"])
            self.assertEqual(payload["host_route_signal"]["router_state"], "armed")
            self.assertEqual(payload["host_route_signal"]["host_next_route_decision"], "reroute-now")
            self.assertTrue(payload["host_route_signal"]["host_reroute_trigger_matched"])
            self.assertEqual(payload["host_route_signal"]["matched_trigger_label"], "initial-routing")
            self.assertEqual(payload["host_turn_signal"]["next_host_action"], "reflect_and_finalize_route")
            self.assertFalse(payload["host_turn_signal"]["requires_user_visible_message"])
            self.assertFalse(payload["host_turn_signal"]["must_end_turn"])
            self.assertEqual(payload["routing_status_card"]["phase"], "reflective-routing")
            self.assertEqual(payload["routing_status_card"]["user_action"], "none")
            self.assertEqual(payload["routing_status_card"]["next_step"], "host-reflect")
            self.assertFalse(payload["routing_status_card"]["waiting_for_user"])
            self.assertEqual(payload["task_profile"]["task_stage"], "delivery")
            self.assertIn("documentation", payload["task_profile"]["needed_capability_groups"])
            self.assertEqual(payload["host_reasoning_request"]["task_stage_seed"], "delivery")
            self.assertIn("documentation", payload["host_reasoning_request"]["needed_capability_group_hints"])
            self.assertNotIn("final_plan", payload)

    def test_plan_route_can_finalize_from_host_decision_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            tool_home = temp_path / ".agents"
            skill_dir = tool_home / "skills" / "doc-writer"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: doc-writer\ndescription: Use when writing structured documents.\n---\n",
                encoding="utf-8",
            )
            host_decision = temp_path / "host-decision.json"
            host_decision.write_text(
                json.dumps(
                    {
                        "task_understanding": "Write a document from the available skill.",
                        "task_profile": {
                            "deliverable": "document",
                            "actions": ["summarize"],
                            "quality_goals": ["accuracy"],
                            "bounded_request": False,
                            "process_intents": [],
                            "user_language": "zh",
                        },
                        "needed_capabilities": ["document"],
                        "required_capabilities": ["document"],
                        "optional_support_capabilities": ["review"],
                        "role_findings": [
                            {
                                "role_id": "delivery-role",
                                "conclusion": "The document skill can directly produce the requested editable result.",
                                "concerns": ["The route still needs a visible review checkpoint before execution."],
                                "suggested_capabilities": ["document"],
                            },
                            {
                                "role_id": "quality-critic-role",
                                "conclusion": "The route is functionally sufficient, but it should still foreground accuracy expectations.",
                                "concerns": ["Quality expectations should stay visible to the user."],
                                "suggested_capabilities": ["review"],
                            },
                            {
                                "role_id": "design-editor-role",
                                "conclusion": "The output should stay editable and readable rather than merely complete.",
                                "concerns": ["The user should see that readability and editability were considered."],
                                "suggested_capabilities": ["information-design"],
                            },
                        ],
                        "completion_assessment": {
                            "quality_bar": "best-practical",
                            "baseline_satisfied": True,
                            "quality_risks": ["If the route is shown as purely functional, the user will not see the proactive quality thinking."],
                            "optimization_opportunities": ["Keep the route summary explicit about delivery, quality, and editing concerns."],
                            "reason": "This route is acceptable because it stays simple while still making the quality bar explicit.",
                        },
                        "quality_gate": {
                            "status": "pass",
                            "reason": "The route clears the quality gate.",
                            "blocking_issues": [],
                        },
                        "second_pass_review": {
                            "verdict": "good-enough",
                            "reason": "The route is simple, but still explicitly carries quality intent.",
                            "follow_up_actions": ["在交付前提醒宿主再看一次准确性与可编辑性"],
                        },
                        "minimal_high_quality_combo": [
                            {
                                "executor_id": "skill:agents:doc-writer",
                                "role": "primary",
                                "why": "Directly produces the requested editable document."
                            }
                        ],
                        "missing_executors": [],
                        "step_acceptance_blueprint": [
                            {
                                "step_id": "direct-doc-step-1",
                                "summary_template": "Review the generated editable document draft.",
                                "acceptance_criteria": ["The draft is editable", "The draft matches the request"],
                                "improvement_checks": ["The structure reads clearly", "Any final polish is low-cost and worthwhile"],
                            }
                        ],
                        "candidate_plans": [
                            {
                                "plan_id": "direct-doc",
                                "summary": "Use the document skill directly.",
                                "steps": [
                                    {
                                        "step_id": "direct-doc-step-1",
                                        "step_type": "skill",
                                        "executor_id": "skill:agents:doc-writer",
                                        "purpose": "Write the requested document",
                                        "required_inputs": [],
                                        "expected_output": "Editable document draft",
                                        "reads_context_only": False,
                                        "may_mutate": False,
                                    }
                                ],
                                "pros": ["Simple"],
                                "cons": [],
                            }
                        ],
                        "chosen_plan_id": "direct-doc",
                        "chosen_plan_reason": "The skill already covers the document task.",
                        "why_not_others": [],
                        "missing_required_capabilities": [],
                        "missing_optional_capabilities": [],
                        "reflection_trace": [],
                    }
                ),
                encoding="utf-8",
            )

            script_path = SCRIPTS_DIR / "plan_route.py"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    "--task",
                    "写一份结构化文档",
                    "--tool-home",
                    str(tool_home),
                    "--host-decision-file",
                    str(host_decision),
                    "--no-remote",
                    "--base-dir",
                    str(Path(__file__).resolve().parents[1]),
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            payload = json.loads(completed.stdout)

            self.assertEqual(payload["routing_status"], "completed")
            self.assertIn("final_plan", payload)
            self.assertEqual(payload["final_plan"]["chosen_plan_id"], "direct-doc")
            self.assertEqual(payload["routing_decision"]["completion_assessment"]["quality_bar"], "best-practical")
            self.assertEqual(len(payload["routing_decision"]["role_findings"]), 3)
            self.assertEqual(
                [item["role_id"] for item in payload["routing_decision"]["role_findings"]],
                ["delivery-role", "quality-critic-role", "design-editor-role"],
            )
            self.assertEqual(payload["routing_decision"]["quality_gate"]["status"], "pass")
            self.assertEqual(payload["routing_decision"]["second_pass_review"]["verdict"], "good-enough")
            self.assertIn("quality_reflection", payload["final_plan"])
            self.assertEqual(payload["final_plan"]["quality_reflection"]["quality_bar"], "best-practical")
            self.assertEqual(
                [item["role_id"] for item in payload["final_plan"]["quality_reflection"]["role_highlights"]],
                ["delivery-role", "quality-critic-role", "design-editor-role"],
            )
            self.assertTrue(payload["final_plan"]["proactive_improvement_loop"]["second_pass_follow_up_actions"])
            self.assertTrue(payload["final_plan"]["proactive_improvement_loop"]["step_level_improvement_checks"])
            self.assertIn("不是只按“能做”来选", payload["user_summary"])


if __name__ == "__main__":
    unittest.main()
