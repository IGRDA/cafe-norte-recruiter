"""Load cases, drive sessions, score, report."""

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals")
    parser.add_argument(
        "--suite", choices=["scenarios", "retrieval", "comparison"], default="scenarios"
    )
    parser.add_argument("--mode", choices=["fake", "live"], default="fake")
    parser.add_argument("--only", nargs="*", default=[])
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--models", nargs="*", default=[])
    parser.add_argument("--judge", default="off")
    parser.add_argument("--list", action="store_true")
    parser.parse_args(argv)
    raise NotImplementedError
