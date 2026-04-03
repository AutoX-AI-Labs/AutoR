"""Agent Card definition for the Claude Code A2A server."""
from __future__ import annotations

from a2a.types import (
    AgentCard,
    AgentCapabilities,
    AgentSkill,
    AgentProvider,
)


def build_agent_card(url: str) -> AgentCard:
    """Build the Agent Card describing this Claude Code research agent."""
    return AgentCard(
        name="claude-code-research",
        description=(
            "Claude Code research agent for AutoR pipeline. "
            "Executes 8-stage research workflows: literature survey, hypothesis, "
            "study design, implementation, experimentation, analysis, writing, dissemination."
        ),
        url=url,
        version="0.1.0",
        protocolVersion="0.3",
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
        capabilities=AgentCapabilities(
            streaming=True,
        ),
        skills=[
            AgentSkill(
                id="literature_survey",
                name="Literature Survey",
                description="Map the research landscape, collect references, identify gaps.",
                tags=["research", "literature"],
            ),
            AgentSkill(
                id="hypothesis",
                name="Hypothesis Generation",
                description="Narrow scope to a core claim with falsifiable predictions.",
                tags=["research", "hypothesis"],
            ),
            AgentSkill(
                id="study_design",
                name="Study Design",
                description="Design experiment protocol with machine-readable specs.",
                tags=["research", "design"],
            ),
            AgentSkill(
                id="implementation",
                name="Implementation",
                description="Write and debug research code.",
                tags=["code", "implementation"],
            ),
            AgentSkill(
                id="experimentation",
                name="Experimentation",
                description="Run experiments and produce machine-readable results.",
                tags=["code", "experimentation"],
            ),
            AgentSkill(
                id="analysis",
                name="Analysis",
                description="Interpret results, generate figures and tables.",
                tags=["research", "analysis"],
            ),
            AgentSkill(
                id="writing",
                name="Writing",
                description="Draft venue-aware LaTeX manuscript and compile PDF.",
                tags=["writing", "latex"],
            ),
            AgentSkill(
                id="dissemination",
                name="Dissemination",
                description="Prepare review materials, submission checklist, release bundle.",
                tags=["writing", "dissemination"],
            ),
        ],
        provider=AgentProvider(
            organization="AutoX-AI-Labs",
            url="https://github.com/AutoX-AI-Labs/AutoR",
        ),
    )
