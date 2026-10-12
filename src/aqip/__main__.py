"""CLI: python -m aqip <ingest|clean|warehouse|insights|train|pipeline> [--incremental]"""
from __future__ import annotations

import argparse
import json
import logging


def main() -> None:
    ap = argparse.ArgumentParser(prog="aqip")
    ap.add_argument("step", choices=["ingest", "clean", "warehouse", "insights", "train", "pipeline", "all"])
    ap.add_argument("--incremental", action="store_true", help="ingest only the last 7 days")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    from . import clean, ingest, warehouse

    if args.step in ("ingest", "pipeline", "all"):
        ingest.run(incremental=args.incremental)
    if args.step in ("clean", "pipeline", "all"):
        clean.run()
    if args.step in ("warehouse", "pipeline", "all"):
        print(json.dumps(warehouse.build(), indent=2))
    if args.step in ("insights", "all"):
        from . import insights
        insights.run()
    if args.step in ("train", "all"):
        from . import train
        train.run()


if __name__ == "__main__":
    main()
