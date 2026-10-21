"""The spec's listening check: the same two short scripts, Spanish and English, through a few
ElevenLabs multilingual voices. Paid (a few hundred characters per voice); manual; never CI.

    uv run python scripts/voice_listen.py            # writes /tmp/voices/<voice>-<lang>.mp3
    uv run python scripts/voice_listen.py --voices id1 id2
"""

import argparse
import os
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values

# ElevenLabs premade multilingual voices commonly used for Spanish; override with --voices.
CANDIDATES = {
    "laura": "FGY2WhTYpPnrIDTdsKH5",
    "sarah": "EXAVITQu4vr4xnSDxMaL",
    "matilda": "XrExE9yKIg1WjnnlVkGX",
}
SCRIPTS = {
    "es": (
        "Hola, soy Ana, la asistente de IA de Café Norte. He apuntado que podrías empezar el "
        "lunes 26 de octubre. ¿Es correcto?"
    ),
    "en": (
        "Hi, I'm Ana, Café Norte's AI assistant. I have noted that you could start on Monday "
        "the 26th of October. Is that right?"
    ),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices", nargs="*", default=list(CANDIDATES.values()))
    parser.add_argument("--out", default="/tmp/voices")
    args = parser.parse_args(argv)
    key = os.environ.get("ELEVENLABS_API_KEY") or dotenv_values(".env").get("ELEVENLABS_API_KEY")
    if not key:
        print("ELEVENLABS_API_KEY is not set", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    names = {v: k for k, v in CANDIDATES.items()}
    with httpx.Client(timeout=60, headers={"xi-api-key": key}) as client:
        for voice_id in args.voices:
            for lang, text in SCRIPTS.items():
                response = client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                    json={"text": text, "model_id": "eleven_flash_v2_5"},
                    headers={"Accept": "audio/mpeg"},
                )
                label = names.get(voice_id, voice_id)
                if response.status_code != 200:
                    print(f"{label} {lang}: HTTP {response.status_code} {response.text[:120]}")
                    continue
                path = out / f"{label}-{lang}.mp3"
                path.write_bytes(response.content)
                print(f"{label} ({voice_id}) {lang}: {len(response.content)} bytes → {path}")
    print("Listen, pick one, and put its id in .env as ELEVENLABS_VOICE_ID.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
