from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .agents import AgentRuntimeManager, CommandResearchAgent
from .orchestration import SwarmPattern
from .types import ProvenanceRecord, ResearchTask, TaskResult


@dataclass(frozen=True)
class DebateTurn:
    agent_name: str
    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {
            "agent_name": self.agent_name,
            "role": self.role,
            "content": self.content,
        }


@dataclass(frozen=True)
class HypothesisDebateResult:
    rounds: int
    turns: list[DebateTurn]
    winning_hypothesis: str

    def to_dict(self) -> dict[str, object]:
        return {
            "rounds": self.rounds,
            "winning_hypothesis": self.winning_hypothesis,
            "turns": [turn.to_dict() for turn in self.turns],
        }


class HypothesisDebateWorkflow:
    def __init__(self) -> None:
        self.runtime = AgentRuntimeManager()
        self.runtime.register(
            CommandResearchAgent(
                name="proposal-agent",
                domain="general",
                pipeline_stages=["hypothesis_generation"],
                handler=self._proposal_handler,
            )
        )
        self.runtime.register(
            CommandResearchAgent(
                name="critic-agent",
                domain="general",
                pipeline_stages=["hypothesis_generation"],
                handler=self._critic_handler,
            )
        )
        self.runtime.register(
            CommandResearchAgent(
                name="moderator-agent",
                domain="general",
                pipeline_stages=["hypothesis_generation"],
                handler=self._moderator_handler,
            )
        )

    def run(self, goal: str, kb_context: list[str], rounds: int = 2) -> HypothesisDebateResult:
        turns: list[DebateTurn] = []
        current_hypothesis = ""
        pattern = SwarmPattern(rounds=rounds)

        def runner(task: ResearchTask) -> TaskResult:
            agent = self.runtime.get(task.title)
            return agent.run(task)

        tasks = [
            ResearchTask(
                task_id="proposal",
                title="proposal-agent",
                goal=goal,
                pipeline_stage="hypothesis_generation",
                project_id="debate",
                kb_context=kb_context,
                human_gate_required=False,
            ),
            ResearchTask(
                task_id="critic",
                title="critic-agent",
                goal=goal,
                pipeline_stage="hypothesis_generation",
                project_id="debate",
                kb_context=kb_context,
                human_gate_required=False,
            ),
            ResearchTask(
                task_id="moderator",
                title="moderator-agent",
                goal=goal,
                pipeline_stage="hypothesis_generation",
                project_id="debate",
                kb_context=kb_context,
                human_gate_required=False,
            ),
        ]

        for result in pattern.execute(tasks, runner):
            role = result.provenance[0].action.split(":", 1)[0]
            turns.append(DebateTurn(agent_name=result.provenance[0].agent_name, role=role, content=result.output))
            if role == "moderator":
                current_hypothesis = result.output

        return HypothesisDebateResult(rounds=rounds, turns=turns, winning_hypothesis=current_hypothesis)

    def write_artifacts(self, output_dir: Path, stage_slug: str, result: HypothesisDebateResult) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / f"{stage_slug}_debate.json"
        md_path = output_dir / f"{stage_slug}_debate.md"
        json_path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        lines = [f"# Hypothesis Debate for {stage_slug}", "", f"Winning hypothesis: {result.winning_hypothesis}", ""]
        for turn in result.turns:
            lines.extend([f"## {turn.agent_name}", turn.content, ""])
        md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return [json_path, md_path]

    def _proposal_handler(self, task: ResearchTask) -> TaskResult:
        hypothesis = (
            f"Hypothesis: prioritizing a focused, evidence-backed approach to '{task.goal[:120]}' "
            "will improve reproducibility and literature grounding."
        )
        return TaskResult(
            task_id=task.task_id,
            output=hypothesis,
            provenance=[ProvenanceRecord(agent_name="proposal-agent", action="proposal:generate")],
        )

    def _critic_handler(self, task: ResearchTask) -> TaskResult:
        critique = (
            "Critique: the hypothesis should be falsifiable, name at least one failure mode, "
            "and be tied to measurable outcomes and comparison baselines."
        )
        return TaskResult(
            task_id=task.task_id,
            output=critique,
            provenance=[ProvenanceRecord(agent_name="critic-agent", action="critic:challenge")],
        )

    def _moderator_handler(self, task: ResearchTask) -> TaskResult:
        synthesis = (
            "Moderator synthesis: adopt a hypothesis that explicitly names the expected benefit, "
            "the comparison baseline, and the main falsification criterion."
        )
        return TaskResult(
            task_id=task.task_id,
            output=synthesis,
            provenance=[ProvenanceRecord(agent_name="moderator-agent", action="moderator:synthesize")],
        )
