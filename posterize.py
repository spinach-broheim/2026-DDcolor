#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}

PALETTE_METHODS = {
    "mediancut": Image.Quantize.MEDIANCUT,
    "maxcoverage": Image.Quantize.MAXCOVERAGE,
    "octree": Image.Quantize.FASTOCTREE,
}

DITHERS = {
    "none": Image.Dither.NONE,
    "floydsteinberg": Image.Dither.FLOYDSTEINBERG,
}


def _median(im: Image.Image, size: int) -> Image.Image:
    if size < 3:
        return im
    if size % 2 == 0:
        size += 1
    return im.filter(ImageFilter.MedianFilter(size))


def _palette(im: Image.Image, colors: int, method: str, dither: str) -> Image.Image:
    q = im.quantize(
        colors=colors,
        method=PALETTE_METHODS[method],
        dither=DITHERS[dither],
    )
    return q.convert("RGB")


def _levels(im: Image.Image, bits: int) -> Image.Image:
    return ImageOps.posterize(im, bits)


def _chroma(im: Image.Image, bits: int, smooth: int) -> Image.Image:
    L, a, b = im.convert("LAB").split()
    a = _median(a, smooth)
    b = _median(b, smooth)
    return Image.merge(
        "LAB",
        (L, ImageOps.posterize(a, bits), ImageOps.posterize(b, bits)),
    ).convert("RGB")


def _variants(im: Image.Image, args: argparse.Namespace) -> list[tuple[str, Image.Image]]:
    out: list[tuple[str, Image.Image]] = []
    base = im
    if args.mode in ("palette", "all"):
        base = _median(im, args.smooth)
        out.append(
            (
                f"__palette-k{args.colors}",
                _palette(base, args.colors, args.palette_method, args.dither),
            )
        )
    if args.mode in ("levels", "all"):
        base = _median(im, args.smooth)
        out.append((f"__levels-b{args.levels_bits}", _levels(base, args.levels_bits)))
    if args.mode in ("chroma", "all"):
        out.append(
            (
                f"__chroma-b{args.chroma_bits}",
                _chroma(im, args.chroma_bits, args.smooth),
            )
        )
    return out


def _collect(folder: Path, recursive: bool) -> list[Path]:
    it = folder.rglob("*") if recursive else folder.iterdir()
    return sorted(
        p for p in it if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="posterize.py",
        description="Apply posterize / palette-quantize effects to every image in a folder.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python posterize.py -i input -o outputs/posterized\n"
            "  python posterize.py -i input -m palette -k 8\n"
            "  python posterize.py -i DDColor/assets/test_images -o trials -m chroma --smooth 5\n"
            "  python posterize.py -i input -m levels --levels-bits 3\n"
            "  python posterize.py -i input -m palette -k 32 --dither floydsteinberg\n"
        ),
    )
    p.add_argument("-i", "--input", required=True, help="folder with source images")
    p.add_argument(
        "-o",
        "--output",
        help="folder for results (default: sibling 'posterized' folder)",
    )
    p.add_argument(
        "-m",
        "--mode",
        choices=("all", "palette", "levels", "chroma"),
        default="all",
        help="effect to apply (default: all)",
    )
    p.add_argument(
        "-k",
        "--colors",
        type=int,
        default=16,
        help="palette size for -m palette (2-256, default: 16)",
    )
    p.add_argument(
        "--palette-method",
        choices=tuple(PALETTE_METHODS),
        default="maxcoverage",
        help="palette selection algorithm (default: maxcoverage)",
    )
    p.add_argument(
        "--dither",
        choices=tuple(DITHERS),
        default="none",
        help="dithering for palette mode (default: none)",
    )
    p.add_argument(
        "-b",
        "--levels-bits",
        type=int,
        default=4,
        help="bits per channel for -m levels (1-8, default: 4)",
    )
    p.add_argument(
        "--chroma-bits",
        type=int,
        default=2,
        help="bits per color channel for -m chroma (1-8, default: 2)",
    )
    p.add_argument(
        "-s",
        "--smooth",
        type=int,
        default=0,
        help="median filter size before palette/levels, and on color channels for chroma (0=off, default: 0)",
    )
    p.add_argument(
        "-q",
        "--quality",
        type=int,
        default=95,
        help="JPEG/WebP quality (default: 95)",
    )
    p.add_argument("-r", "--recursive", action="store_true", help="walk subfolders")
    return p


def validate(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if not 1 <= args.colors <= 256:
        parser.error("--colors must be between 1 and 256")
    if not 1 <= args.levels_bits <= 8:
        parser.error("--levels-bits must be between 1 and 8")
    if not 1 <= args.chroma_bits <= 8:
        parser.error("--chroma-bits must be between 1 and 8")
    if not 1 <= args.quality <= 100:
        parser.error("--quality must be between 1 and 100")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate(args, parser)

    src = Path(args.input).expanduser()
    if not src.is_dir():
        parser.error(f"input folder not found: {src}")

    out_dir = (
        Path(args.output).expanduser()
        if args.output
        else src.resolve().parent / "posterized"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    files = _collect(src, args.recursive)
    if not files:
        print(f"no images found in {src}", file=sys.stderr)
        return 1

    done = 0
    failed = 0
    for path in files:
        rel = path.relative_to(src)
        dest_dir = out_dir / rel.parent
        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            with Image.open(path) as raw:
                im = raw.convert("RGB")
                for suffix, result in _variants(im, args):
                    dest = dest_dir / f"{path.stem}{suffix}{path.suffix.lower()}"
                    result.save(dest, quality=args.quality)
                    print(f"{path.name} -> {dest.relative_to(out_dir)}")
            done += 1
        except Exception as exc:
            failed += 1
            print(f"skipped {path}: {exc}", file=sys.stderr)

    print(f"\n{done} image(s) processed, {failed} skipped, results in {out_dir}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
