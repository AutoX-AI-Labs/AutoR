from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.manager import ResearchManager
from src.operator import ClaudeOperator
from src.utils import STAGES, StageSpec


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AutoR research workflow runner")
    parser.add_argument(
        "--goal",
        help="Research goal. If omitted, the goal is collected from terminal input.",
    )
    parser.add_argument(
        "--runs-dir",
        default="runs",
        help="Directory used to store run artifacts. Defaults to runs/ under the repo root.",
    )
    parser.add_argument(
        "--fake-operator",
        action="store_true",
        help="Use a fake operator for local validation instead of invoking Claude.",
    )
    parser.add_argument(
        "--model",
        default="sonnet",
        help="Claude model alias or full model name for real runs. Defaults to 'sonnet'.",
    )
    parser.add_argument(
        "--resume-run",
        help="Resume an existing run by run_id under runs/. Use 'latest' to resume the most recent run.",
    )
    parser.add_argument(
        "--redo-stage",
        help="When resuming a run, restart from this stage slug or stage number (for example '06_analysis' or '6').",
    )
    parser.add_argument(
        "--rollback-stage",
        help="When resuming a run, roll back to this stage and mark downstream stages stale before continuing.",
    )
    parser.add_argument(
        "--show-status",
        action="store_true",
        help="Print the structured run status for --resume-run and exit.",
    )
    parser.add_argument(
        "--kb-search",
        help="Search the run knowledge base for --resume-run and exit.",
    )
    parser.add_argument(
        "--kb-limit",
        type=int,
        default=5,
        help="Maximum number of knowledge-base results to return with --kb-search. Defaults to 5.",
    )
    return parser.parse_args()


def resolve_stage(value: str | None) -> StageSpec | None:
    if value is None:
        return None

    normalized = value.strip().lower()
    if not normalized:
        return None

    for stage in STAGES:
        if normalized in {stage.slug.lower(), str(stage.number), f"{stage.number:02d}"}:
            return stage

    raise ValueError(f"Unknown stage identifier: {value}")


def resolve_resume_run(runs_dir: Path, value: str) -> Path:
    if value == "latest":
        candidates = sorted(path for path in runs_dir.iterdir() if path.is_dir())
        if not candidates:
            raise FileNotFoundError(f"No runs found in {runs_dir}")
        return candidates[-1]

    run_root = runs_dir / value
    if not run_root.exists() or not run_root.is_dir():
        raise FileNotFoundError(f"Run not found: {run_root}")
    return run_root


def read_user_goal() -> str:
    print("Enter your research goal. Finish with an empty line on a new line:")
    lines: list[str] = []

    while True:
        prompt = "> " if not lines else ""
        try:
            line = input(prompt)
        except EOFError:
            break

        if not line.strip():
            if lines:
                break
            continue

        lines.append(line.rstrip())

    goal = "\n".join(lines).strip()
    if not goal:
        raise ValueError("Research goal cannot be empty.")
    return goal


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent
    runs_dir = repo_root / args.runs_dir

    operator = ClaudeOperator(model=args.model, fake_mode=args.fake_operator)
    manager = ResearchManager(
        project_root=repo_root,
        runs_dir=runs_dir,
        operator=operator,
    )

    if args.resume_run:
        run_root = resolve_resume_run(runs_dir, args.resume_run)
        if args.show_status or args.kb_search:
            if args.redo_stage or args.rollback_stage:
                raise ValueError("--redo-stage/--rollback-stage cannot be combined with --show-status or --kb-search.")
            if args.show_status:
                print(manager.describe_run_status(run_root))
            if args.kb_search:
                print(manager.search_run_knowledge_base(run_root, args.kb_search, limit=max(args.kb_limit, 1)))
            return 0

        start_stage = resolve_stage(args.redo_stage)
        rollback_stage = resolve_stage(args.rollback_stage)
        if start_stage is not None and rollback_stage is not None:
            raise ValueError("--redo-stage and --rollback-stage are mutually exclusive.")
        manager.resume_run(run_root, start_stage=start_stage, rollback_stage=rollback_stage)
        return 0

    goal = args.goal.strip() if args.goal else read_user_goal()
    manager.run(goal)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
