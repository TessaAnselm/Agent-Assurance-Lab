"""Generate the lab's fixed dialogue locally using an XTTS reference recording."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import wave

ROOT = Path(__file__).resolve().parents[1]
MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
LICENSE = "https://huggingface.co/coqui/XTTS-v2/blob/main/LICENSE.txt"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--accept-noncommercial-license", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "frontend" / "audio")
    args = parser.parse_args()
    if not args.reference.is_file():
        parser.error("Reference recording does not exist")
    if not args.accept_noncommercial_license:
        parser.error(f"Read {LICENSE}, then pass --accept-noncommercial-license if you accept")

    # The model downloads locally; the speaker reference is never uploaded.
    os.environ["COQUI_TOS_AGREED"] = "1"
    import torch
    from TTS.api import TTS

    torch.set_num_threads(min(4, os.cpu_count() or 1))
    lines = json.loads((ROOT / "frontend" / "dialogue.json").read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {"model": MODEL, "license": LICENSE, "clips": {}}
    with tempfile.TemporaryDirectory(prefix="lab-voice-") as temporary:
        reference = Path(temporary) / "reference.wav"
        subprocess.run([
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i",
            str(args.reference.resolve()), "-ac", "1", "-ar", "24000",
            "-af", "loudnorm=I=-23:TP=-2:LRA=7", "-c:a", "pcm_s16le", str(reference),
        ], check=True)
        model = TTS(MODEL).to("cpu")
        for stage, text in lines.items():
            fingerprint = hashlib.sha256(text.encode()).hexdigest()[:12]
            filename = f"{stage}-{fingerprint}.wav"
            output = args.output / filename
            print(f"Generating {stage}...", flush=True)
            model.tts_to_file(text=text, speaker_wav=str(reference), language="en", file_path=str(output))
            with wave.open(str(output)) as audio:
                duration = audio.getnframes() / audio.getframerate()
                if duration < 1:
                    raise RuntimeError(f"Generated audio too short: {stage}")
            manifest["clips"][stage] = {"text": text, "file": filename, "duration": round(duration, 3)}
            print(f"  {duration:.1f} seconds", flush=True)
    # Publish the manifest only when every clip was successfully generated.
    pending = args.output / "manifest.tmp"
    pending.write_text(json.dumps(manifest, indent=2) + "\n")
    pending.replace(args.output / "manifest.json")
    print(f"Generated {len(lines)} clips in {args.output}")


if __name__ == "__main__":
    main()
