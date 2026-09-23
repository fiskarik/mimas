"""Render the original mimas liquid background; requires numpy, Pillow and FFmpeg.

Example: python scripts/render_mimas_fluid.py --ffmpeg /path/to/ffmpeg
All motion is periodic, so the 12-second video loops without a crossfade.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'frontend' / 'public' / 'media'
WIDTH, HEIGHT, FPS, SECONDS = 1280, 720, 24, 12


def frame(phase: float) -> np.ndarray:
    x, y = np.meshgrid(np.linspace(-2.3, 2.3, WIDTH, dtype=np.float32),
                       np.linspace(-1.3, 1.3, HEIGHT, dtype=np.float32))
    u, v = x.copy(), y.copy()
    # Domain-warped folds: fixed spatial detail with slowly orbiting phases.
    for frequency, amplitude, offset in [(1.15, .8, 0), (1.9, .44, 1.4), (3.2, .18, 2.8)]:
        a = u + amplitude * np.sin(v * frequency + np.cos(phase + offset) * .48)
        v = v + amplitude * np.cos(u * frequency + np.sin(phase + offset) * .48)
        u = a
    field = 2.0 * u + 1.6 * v + .55 * np.sin(2.8 * v - .35 * np.cos(phase))
    fold = (.5 + .5 * np.sin(field * 2.2))
    fine = (.5 + .5 * np.sin(field * 25 + .3 * np.sin(v * 19)))
    shimmer = np.power(fold, 12) * (.60 + .40 * fine)
    broad = np.power(.5 + .5 * np.sin(field + 1.3), 3)
    dark = np.array([3, 17, 16], dtype=np.float32)
    teal = np.array([35, 106, 89], dtype=np.float32)
    silver = np.array([179, 203, 165], dtype=np.float32)
    rgb = dark + broad[..., None] * (teal - dark)
    rgb += shimmer[..., None] * (silver - teal) * .95
    # A warm reflected light on the upper right, away from the headline.
    glow = np.exp(-((x - .95)**2 / .9 + (y + .6)**2 / .8))
    rgb += glow[..., None] * np.array([49, 39, 23]) * np.power(fold[..., None], 2)
    vignette = np.clip(1.1 - .13 * (x*x + y*y), .35, 1)
    rgb *= vignette[..., None]
    return np.uint8(np.clip(rgb, 0, 255))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--ffmpeg', default='ffmpeg')
    parser.add_argument('--poster-only', action='store_true')
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    Image.fromarray(frame(0)).save(OUTPUT / 'mimas-fluid-poster.webp', quality=88)
    if args.poster_only:
        return
    command = [args.ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
               '-f', 'rawvideo', '-vcodec', 'rawvideo', '-pix_fmt', 'rgb24',
               '-s', f'{WIDTH}x{HEIGHT}', '-r', str(FPS), '-i', '-', '-an',
               '-c:v', 'libx264', '-preset', 'slow', '-crf', '24',
               '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
               str(OUTPUT / 'mimas-fluid.mp4')]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    try:
        for index in range(FPS * SECONDS):
            process.stdin.write(frame(index / (FPS * SECONDS) * np.pi * 2).tobytes())
            if index % FPS == 0:
                print(f'Rendered {index // FPS}/{SECONDS} seconds', flush=True)
    finally:
        process.stdin.close()
    if process.wait():
        raise SystemExit('FFmpeg failed')
    print(f'Saved {OUTPUT / "mimas-fluid.mp4"}', flush=True)


if __name__ == '__main__':
    main()
