#!/usr/bin/env python3
"""Build a v2 ASCII character pack (JSON) from a folder of .txt frames + pack.yaml.

    build_character_pack.py <src_dir> <out.json>

src_dir layout: every *.txt in a SUB-folder is a frame named by its stem (idle_01, …);
top-level .txt files are notes and ignored.
pack.yaml:
    name: heren
    fps: 8
    animations:
      idle:      { loop:  [idle_01, idle_02, …] }
      thinking:  { intro: [thinking_01, …], loop: [thinking_05, …] }
      key format: "activity" | "activity.mood" | "default"

Frames are trimmed of *common* blank margins (same trim for every frame, so relative
motion survives), then padded to one uniform cell. Whitespace inside is untouched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml


def load_frames(src: Path) -> dict[str, list[str]]:
    frames: dict[str, list[str]] = {}
    for p in sorted(src.rglob("*.txt")):
        if p.parent == src:
            continue  # top-level .txt are notes; frames live in sub-folders
        text = p.read_text(encoding="utf-8").replace("\r", "").replace("\t", "    ")
        lines = text.split("\n")
        while lines and lines[-1] == "":
            lines.pop()
        frames[p.stem] = lines
    return frames


def common_margins(frames: dict[str, list[str]]) -> tuple[int, int]:
    top = min((next((i for i, l in enumerate(ls) if l.strip()), len(ls)) for ls in frames.values()), default=0)
    left = min((min((len(l) - len(l.lstrip(" ")) for l in ls if l.strip()), default=0) for ls in frames.values()), default=0)
    return top, left


def main(src_dir: str, out_path: str) -> int:
    src = Path(src_dir)
    cfg = yaml.safe_load((src / "pack.yaml").read_text()) or {}
    raw = load_frames(src)
    if not raw:
        print("no .txt frames found", file=sys.stderr)
        return 2

    top, left = common_margins(raw)
    trimmed = {n: [l[left:] for l in ls[top:]] for n, ls in raw.items()}
    # drop trailing blank rows per frame, then size the cell to the largest drawing
    for ls in trimmed.values():
        while ls and not ls[-1].strip():
            ls.pop()
    rows = max(len(ls) for ls in trimmed.values())
    cols = max((len(l.rstrip()) for ls in trimmed.values() for l in ls), default=0)
    frames = {n: "\n".join((ls[r] if r < len(ls) else "")[:cols].ljust(cols) for r in range(rows))
              for n, ls in trimmed.items()}

    animations: dict[str, dict] = {}
    missing: list[str] = []
    for key, spec in (cfg.get("animations") or {}).items():
        entry: dict = {}
        for part in ("intro", "loop"):
            names = spec.get(part)
            if names:
                for n in names:
                    if n not in frames:
                        missing.append(f"{key}.{part}: {n}")
                entry[part] = list(names)
        if "fps" in spec:
            entry["fps"] = spec["fps"]
        animations[key] = entry
    if missing:
        print("unknown frame(s): " + "; ".join(missing), file=sys.stderr)
        return 1
    if "default" not in animations:
        first = animations.get("idle") or next(iter(animations.values()), None)
        animations["default"] = dict(first) if first else {"loop": [next(iter(frames))]}

    pack = {"name": cfg.get("name", src.name), "cell": {"cols": cols, "rows": rows},
            "fps": cfg.get("fps", 8), "frames": frames, "animations": animations}
    Path(out_path).write_text(json.dumps(pack, ensure_ascii=False))
    print(f"{out_path}: {len(frames)} frames, cell {cols}x{rows}, {len(animations)} animations "
          f"({Path(out_path).stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
