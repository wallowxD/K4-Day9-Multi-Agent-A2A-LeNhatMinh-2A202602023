from pathlib import Path

MODEL_NAME = "llama3.2:3b"
MODEL_PARAMETER_SIZE = "3B"
POLICY_VERSION = "EC_POLICY_V2"

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = ROOT / "data"
DEFAULT_INPUT_DIR = ROOT / "input"
DEFAULT_OUTPUT_DIR = ROOT / "output"
DEFAULT_TRACE_PATH = ROOT / "logging" / "trace.jsonl"
DEFAULT_METADATA_PATH = ROOT / "logging" / "metadata.json"

LIMITS = {
    "order_ids": 5,
    "item_ids": 5,
    "seller_ids": 3,
    "payment_ids": 5,
    "related_order_ids": 5,
    "product_ids": 5,
    "category_names": 5,
    "ranked_causes": 3,
    "responsible_parties": 3,
    "evidence_ids": 20,
    "resolution_actions": 5,
}

