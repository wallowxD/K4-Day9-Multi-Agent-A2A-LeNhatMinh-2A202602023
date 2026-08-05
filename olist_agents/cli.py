from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import (
    DEFAULT_DATA_DIR,
    DEFAULT_INPUT_DIR,
    DEFAULT_METADATA_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_TRACE_PATH,
    MODEL_NAME,
    MODEL_PARAMETER_SIZE,
    POLICY_VERSION,
)
from .llm import LlamaRuntime
from .orchestrator import CoordinatorAgent
from .repository import DataContractError, OlistRepository
from .trace import TraceWriter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Olist multi-agent dispute pipeline")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE_PATH)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA_PATH)
    parser.add_argument("--ollama-host", default=os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"))
    parser.add_argument("--llm-mode", choices=("auto", "required", "off"), default="auto")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Allow fewer than the required EC_001..EC_050 inputs (development only)",
    )
    parser.add_argument("--zip-output", type=Path, help="Create a zip containing output JSON files only")
    return parser


def load_cases(input_dir: Path, allow_partial: bool) -> list[tuple[Path, dict[str, Any]]]:
    paths = sorted(input_dir.glob("EC_*.json"))
    expected = [f"EC_{number:03d}.json" for number in range(1, 51)]
    names = [path.name for path in paths]
    if not allow_partial and names != expected:
        missing = [name for name in expected if name not in names]
        extra = [name for name in names if name not in expected]
        raise DataContractError(
            f"Expected exactly EC_001.json..EC_050.json; missing={missing}, extra={extra}"
        )
    if not paths:
        raise DataContractError(f"No EC_*.json inputs found in {input_dir}")

    cases: list[tuple[Path, dict[str, Any]]] = []
    for path in paths:
        try:
            case = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DataContractError(f"Cannot parse {path}: {exc}") from exc
        if case.get("case_id") != path.stem:
            raise DataContractError(
                f"Filename/case_id mismatch in {path.name}: {case.get('case_id')!r}"
            )
        cases.append((path, case))
    return cases


def write_metadata(
    path: Path,
    llama: LlamaRuntime,
    *,
    case_count: int,
    status: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "model": llama.model,
        "parameter_size": MODEL_PARAMETER_SIZE,
        "policy_version": POLICY_VERSION,
        "framework": "custom Python multi-agent orchestration",
        "runtime": f"Python {platform.python_version()}",
        "llm_provider": "Ollama",
        "llm_mode": llama.mode,
        "llm_calls": llama.calls,
        "llm_calls_completed": llama.completed_calls,
        "llm_calls_failed": llama.failed_calls,
        "case_count": case_count,
        "run_status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def create_output_zip(output_dir: Path, destination: Path, expected_count: int) -> None:
    outputs = sorted(output_dir.glob("EC_*.json"))
    if len(outputs) != expected_count:
        raise DataContractError(
            f"Refusing to zip: expected {expected_count} outputs, found {len(outputs)}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for output in outputs:
            archive.write(output, arcname=output.name)


def run(args: argparse.Namespace) -> int:
    cases = load_cases(args.input_dir, args.allow_partial)
    repository = OlistRepository(args.data_dir)
    llama = LlamaRuntime(model=MODEL_NAME, host=args.ollama_host, mode=args.llm_mode)
    trace = TraceWriter(args.trace)
    coordinator = CoordinatorAgent(repository, llama, trace)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    completed = 0
    try:
        for input_path, case in cases:
            result = coordinator.process(case)
            output_path = args.output_dir / input_path.name
            temporary_path = output_path.with_suffix(".json.tmp")
            temporary_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            temporary_path.replace(output_path)
            completed += 1
        if args.zip_output:
            create_output_zip(args.output_dir, args.zip_output, len(cases))
        status = "completed_with_llm_fallback" if llama.failed_calls else "completed"
        write_metadata(args.metadata, llama, case_count=completed, status=status)
    except Exception:
        write_metadata(args.metadata, llama, case_count=completed, status="failed")
        raise
    return 0


def main() -> None:
    parser = build_parser()
    try:
        raise SystemExit(run(parser.parse_args()))
    except DataContractError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
