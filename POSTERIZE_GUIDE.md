# Posterize / Limited-Palette Colorization Notes

Notes on getting a poster-like, flat-color look out of DDColor (or any colorizer).

## Similar models

Posterization is usually a **post-process**, not something the colorizer does
itself — run any colorizer, then quantize (ImageMagick `-posterize N`, PIL
`Image.quantize`, or a palette/LUT step). Models that bake in a flat,
poster-like look:

- **DeOldify (Artistic model)** — more vivid/stylized color than DDColor,
  closer to hand-tinted postcards.
- **Diffusion + ControlNet colorization** (SD 1.5/XL with a colorization
  ControlNet, or "Palette" by Kumar et al.) — lets you prompt for poster/painting
  styles while colorizing.
- **Cartoonization / style-transfer models** — AnimeGANv2/v3, White-box
  Cartoonization, AdaIN — flatten into poster-like color bands.
- **Vectorization models** — VectorFusion, SVGDreamer, or commercial
  Vectorizer.ai — produce limited-palette poster art.
- **InstColorization / BigColor / ChromaGAN** — DDColor-style automatic
  colorizers, but none has a posterize knob either.

## What "apply a quantize step to `outputs/`" actually means

The colorized JPEGs in `outputs/` are full-color, continuous-tone images (often
thousands of distinct colors). Posterizing means **reducing the number of colors
or color levels** so the image breaks into flat bands. There are two distinct
operations that people call "posterize":

### 1. Bit-depth posterize (per-channel levels)

Every channel (R, G, B) is snapped to `2^bits` evenly spaced values. It is a
simple lookup table per channel, independent of image content.

- `bits = 3` → 8 levels per channel → up to 512 colors
- `bits = 2` → 4 levels per channel → up to 64 colors
- `bits = 1` → 2 levels per channel → 8 colors (very harsh)

Pros: fast, predictable, no color drift. Cons: can look "electric" because it
bands the whole gamut evenly instead of picking the colors that matter.

### 2. Palette quantization (K-color reduction)

The image is reduced to a chosen palette of `K` colors, picked from the image
itself (median cut, octree, k-means) or supplied explicitly. This is the classic
"poster" look: sky becomes 2–3 blues, skin becomes 3–4 tones, shadows collapse
into one flat block.

- `K = 8–16` → strong poster / screen-print feel
- `K = 24–48` → flat illustration, still photographic
- `K = 64–128` → subtle banding only

Pros: keeps the image's own dominant colors, much better than bit-depth
posterize for photos. Cons: palette can drift between images (fine for one
photo, inconsistent for a set), and dithering choices matter a lot.

### 3. Chroma-only posterize (keep detail, flatten color)

Convert to CIELAB, posterize only the `a` and `b` (color) channels, and leave
`L` (luminance) untouched. The photo keeps all its sharpness and tonal detail
while its colors flatten into poster bands. This is usually the nicest result
for portraits and old photos where you don't want to lose facial structure.

## Verified commands

Tested locally with PIL 12.3.0 and ImageMagick 7 on `DDColor/assets/test_images/`.

### ImageMagick (fastest, no code)

```sh
# per-channel levels: 6 levels per channel
magick input.jpg -posterize 6 posterized.jpg

# "N total colors" palette, no dithering (clean poster bands)
magick input.jpg -colors 16 +dither posterized.jpg

# same, with Floyd-Steinberg dithering (smoother gradients, grainy)
magick input.jpg -colors 16 -dither FloydSteinberg posterized.jpg
```

Note: `-posterize` takes **levels per channel**, `-colors` takes **total colors**.
They are not the same scale.

### Pillow (scriptable, per-image control)

```python
from PIL import Image, ImageFilter, ImageOps

im = Image.open("outputs/photo.jpg").convert("RGB")

# A) bit-depth posterize: 3 bits = 8 levels per channel
ImageOps.posterize(im, 3).save("posterized_channel.jpg", quality=95)

# B) palette quantization: 16 colors, median cut, no dither
q = im.quantize(colors=16, method=Image.Quantize.MEDIANCUT,
                dither=Image.Dither.NONE)
q.convert("RGB").save("posterized_palette.jpg", quality=95)

# C) chroma-only posterize: flatten color, keep luminance detail
lab = im.convert("LAB")
L, a, b = lab.split()
a = ImageOps.posterize(a, 2)
b = ImageOps.posterize(b, 2)
Image.merge("LAB", (L, a, b)).convert("RGB").save("posterized_chroma.jpg",
                                                  quality=95)
```

`Image.Quantize` options: `MEDIANCUT` (default, good general purpose),
`MAXCOVERAGE` (biased to large flat areas — very poster-like), `FASTOCTREE`
(quick, slightly worse), `LIBIMAGEQUANT` (highest quality but needs the optional
`libimagequant` dependency).

### ffmpeg (batch/video, palette file)

```sh
ffmpeg -i input.jpg -vf "palettegen=max_colors=16" palette.png
ffmpeg -i input.jpg -i palette.png -vf "paletteuse=dither=none" posterized.jpg
```

Useful if you ever posterize video rather than stills.

## Practical recipe for a good poster look

