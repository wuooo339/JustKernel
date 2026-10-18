"""Dispatch a registered team through the public A2A client, without client-side keys."""

import argparse
import asyncio
import json

from aworker.server.client import send_text_message


# ---- main -------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("task")
    parser.add_argument("--team", default="gpt-a")
    parser.add_argument("--url", default="http://127.0.0.1:4173/a2a/")
    args = parser.parse_args()
    print(
        asyncio.run(send_text_message(args.url, json.dumps({"team": args.team, "task": args.task})))
    )


if __name__ == "__main__":
    main()
