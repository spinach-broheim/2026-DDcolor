#!/usr/bin/env python3
"""colorize_clip.py — colorize a black-and-white video clip with DDColor, in
one command.

    python3 ~/Sync/2026-DDcolor/colorize_clip.py TAMX.mp4 --start 00:42:04 --end 00:42:17

Cuts the part you ask for (or uses the whole file), colorizes every frame
with DDColor on the M1 graphics chip (falls back to the CPU if needed), puts
the original sound back, and makes a side-by-side comparison video. Prints
how long it took and an estimate for a whole film.

Output, next to the input video (the colour settings go into the name, so
different looks don't overwrite each other):
    <name>_<start>-<end>.mp4                    the original clip
    <name>_<start>-<end>_color[_look].mp4       colorized
    <name>_<start>-<end>_compare[_look].mp4     original | colour, side by side

Options:
    --start / --end     part of the video (hh:mm:ss, fractions ok); default: whole file
    --variant NAME      the model's colour look:
                          modelscope  (default; your downloaded model) fairly vivid / warm
                          paper       usually more natural and muted
                          artistic    the most vivid
                          tiny        small + fast, similar to paper
                        (paper / artistic / tiny download once from Hugging Face)
    --saturation 0.8    overall colour strength (1 = as the model makes it)
    --less-red 0.3      pull reds / magentas towards neutral (0 = off … 1 = no red)
    --size 256          smaller model input (faster / less memory; default 512)
    --cpu               don't use the M1 graphics chip
    --no-compare        skip the side-by-side video

Example (calmer, less red):
    python3 colorize_clip.py TAMX.mp4 --start 00:42:04 --end 00:42:17 \
        --variant paper --saturation 0.8 --less-red 0.3

Uses the DDColor install next to this script (./DDColor) and its Python
environment (./.venv); run it with any python3 — it switches to that
environment itself.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DDCOLOR = HERE / "DDColor"
VENV_PY = HERE / ".venv" / "bin" / "python"
LARGE_MODEL = (DDCOLOR / "pretrain" / "modelscope" / "models" /
               "damo--cv_ddcolor_image-colorization" / "snapshots" / "master" /
               "pytorch_model.pt")


def run(cmd: list[str]) -> None:
    """Run a command quietly; show its output only if it fails."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"\n✗ command failed: {' '.join(cmd)}\n{proc.stderr[-2000:]}")


def probe(path: Path, entry: str, stream: str = "v:0") -> str:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries", entry,
         "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout
    return out.strip().splitlines()[0] if out.strip() else ""


def stamp(t: str | None) -> str:
    return (t or "").replace(":", "").replace(".", "_") or "full"