1. **Smooth first.** Colorizers (DDColor included) leave low-level color
   speckle and muddy patches. Posterizing amplifies it into confetti. Pre-filter
   with a median or bilateral filter:
   `im.filter(ImageFilter.MedianFilter(5))` or
   `cv2.bilateralFilter(img, 9, 75, 75)`. A small bilateral pass keeps edges
   crisp while flattening the noise.
2. **Quantize to a palette**, not per-channel, if you want a real poster look:
   `quantize(colors=12–24, method=Image.Quantize.MAXCOVERAGE, dither=NONE)`.
3. **Decide on dithering.** `NONE` = clean, graphic, screen-print bands.
   `FLOYDSTEINBERG` = smoother gradients but visible grain. For posters, `NONE`.
4. **Optionally posterize the chroma only** (recipe C) when the subject has
   important detail you don't want banded.
5. **Save at full resolution as PNG or high-quality JPEG** (`quality=95`).
   Posterized images compress very well and can look bad if re-compressed hard.

## Gotchas

- Always write to a **new folder** (e.g. `outputs/posterized/`); never
  overwrite `outputs/`, so you can re-run with different parameters.
- Quantize **before** resizing down. Downscaling a posterized image re-blends
  the flat bands and undoes the effect.
- BMP/PNG avoid JPEG ringing around hard color edges; JPEG at `quality=95` is
  usually fine but hard edges can show mosquito noise.
- A fixed custom palette (`quantize(palette=pal_img)`) gives a consistent look
  across a photo set; per-image adaptive palettes shift from photo to photo.
- If the source photo is still grayscale, the colorizer output is what gets
  posterized; posterizing the original B&W only gives you a grayscale poster.

## Using `posterize.py`

A small batch script lives at the repo root: `posterize.py`. It requires only
Pillow, which is already in `.venv`, so no ImageMagick needed.

Run it with the venv Python (or activate the venv first):

```sh
cd /Users/aaronpanych/Sync/2026-DDcolor
.venv/bin/python posterize.py -i <input-folder> [-o <output-folder>]
```

It never modifies the source folder; results go to `-o`, or to a sibling
`posterized/` folder when `-o` is omitted. File names get a suffix describing
the effect, e.g. `photo__palette-k16.jpg`, `photo__levels-b4.jpg`,
`photo__chroma-b2.jpg`. Input extension and resolution are preserved.

### Common runs

```sh
# all three effects on every photo in input/
.venv/bin/python posterize.py -i input -o outputs/posterized

# only palette, strong poster look with 8 colors
.venv/bin/python posterize.py -i input -m palette -k 8

# smoother palette result (pre-filter) and Floyd-Steinberg dithering
.venv/bin/python posterize.py -i input -m palette -k 32 --dither floydsteinberg -s 5

# harsh bit-depth posterize: 3 bits per channel
.venv/bin/python posterize.py -i input -m levels -b 3

# chroma-only: keep luminance detail, flatten color
.venv/bin/python posterize.py -i input -m chroma --chroma-bits 2 -s 5

# walk subfolders, use a different palette method
.venv/bin/python posterize.py -i input -o trials -r --palette-method mediancut
```

### Options

| Flag | Default | Meaning |
| --- | --- | --- |
| `-i, --input` | required | Folder containing source images (`.jpg .jpeg .png .webp .bmp .tif .tiff`) |
| `-o, --output` | sibling `posterized/` | Where results are written (created if missing) |
| `-m, --mode` | `all` | `all`, `palette`, `levels`, or `chroma` |
| `-k, --colors` | `16` | Palette size for `palette` mode, 2–256 |
| `--palette-method` | `maxcoverage` | `maxcoverage` (flat poster look), `mediancut` (balanced), `octree` (fast) |
| `--dither` | `none` | `none` for clean bands, `floydsteinberg` for smoother gradients |
| `-b, --levels-bits` | `4` | Bits per channel for `levels` mode; 3 = 8 levels, 2 = 4 levels |
| `--chroma-bits` | `2` | Bits per color channel for `chroma` mode |
| `-s, --smooth` | `0` | Median filter size before quantizing (0 = off; try 3–5); in `chroma` mode only the color channels are smoothed |
| `-q, --quality` | `95` | JPEG/WebP quality |
| `-r, --recursive` | off | Also process images in subfolders |

`chroma` mode ignores `-k`, `--palette-method`, and `--dither`.

### Trying it now

`input/` is currently empty, so use any of the bundled test photos:

```sh
.venv/bin/python posterize.py -i DDColor/assets/test_images -o posterize_trials
open posterize_trials
```

Those test images are black-and-white, so the results show the poster effect in
grayscale. For color posterization, point `-i` at colorized photos (e.g.
`outputs/`) or any color image.

### Suggested workflow for this repo

```sh
cd DDColor && source ../.venv/bin/activate

# 1. colorize
python scripts/infer.py \
  --model_path ./pretrain/modelscope/models/damo--cv_ddcolor_image-colorization/snapshots/master/pytorch_model.pt \
  --input ../input --output ../outputs

cd ..

# 2. posterize a copy (originals stay untouched)
.venv/bin/python posterize.py -i outputs -o outputs/posterized -m all
```
