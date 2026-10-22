"""A local command: a packing list from today's weather. Called by planner.py as a subprocess."""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-c", type=float, required=True)
    parser.add_argument("--rain", type=float, required=True)
    args = parser.parse_args()
    items = ["water bottle", "phone charger"]
    if args.max_c >= 28:
        items += ["sunscreen", "cap"]
    if args.max_c <= 15:
        items.append("jacket")
    if args.rain >= 40:
        items.append("umbrella")
    print(", ".join(items))


if __name__ == "__main__":
    main()
