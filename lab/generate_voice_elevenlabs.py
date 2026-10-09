#!/usr/bin/env python3
"""Generate the monster's narration clips via ElevenLabs text-to-speech.

Reads frontend/dialogue.json (the same source the Coqui pipeline uses),
renders each stage's line through ElevenLabs' TTS API, and writes
frontend/audio/manifest.json in the exact shape app.js already expects --
so no frontend change is needed to switch voice backends.

Usage:
    python3 lab/generate_voice_elevenlabs.py
    python3 lab/generate_voice_elevenlabs.py --voice-id <id>
    python3 lab/generate_voice_elevenlabs.py --list-voices

Requires ELEVENLABS_API_KEY in a .env file at the repo root. The key is
read from that file and used only as an HTTP header -- this script never
prints it, logs it, or echoes it back anywhere.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DIALOGUE_PATH = REPO_ROOT / "frontend" / "dialogue.json"
AUDIO_DIR = REPO_ROOT / "frontend" / "audio"
MANIFEST_PATH = AUDIO_DIR / "manifest.json"
ENV_PATH = REPO_ROOT / ".env"

API_BASE = "https://api.elevenlabs.io/v1"
OUTPUT_FORMAT = "mp3_44100_128"
DEFAULT_MODEL_ID = "eleven_multilingual_v2"
# George is an ElevenLabs default voice with a warm, crisp storytelling tone.
# Keeping a known default means a TTS-only API key does not also need the
# voices_read permission just to render the frontend's fixed narration.
DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
DEFAULT_VOICE_NAME = "George"
VOICE_SETTINGS = {
    "stability": 0.42,
    "similarity_boost": 0.78,
    "style": 0.16,
    "use_speaker_boost": True,
    "speed": 1.04,
}


def load_env(path: Path) -> dict[str, str]:
    """Tiny .env parser -- plain KEY=value lines, no quoting needed here."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def api_request(path: str, api_key: str, method: str = "GET", body: dict[str, Any] | None = None) -> bytes:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"xi-api-key": api_key}
    if data is not None:
        headers["content-type"] = "application/json"
    req = urllib.request.Request(f"{API_BASE}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"ElevenLabs API error {e.code} on {method} {path}: {detail}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Could not reach ElevenLabs on {method} {path}: {e.reason}")


def list_voices(api_key: str) -> list[dict[str, Any]]:
    return json.loads(api_request("/voices", api_key))["voices"]


def synthesize(text: str, voice_id: str, api_key: str) -> bytes:
    """Return a browser-ready MP3 narration clip."""
    return api_request(
        f"/text-to-speech/{voice_id}?output_format={OUTPUT_FORMAT}",
        api_key,
        method="POST",
        body={
            "text": text,
            "model_id": DEFAULT_MODEL_ID,
            "voice_settings": VOICE_SETTINGS,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice-id", default=None, help="ElevenLabs voice id. Defaults to the account's first premade voice.")
    parser.add_argument("--list-voices", action="store_true", help="Print available voices and exit -- makes no TTS calls.")
    args = parser.parse_args()

    env = load_env(ENV_PATH)
    api_key = env.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(f"ELEVENLABS_API_KEY is not set in {ENV_PATH}. Add it there (not on the command line).")

    if args.list_voices:
        voices = list_voices(api_key)
        for v in voices:
            print(f"{v['voice_id']}  {v.get('name', '?'):20} category={v.get('category')}")
        return 0

    if args.voice_id:
        voice_id = args.voice_id
        chosen_name = "custom voice"
    else:
        voice_id = DEFAULT_VOICE_ID
        chosen_name = DEFAULT_VOICE_NAME

    print(f"Using voice: {chosen_name} ({voice_id})")

    dialogue: dict[str, str] = json.loads(DIALOGUE_PATH.read_text(encoding="utf-8"))
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    clips: dict[str, dict[str, str]] = {}
    for stage_key, text in dialogue.items():
        print(f"  generating {stage_key} ({len(text)} chars)...")
        audio = synthesize(text, voice_id, api_key)
        file_name = f"{stage_key}-elevenlabs.mp3"
        (AUDIO_DIR / file_name).write_bytes(audio)
        clips[stage_key] = {"text": text, "file": file_name}

    manifest = {
        "provider": "ElevenLabs",
        "model": DEFAULT_MODEL_ID,
        "voice": {"id": voice_id, "name": chosen_name},
        "settings": VOICE_SETTINGS,
        "clips": clips,
    }
    pending_manifest = MANIFEST_PATH.with_suffix(".tmp")
    pending_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    pending_manifest.replace(MANIFEST_PATH)
    print(f"\nWrote {len(clips)} clips and {MANIFEST_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
