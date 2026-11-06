"""CLI for reproducible, local Phase 1 ingestion."""
import argparse
import json
from pathlib import Path
from .ingestion import ingest_phase1


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Phase 1 judicial annotations")
    parser.add_argument("--texts", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("data/interim/phase_1"))
    parser.add_argument("--labels", type=Path, default=Path("configs/labels.json"))
    parser.add_argument("--aliases", type=Path, default=Path("configs/label_aliases.json"))
    parser.add_argument(
        "--texts-encoding", default="auto",
        help="CSV encoding for documents (default: auto)",
    )
    parser.add_argument(
        "--annotations-encoding", default="auto",
        help="CSV encoding for annotations (default: auto)",
    )
    args = parser.parse_args()
    result = ingest_phase1(args.texts, args.annotations, args.output, args.labels, args.aliases, args.texts_encoding, args.annotations_encoding)
    print(json.dumps(result, ensure_ascii=False, indent=2))
