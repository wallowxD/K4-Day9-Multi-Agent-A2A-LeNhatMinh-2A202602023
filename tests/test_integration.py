from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from olist_agents.cli import run
from olist_agents.config import DEFAULT_DATA_DIR
from olist_agents.llm import LlamaRuntime
from olist_agents.orchestrator import CoordinatorAgent
from olist_agents.repository import OlistRepository
from olist_agents.trace import TraceWriter


class PipelineIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repository = OlistRepository(DEFAULT_DATA_DIR)

    def test_real_olist_order_passes_verifier(self) -> None:
        case = self.sample_case()
        with tempfile.TemporaryDirectory() as directory:
            trace_path = Path(directory) / "trace.jsonl"
            coordinator = CoordinatorAgent(
                self.repository,
                LlamaRuntime(mode="off"),
                TraceWriter(trace_path),
            )
            result = coordinator.process(case)
            trace_rows = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(result["case_id"], "EC_001")
        self.assertEqual(result["case_assessment"]["primary_issue"], "valid_split_payment")
        self.assertTrue(result["payment_reconciliation"]["reconciled"])
        self.assertGreaterEqual(len(result["affected_entities"]["payment_ids"]), 2)
        self.assertEqual(result["financial_resolution"]["recommended_refund_brl"], 0.0)
        self.assertTrue(any(row["event"] == "hard_gate_passed" for row in trace_rows))

    def test_batch_cli_writes_output_trace_metadata_and_clean_zip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_dir = root / "input"
            input_dir.mkdir()
            (input_dir / "EC_001.json").write_text(
                json.dumps(self.sample_case(), ensure_ascii=False), encoding="utf-8"
            )
            args = Namespace(
                data_dir=DEFAULT_DATA_DIR,
                input_dir=input_dir,
                output_dir=root / "output",
                trace=root / "logging" / "trace.jsonl",
                metadata=root / "logging" / "metadata.json",
                ollama_host="http://127.0.0.1:11434",
                llm_mode="off",
                allow_partial=True,
                zip_output=root / "output.zip",
            )
            self.assertEqual(run(args), 0)
            output = json.loads((args.output_dir / "EC_001.json").read_text(encoding="utf-8"))
            metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
            import zipfile

            with zipfile.ZipFile(args.zip_output) as archive:
                zip_names = archive.namelist()

        self.assertEqual(output["case_id"], "EC_001")
        self.assertEqual(metadata["run_status"], "completed")
        self.assertEqual(metadata["case_count"], 1)
        self.assertEqual(zip_names, ["EC_001.json"])

    @staticmethod
    def sample_case() -> dict[str, object]:
        return {
            "case_id": "EC_001",
            "customer_request": {
                "language": "vi",
                "message": "Điều tra khiếu nại giao hàng.",
                "claimed_order_id": "e481f51cbdc54678b7cc49136f2d6af7",
            },
            "investigation_scope": {
                "include_customer_history": True,
                "include_product_context": True,
            },
            "policy_version": "EC_POLICY_V2",
        }


if __name__ == "__main__":
    unittest.main()
