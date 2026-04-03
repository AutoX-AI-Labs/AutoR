from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.artifact_index import format_artifact_index_for_prompt, load_artifact_index, write_artifact_index
from src.utils import build_run_paths, ensure_run_layout, write_text
from src.writing_manifest import build_writing_manifest


class ArtifactIndexTests(unittest.TestCase):
    def _build_paths(self) -> object:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        run_root = Path(tmp_dir.name) / "run"
        paths = build_run_paths(run_root)
        ensure_run_layout(paths)
        return paths

    def test_write_artifact_index_indexes_structured_workspace_artifacts(self) -> None:
        paths = self._build_paths()
        write_text(paths.data_dir / "dataset.csv", "id,label\n1,cat\n2,dog\n")
        write_text(
            paths.data_dir / "dataset.csv.schema.json",
            json.dumps({"kind": "table", "columns": ["id", "label"], "primary_key": "id"}),
        )
        write_text(
            paths.results_dir / "metrics.jsonl",
            '{"metric":"accuracy","value":0.9}\n{"metric":"loss","value":0.1}\n',
        )
        (paths.figures_dir / "accuracy.png").write_bytes(b"\x89PNG fake image data")

        index = write_artifact_index(paths)
        self.assertEqual(index.artifact_count, 3)
        self.assertEqual(index.counts_by_category["data"], 1)
        self.assertEqual(index.counts_by_category["results"], 1)
        self.assertEqual(index.counts_by_category["figures"], 1)

        loaded = load_artifact_index(paths.artifact_index)
        self.assertIsNotNone(loaded)
        assert loaded is not None

        by_path = {artifact.rel_path: artifact for artifact in loaded.artifacts}
        self.assertEqual(by_path["data/dataset.csv"].schema["source"], "declared")
        self.assertEqual(
            by_path["data/dataset.csv"].schema["sidecar_path"],
            "data/dataset.csv.schema.json",
        )
        self.assertEqual(by_path["results/metrics.jsonl"].schema["row_count"], 2)
        self.assertIn("metric", by_path["results/metrics.jsonl"].schema["keys"])
        self.assertEqual(by_path["figures/accuracy.png"].schema["kind"], "figure")

        prompt_context = format_artifact_index_for_prompt(loaded)
        self.assertIn("results/metrics.jsonl", prompt_context)
        self.assertIn("rows=2", prompt_context)

    def test_writing_manifest_reuses_artifact_index_metadata(self) -> None:
        paths = self._build_paths()
        write_text(paths.data_dir / "study_design.json", '{"dataset":"demo"}')
        write_text(paths.results_dir / "scores.csv", "step,score\n1,0.5\n2,0.7\n")
        (paths.figures_dir / "curve.png").write_bytes(b"\x89PNG fake image data")

        manifest = build_writing_manifest(paths)
        self.assertEqual(manifest["artifact_index_path"], "artifact_index.json")

        result_files = manifest["result_files"]
        assert isinstance(result_files, list)
        self.assertEqual(result_files[0]["rel_path"], "results/scores.csv")
        self.assertEqual(result_files[0]["schema"]["row_count"], 2)

        data_files = manifest["data_files"]
        assert isinstance(data_files, list)
        self.assertEqual(data_files[0]["rel_path"], "data/study_design.json")
        self.assertEqual(data_files[0]["schema"]["kind"], "object")


if __name__ == "__main__":
    unittest.main()
