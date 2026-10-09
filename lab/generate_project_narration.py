#!/usr/bin/env python3
"""Render paragraph-based project narration with a local XTTS voice reference."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import tempfile

MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    for path in (args.text, args.reference):
        if not path.is_file():
            parser.error(f"Missing input: {path}")

    paragraphs = [part.strip().replace("\n", " ") for part in args.text.read_text().split("\n\n") if part.strip()]
    if not paragraphs:
        parser.error("Narration text is empty")

    os.environ["COQUI_TOS_AGREED"] = "1"
    import torch
    from TTS.api import TTS

    torch.set_num_threads(min(4, os.cpu_count() or 1))
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="assurance-video-voice-") as temporary:
        work = Path(temporary)
        reference_wav = work / "reference.wav"
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-i", str(args.reference.resolve()), "-ac", "1", "-ar", "24000",
                "-af", "loudnorm=I=-23:TP=-2:LRA=7", "-c:a", "pcm_s16le",
                str(reference_wav),
            ],
            check=True,
        )

        model = TTS(MODEL).to("cpu")
        clips: list[Path] = []
        for index, paragraph in enumerate(paragraphs, start=1):
            clip = work / f"clip-{index:02d}.wav"
            print(f"Generating narration {index}/{len(paragraphs)}...", flush=True)
            model.tts_to_file(
                text=paragraph,
                speaker_wav=str(reference_wav),
                language="en",
                file_path=str(clip),
            )
            clips.append(clip)

        concat_file = work / "clips.txt"
        concat_file.write_text("".join(f"file '{clip}'\n" for clip in clips))
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0", "-i", str(concat_file),
                "-af", "loudnorm=I=-16:TP=-1.5:LRA=9", "-ar", "24000", "-ac", "1",
                str(args.output),
            ],
            check=True,
        )

    print(f"Rendered narration to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
