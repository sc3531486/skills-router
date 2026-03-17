#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

from execution_runner import execute_selected_plan


def load_json(path_text):
    with open(Path(path_text).expanduser().resolve(), "r", encoding="utf-8") as handle:
        return json.load(handle)


def main():
    parser = argparse.ArgumentParser(description="Execute a validated chosen plan in a safe, host-aware way.")
    parser.add_argument("--route-file", required=True, help="JSON output file produced by plan_route.py")
    parser.add_argument("--resource-contents-file", help="Optional JSON map of MCP resource content by executor_id/name/ref")
    parser.add_argument("--mock-executor-results-file", help="Optional JSON map of mock executor outputs for testing")
    parser.add_argument("--continue-after-handoff", action="store_true", help="Do not stop after the first host handoff step.")
    args = parser.parse_args()

    route_payload = load_json(args.route_file)
    resource_contents = load_json(args.resource_contents_file) if args.resource_contents_file else {}
    mock_executor_results = load_json(args.mock_executor_results_file) if args.mock_executor_results_file else {}

    result = execute_selected_plan(
        route_payload,
        resource_contents=resource_contents,
        mock_executor_results=mock_executor_results,
        stop_on_host_handoff=not args.continue_after_handoff,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    main()
