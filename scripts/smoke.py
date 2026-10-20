"""Post-deployment smoke check: page, health, access gate and optionally one text turn."""

import sys


def main(url: str) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"))
