"""
CLI entry point for swarm-lite micro-worker orchestration engine.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from swarm_lite import __version__
from swarm_lite.engine import LifecyclePolicy, SwarmOrchestrator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="swarm-lite",
        description="Ultra-low-token 30+ agent swarm orchestration engine.",
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"%(prog)s {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Command: run
    run_parser = subparsers.add_parser("run", help="Run a multi-worker micro-agent swarm job.")
    run_parser.add_argument(
        "-w", "--workers", type=int, default=30, help="Number of micro-workers to fan out (default: 30)"
    )
    run_parser.add_argument(
        "-p",
        "--policy",
        type=str,
        default="single_turn_immediate",
        choices=[p.value for p in LifecyclePolicy],
        help="Default lifecycle policy for workers",
    )
    run_parser.add_argument(
        "-t", "--task", type=str, default="Micro-task execution", help="Description of task to perform"
    )
    run_parser.add_argument(
        "--db-path", type=str, default=None, help="Custom SQLite DB path for state bus"
    )

    # Command: status
    status_parser = subparsers.add_parser("status", help="Get swarm execution metrics and status JSON.")
    status_parser.add_argument(
        "--db-path", type=str, default=None, help="Custom SQLite DB path for state bus"
    )

    # Command: list
    list_parser = subparsers.add_parser("list", help="List active and historical micro-workers.")
    list_parser.add_argument(
        "--db-path", type=str, default=None, help="Custom SQLite DB path for state bus"
    )

    # Command: render
    render_parser = subparsers.add_parser("render", help="Render executive ASCII dashboard matrix.")
    render_parser.add_argument(
        "--db-path", type=str, default=None, help="Custom SQLite DB path for state bus"
    )

    # Global flags compatibility (--status, --render)
    parser.add_argument("--status", action="store_true", help="Display status JSON")
    parser.add_argument("--render", action="store_true", help="Display ASCII dashboard matrix")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    db_path = getattr(args, "db_path", None)
    orchestrator = SwarmOrchestrator(db_path=db_path)

    try:
        if args.status:
            print(json.dumps(orchestrator.get_status(), indent=2))
            return 0

        if args.render:
            print(orchestrator.render_matrix())
            return 0

        if args.command == "run":
            num_workers = args.workers
            policy = args.policy
            task = args.task

            print(f"[Swarm-Lite] Fanning out {num_workers} micro-workers using policy '{policy}'...")
            specs = [
                {
                    "worker_id": f"worker-{i+1:02d}",
                    "role": f"agent-type-{(i % 4) + 1}",
                    "task": f"{task} - part {i+1}",
                    "policy": policy,
                    "max_tokens": 1500,
                }
                for i in range(num_workers)
            ]

            summary = orchestrator.fan_out(specs)
            print(f"[Swarm-Lite] Run finished. Executed {summary['total_workers']} micro-workers.")
            print(orchestrator.render_matrix())
            return 0

        elif args.command == "status":
            print(json.dumps(orchestrator.get_status(), indent=2))
            return 0

        elif args.command == "list":
            status_info = orchestrator.get_status()
            print(json.dumps(status_info["workers"], indent=2))
            return 0

        elif args.command == "render":
            print(orchestrator.render_matrix())
            return 0

        else:
            parser.print_help()
            return 0
    finally:
        orchestrator.close()



if __name__ == "__main__":
    sys.exit(main())
