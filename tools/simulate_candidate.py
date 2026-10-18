"""Enqueue an actual team candidate in the local CANN worker, without model calls."""

import argparse
import asyncio
import json

from aworker.config import Settings
from aworker.lab.service import LabService


# ---- main ------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--team", required=True)
    parser.add_argument("--case", action="append", dest="cases")
    parser.add_argument("--hypothesis", default="Independent source compile/simulation validation")
    args = parser.parse_args()
    service = LabService(Settings())
    result = asyncio.run(
        service.simulator.evaluate(args.team, "manual-simulation", args.hypothesis, args.cases)
    )
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
