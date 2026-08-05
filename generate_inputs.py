from __future__ import annotations

import argparse
import json
from pathlib import Path

from olist_agents.config import DEFAULT_DATA_DIR, DEFAULT_INPUT_DIR
from olist_agents.input_generator import InputGenerator
from olist_agents.repository import OlistRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate 50 source-backed cases from Olist CSV")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    args = parser.parse_args()
    manifest = InputGenerator(OlistRepository(args.data_dir)).write(args.input_dir)
    counts: dict[str, int] = {}
    for row in manifest:
        issue = row["expected_issue"]
        counts[issue] = counts.get(issue, 0) + 1
    print(json.dumps({"generated": len(manifest), "distribution": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()

