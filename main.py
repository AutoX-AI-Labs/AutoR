from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.manager import ResearchManager
from src.operator import ClaudeOperator
from src.utils import (
    DEFAULT_VENUE,
    STAGES,
    StageSpec,
    build_run_paths,
    load_run_config,
    resolve_venue_key,
)


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
        help=(
            "Claude model alias or full model name for real runs. "
            "Defaults to 'sonnet' for new runs and preserves the existing run model when resuming."
        ),
    )
    parser.add_argument(
        "--venue",
        help=(
            "Target venue profile for Stage 07 writing. "
            f"Defaults to '{DEFAULT_VENUE}' for new runs and preserves the existing run venue when resuming. "
            "Examples: neurips_2025, nature, nature_communications, jmlr."
        ),
    )
    parser.add_argument(
        "--resume-run",
        help="Resume an existing run by run_id under runs/. Use 'latest' to resume the most recent run.",
    )
    parser.add_argument(
        "--redo-stage",
        help="When resuming a run, restart from this stage slug or stage number (for example '06_analysis' or '6').",
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

    if args.resume_run:
        start_stage = resolve_stage(args.redo_stage)
        run_root = resolve_resume_run(runs_dir, args.resume_run)
        paths = build_run_paths(run_root)
        existing_config = load_run_config(paths)
        existing_model = existing_config.get("model")
        model = args.model or (existing_model if existing_model != "unknown" else None) or "sonnet"
        venue = resolve_venue_key(args.venue or existing_config["venue"])
        operator = ClaudeOperator(model=model, fake_mode=args.fake_operator)
        manager = ResearchManager(
            project_root=repo_root,
            runs_dir=runs_dir,
            operator=operator,
        )
        manager.resume_run(run_root, start_stage=start_stage, venue=venue)
        return 0

    model = args.model or "sonnet"
    venue = resolve_venue_key(args.venue or DEFAULT_VENUE)
    operator = ClaudeOperator(model=model, fake_mode=args.fake_operator)
    manager = ResearchManager(
        project_root=repo_root,
        runs_dir=runs_dir,
        operator=operator,
    )
    goal = args.goal.strip() if args.goal else read_user_goal()
    manager.run(goal, venue=venue)
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