def fmt_dur(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m" if h else (f"{m}m {s:02d}s" if m else f"{s}s")


def main() -> None:
    ap = argparse.ArgumentParser(description="Colorize a B&W video clip with DDColor.")
    ap.add_argument("video", help="input video file")
    ap.add_argument("--start", help="start time, e.g. 00:42:04")
    ap.add_argument("--end", help="end time, e.g. 00:42:17")
    ap.add_argument("--variant", choices=["modelscope", "paper", "artistic", "tiny"],
                    default="modelscope", help="model colour look (default modelscope)")
    ap.add_argument("--model", choices=["large", "tiny"], help=argparse.SUPPRESS)  # old name
    ap.add_argument("--saturation", type=float, default=1.0,
                    help="overall colour strength, e.g. 0.8 (default 1)")
    ap.add_argument("--less-red", type=float, default=0.0,
                    help="pull reds towards neutral, 0–1 (default 0)")
    ap.add_argument("--size", type=int, default=512, help="model input size (default 512)")
    ap.add_argument("--cpu", action="store_true", help="don't use the M1 graphics chip")
    ap.add_argument("--no-compare", action="store_true", help="skip the side-by-side video")
    args = ap.parse_args()
    if args.model == "tiny":                       # old --model tiny
        args.variant = "tiny"
    if not 0 <= args.less_red <= 1:
        sys.exit("✗ --less-red must be between 0 and 1")
    if args.saturation < 0:
        sys.exit("✗ --saturation must be 0 or more")

    # switch to the DDColor environment (torch, opencv) if we're not in it
    try:
        import torch  # noqa: F401
        import cv2  # noqa: F401
    except ImportError:
        if not VENV_PY.exists():
            sys.exit(f"✗ DDColor's Python environment not found at {VENV_PY}")
        os.execv(str(VENV_PY), [str(VENV_PY), *sys.argv])

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"✗ {tool} not found (brew install ffmpeg)")

    src = Path(args.video).expanduser().resolve()
    if not src.is_file():
        sys.exit(f"✗ video not found: {src}")
    tag = f"{stamp(args.start)}-{stamp(args.end)}" if (args.start or args.end) else "full"
    base = src.parent / f"{src.stem}_{tag}"
    look = "".join([
        "" if args.variant == "modelscope" else f"_{args.variant}",
        "" if args.saturation == 1 else f"_sat{args.saturation:g}",
        "" if not args.less_red else f"_red{args.less_red:g}",
        "" if args.size == 512 else f"_size{args.size}",
    ])
    clip, color, compare = (Path(f"{base}.mp4"), Path(f"{base}_color{look}.mp4"),
                            Path(f"{base}_compare{look}.mp4"))

    t0 = time.time()

    # 1. the clip
    print(f"1/4 cutting the clip → {clip.name}")
    cut = ["ffmpeg", "-y"]
    if args.start:
        cut += ["-ss", args.start]
    if args.end:
        cut += ["-to", args.end]
    cut += ["-i", str(src), "-c:v", "libx264", "-crf", "18", "-c:a", "aac", str(clip)]
    run(cut)
    fps = probe(clip, "stream=r_frame_rate") or "24"
    width, height = (int(v) for v in probe(clip, "stream=width,height").split(","))
    clip_seconds = float(probe(clip, "format=duration", stream="v:0") or 0) or 1.0
    film_seconds = float(probe(src, "format=duration", stream="v:0") or 0)

    # 2. the model
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    import cv2
    import torch
    sys.path.insert(0, str(DDCOLOR))
    from ddcolor import ColorizationPipeline, DDColor, build_ddcolor_model

    import numpy as np

    def load(device):
        if args.variant == "modelscope" and LARGE_MODEL.exists():
            model = build_ddcolor_model(DDColor, model_path=str(LARGE_MODEL),
                                        input_size=args.size, model_size="large",
                                        device=device)
        else:                                       # from Hugging Face (downloads once)
            from huggingface_hub import PyTorchModelHubMixin

            class DDColorHF(DDColor, PyTorchModelHubMixin):
                def __init__(self, config=None, **kwargs):
                    if isinstance(config, dict):
                        kwargs = {**config, **kwargs}
                    super().__init__(**kwargs)
            name = {"tiny": "ddcolor_paper_tiny"}.get(args.variant, f"ddcolor_{args.variant}")
            model = DDColorHF.from_pretrained(f"piddnad/{name}").to(device).eval()
        return ColorizationPipeline(model, input_size=args.size, device=device)

    def tone(img):
        """--saturation / --less-red on a colorized frame (Lab colour space:
        a = green↔red, b = blue↔yellow; brightness untouched)."""
        if args.saturation == 1 and not args.less_red:
            return img
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
        a, b = lab[..., 1] - 128, lab[..., 2] - 128
        if args.less_red:
            a = np.where(a > 0, a * (1 - args.less_red), a)   # only the red side
        a, b = a * args.saturation, b * args.saturation
        lab[..., 1] = np.clip(a + 128, 0, 255)
        lab[..., 2] = np.clip(b + 128, 0, 255)
        return cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2BGR)

    use_mps = not args.cpu and torch.backends.mps.is_available()
    device = torch.device("mps" if use_mps else "cpu")
    tweaks = ", ".join(t for t in (
        f"saturation {args.saturation:g}" if args.saturation != 1 else "",
        f"less red {args.less_red:g}" if args.less_red else "") if t)
    print(f"2/4 loading DDColor ({args.variant}, input {args.size}"
          f"{', ' + tweaks if tweaks else ''}) on "
          f"{'the M1 graphics chip' if use_mps else 'the CPU'}")
    colorizer = load(device)

    # 3. colorize frame by frame, straight into the video (+ original sound)
    cap = cv2.VideoCapture(str(clip))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    print(f"3/4 colorizing {total} frames ({clip_seconds:.1f} s at {fps} fps) → {color.name}")
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}",
         "-framerate", fps, "-i", "-",
         "-i", str(clip), "-map", "0:v", "-map", "1:a?",
         "-vf", "deflicker", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "copy", "-shortest", str(color)],
        stdin=subprocess.PIPE)
    t_color = time.time()
    done = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        try:
            out = colorizer.process(frame)
        except Exception as exc:                    # noqa: BLE001
            if device.type != "mps" or done:
                raise
            print(f"   graphics chip failed ({exc.__class__.__name__}); switching to the CPU")
            device = torch.device("cpu")
            colorizer = load(device)
            out = colorizer.process(frame)
        enc.stdin.write(tone(out).tobytes())
        done += 1
        if done % 10 == 0 or done == total:
            spent = time.time() - t_color
            left = spent / done * max(0, total - done)
            print(f"\r   {done}/{total} frames · {spent / done:.2f} s/frame · "
                  f"~{fmt_dur(left)} left   ", end="", flush=True)
    print()
    cap.release()
    enc.stdin.close()
    if enc.wait() != 0:
        sys.exit("✗ ffmpeg failed while writing the colour video")
    color_seconds = time.time() - t_color

    # 4. side by side
    if not args.no_compare:
        print(f"4/4 side-by-side → {compare.name}")
        run(["ffmpeg", "-y", "-i", str(clip), "-i", str(color), "-filter_complex",
             "[0:v]scale=640:-2[a];[1:v]scale=640:-2[b];[a][b]hstack=2",
             "-map", "1:a?", "-c:v", "libx264", "-crf", "20", "-c:a", "copy", str(compare)])
    else:
        print("4/4 side-by-side skipped")

    per_film_second = color_seconds / clip_seconds
    print("\n✓ done in", fmt_dur(time.time() - t0))
    print(f"  colorizing: {fmt_dur(color_seconds)} for {clip_seconds:.1f} s of film "
          f"({per_film_second:.1f} s per second of film)")
    print(f"  ≈ {fmt_dur(per_film_second * 60)} per minute of film · "
          f"≈ {fmt_dur(per_film_second * 90 * 60)} for a 90-minute film", end="")
    if film_seconds > 0:
        print(f" · ≈ {fmt_dur(per_film_second * film_seconds)} for this whole film "
              f"({fmt_dur(film_seconds)})")
    else:
        print()
    print(f"  files: {clip.name}, {color.name}" + ("" if args.no_compare else f", {compare.name}"))
    print(f"  open \"{compare if not args.no_compare else color}\"")


if __name__ == "__main__":
    main()
