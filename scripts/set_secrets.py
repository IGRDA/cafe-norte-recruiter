"""Create Secret Manager versions for provider keys from the environment; never via Terraform.

    set -a; . ./.env; set +a; uv run python scripts/set_secrets.py --project cafe-norte-orbio

Only names present in the environment are written; values travel on gcloud's stdin, never
on the command line or in output. ``--dry-run`` prints the names it would write. ``--only``
limits the run to the names given, so adding one key never re-writes the others from a local
``.env`` whose values differ from the hosted ones (the access code, the cookie secret)."""

import argparse
import os
import subprocess
import sys
from collections.abc import Collection, Mapping
from dataclasses import dataclass

SECRETS = (
    "OPENAI_API_KEY",
    "GROQ_API_KEY",
    "DAILY_API_KEY",
    "DEEPGRAM_API_KEY",
    "ELEVENLABS_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "CAFE_NORTE_ACCESS_CODE",
    "CAFE_NORTE_COOKIE_SECRET",
)


@dataclass(frozen=True)
class Command:
    name: str
    argv: list[str]
    stdin: str


def commands(
    project: str, env: Mapping[str, str], only: Collection[str] | None = None
) -> list[Command]:
    return [
        Command(
            name=name,
            argv=[
                "gcloud",
                "secrets",
                "versions",
                "add",
                name,
                "--project",
                project,
                "--data-file=-",
                "--quiet",
            ],
            stdin=env[name],
        )
        for name in SECRETS
        if env.get(name) and (only is None or name in only)
    ]


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", nargs="+", metavar="NAME", help="write only these secrets")
    args = parser.parse_args(argv)
    unknown = sorted(set(args.only or ()) - set(SECRETS))
    if unknown:
        print(f"not a managed secret: {', '.join(unknown)}", file=sys.stderr)
        return 2
    env = os.environ if env is None else env
    planned = commands(args.project, env, args.only)
    if not planned:
        print("no secret values in the environment", file=sys.stderr)
        return 1
    for command in planned:
        if args.dry_run:
            print(f"would add a version of {command.name}")
            continue
        result = subprocess.run(command.argv, input=command.stdin, text=True, capture_output=True)
        if result.returncode != 0:
            print(f"{command.name}: gcloud failed: {result.stderr.strip()[:200]}", file=sys.stderr)
            return 1
        print(f"{command.name}: {result.stdout.strip() or 'added'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
