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
from policy_validator import validate_route
from router_lib import infer_task, prepare_reasoning_executors, summarize_executor_for_reasoning


class SkillRouterV2Tests(unittest.TestCase):
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
            self.assertIn("reasoning_input", payload)
            self.assertTrue(payload["validation_result"]["is_valid"])
            self.assertEqual(payload["routing_decision"]["chosen_plan"]["plan_id"], "direct-doc")
            self.assertNotIn("The skill already covers the document task.", payload["user_summary"])
            self.assertEqual(payload["task_profile"]["actions"], ["summarize"])
            self.assertEqual(payload["task_profile"]["quality_goals"], ["accuracy"])
            self.assertFalse(payload["task_profile"]["bounded_request"])
            self.assertEqual(payload["task_profile"]["optional_support_capabilities"], ["review"])
            self.assertNotIn("reflection_trace", payload["routing_decision"])
            self.assertLess(len(payload["reasoning_input"]["available_executors"]), len(payload["discovered_executors"]))
            self.assertNotIn("invocation_ref", payload["reasoning_input"]["available_executors"][0])

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


if __name__ == "__main__":
    unittest.main()
