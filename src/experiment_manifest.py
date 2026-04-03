from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .artifact_index import indexed_artifacts_for_category, write_artifact_index
from .utils import RunPaths


@dataclass(frozen=True)
class ExperimentManifest:
    generated_at: str
    ready_for_analysis: bool
    result_artifacts: list[dict[str, object]]
    code_artifacts: list[str]
    note_artifacts: list[str]
    summary: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "ready_for_analysis": self.ready_for_analysis,
            "result_artifacts": self.result_artifacts,
            "code_artifacts": self.code_artifacts,
            "note_artifacts": self.note_artifacts,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "ExperimentManifest":
        return cls(
            generated_at=str(payload.get("generated_at", "")).strip(),
            ready_for_analysis=bool(payload.get("ready_for_analysis", False)),
            result_artifacts=[
                dict(item)
                for item in payload.get("result_artifacts", [])
                if isinstance(item, dict)
            ],
            code_artifacts=[
                str(item)
                for item in payload.get("code_artifacts", [])
                if str(item).strip()
            ],
            note_artifacts=[
                str(item)
                for item in payload.get("note_artifacts", [])
                if str(item).strip()
            ],
            summary={
                str(key): int(value)
                for key, value in dict(payload.get("summary", {})).items()
            },
        )


def write_experiment_manifest(paths: RunPaths) -> ExperimentManifest:
    artifact_index = write_artifact_index(paths)
    result_artifacts = [
        artifact
        for artifact in indexed_artifacts_for_category(artifact_index, "results")
        if artifact.get("rel_path") != "results/experiment_manifest.json"
    ]
    code_artifacts = _list_relative_files(paths.code_dir, paths.workspace_root)
    note_artifacts = _list_relative_files(paths.notes_dir, paths.workspace_root)
    manifest = ExperimentManifest(
        generated_at=datetime.now().isoformat(timespec="seconds"),
        ready_for_analysis=bool(result_artifacts),
        result_artifacts=result_artifacts,
        code_artifacts=code_artifacts,
        note_artifacts=note_artifacts,
        summary={
            "result_artifact_count": len(result_artifacts),
            "code_artifact_count": len(code_artifacts),
            "note_artifact_count": len(note_artifacts),
        },
    )
    paths.experiment_manifest.write_text(
        json.dumps(manifest.to_dict(), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def load_experiment_manifest(path: Path) -> ExperimentManifest | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ExperimentManifest.from_dict(payload)


def validate_experiment_manifest(path: Path) -> list[str]:
    manifest = load_experiment_manifest(path)
    if manifest is None:
        return ["Missing experiment_manifest.json."]

    problems: list[str] = []
    if not manifest.generated_at:
        problems.append("experiment_manifest.json is missing generated_at.")
    if "result_artifact_count" not in manifest.summary:
        problems.append("experiment_manifest.json is missing summary.result_artifact_count.")
    if "code_artifact_count" not in manifest.summary:
        problems.append("experiment_manifest.json is missing summary.code_artifact_count.")
    if "note_artifact_count" not in manifest.summary:
        problems.append("experiment_manifest.json is missing summary.note_artifact_count.")
    if not isinstance(manifest.ready_for_analysis, bool):
        problems.append("experiment_manifest.json must contain a boolean ready_for_analysis field.")

    for artifact in manifest.result_artifacts:
        rel_path = str(artifact.get("rel_path", "")).strip()
        if not rel_path:
            problems.append("experiment_manifest.json contains a result artifact without rel_path.")
            continue
        schema = artifact.get("schema")
        if not isinstance(schema, dict):
            problems.append(
                f"experiment_manifest.json result artifact `{rel_path}` is missing schema metadata."
            )

    return problems


def format_experiment_manifest_for_prompt(manifest: ExperimentManifest, max_results: int = 5) -> str:
    lines = [
        f"Experiment manifest generated at: {manifest.generated_at}",
        f"Ready for analysis: {'yes' if manifest.ready_for_analysis else 'no'}",
        (
            "Summary: "
            f"{manifest.summary['result_artifact_count']} result artifacts, "
            f"{manifest.summary['code_artifact_count']} code artifacts, "
            f"{manifest.summary['note_artifact_count']} note artifacts"
        ),
    ]

    if manifest.result_artifacts:
        lines.append("\n### Result Artifacts")
        for artifact in manifest.result_artifacts[:max_results]:
            rel_path = str(artifact.get("rel_path", "")).strip()
            schema = artifact.get("schema", {})
            summary = _format_schema(schema)
            line = f"- `{rel_path}`"
            if summary:
                line += f" | {summary}"
            lines.append(line)

    if manifest.code_artifacts:
        lines.append("\n### Supporting Code")
        for rel_path in manifest.code_artifacts[:max_results]:
            lines.append(f"- `{rel_path}`")

    if manifest.note_artifacts:
        lines.append("\n### Experiment Notes")
        for rel_path in manifest.note_artifacts[:max_results]:
            lines.append(f"- `{rel_path}`")

    return "\n".join(lines)


def _list_relative_files(directory: Path, workspace_root: Path) -> list[str]:
    if not directory.exists():
        return []
    return sorted(
        str(path.relative_to(workspace_root))
        for path in directory.rglob("*")
        if path.is_file()
    )


def _format_schema(schema: object) -> str:
    if not isinstance(schema, dict) or not schema:
        return ""

    pieces: list[str] = []
    kind = str(schema.get("kind") or schema.get("source") or "").strip()
    if kind:
        pieces.append(kind)
    if isinstance(schema.get("columns"), list) and schema["columns"]:
        pieces.append("columns=" + ", ".join(str(item) for item in schema["columns"][:6]))
    if isinstance(schema.get("keys"), list) and schema["keys"]:
        pieces.append("keys=" + ", ".join(str(item) for item in schema["keys"][:6]))
    if "row_count" in schema:
        pieces.append(f"rows={schema['row_count']}")
    if "item_count" in schema:
        pieces.append(f"items={schema['item_count']}")

    return ", ".join(pieces)
