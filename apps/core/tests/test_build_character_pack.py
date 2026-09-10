"""build_character_pack.py converts a folder of ASCII .txt frames into a v2 asset pack JSON."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_character_pack.py"


def make_src(tmp_path: Path) -> Path:
    src = tmp_path / "art"
    (src / "idle").mkdir(parents=True)
    (src / "notice").mkdir()
    for i in range(1, 4):
        (src / "idle" / f"idle_{i:02}.txt").write_text(f"  I{i}  \n  ..  \n")          # 6 wide, 2 rows (+trailing nl)
    for i in range(1, 3):
        (src / "notice" / f"notice_{i:02}.txt").write_text(f" N{i}\n x\n y\n z\n")       # 3 wide, 4 rows
    (src / "pack.yaml").write_text("""
name: test
fps: 8
animations:
  idle: { loop: [idle_01, idle_02, idle_03, idle_02] }
  listening: { intro: [notice_01], loop: [notice_02] }
  thinking: { intro: [idle_01] }
""")
    return src


def test_builds_pack_with_named_frames_and_uniform_cell(tmp_path):
    src = make_src(tmp_path)
    out = tmp_path / "heren.json"
    r = subprocess.run([sys.executable, str(SCRIPT), str(src), str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    pack = json.loads(out.read_text())
    # common left margin is 1 (" N1"), so "  I1  " → " I1" (3 wide); rows = max = 4
    assert pack["cell"] == {"cols": 3, "rows": 4}
    assert pack["fps"] == 8
    assert set(pack["frames"]) == {"idle_01", "idle_02", "idle_03", "notice_01", "notice_02"}
    # every frame padded to the cell: rows x cols, inner whitespace preserved
    for name, f in pack["frames"].items():
        lines = f.split("\n")
        assert len(lines) == 4, name
        assert all(len(l) == 3 for l in lines), name
    assert pack["frames"]["idle_02"].split("\n") == [" I2", " ..", "   ", "   "]
    assert pack["frames"]["notice_01"].split("\n") == ["N1 ", "x  ", "y  ", "z  "]
    assert pack["animations"]["idle"] == {"loop": ["idle_01", "idle_02", "idle_03", "idle_02"]}
    assert pack["animations"]["listening"] == {"intro": ["notice_01"], "loop": ["notice_02"]}
    assert "default" in pack["animations"]                # always present so the UI never shows [ ? ]


def test_top_level_txt_files_are_notes_not_frames(tmp_path):
    src = make_src(tmp_path)
    (src / "NOTES.txt").write_text("x" * 300 + "\n" * 40)   # would blow the cell up if treated as a frame
    out = tmp_path / "o.json"
    r = subprocess.run([sys.executable, str(SCRIPT), str(src), str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    pack = json.loads(out.read_text())
    assert "NOTES" not in pack["frames"]
    assert pack["cell"] == {"cols": 3, "rows": 4}


def test_unknown_frame_reference_fails_the_build(tmp_path):
    src = make_src(tmp_path)
    (src / "pack.yaml").write_text("fps: 8\nanimations:\n  idle: { loop: [idle_01, ghost] }\n")
    r = subprocess.run([sys.executable, str(SCRIPT), str(src), str(tmp_path / "o.json")], capture_output=True, text=True)
    assert r.returncode != 0
    assert "ghost" in r.stderr


def test_frames_are_trimmed_of_common_blank_margins_but_keep_alignment(tmp_path):
    # two frames whose drawing sits at different offsets must keep their relative offsets
    src = tmp_path / "art"; (src / "a").mkdir(parents=True)
    (src / "a" / "a_01.txt").write_text("\n\n   X\n")
    (src / "a" / "a_02.txt").write_text("\n\n     X\n")
    (src / "pack.yaml").write_text("fps: 1\nanimations:\n  idle: { loop: [a_01, a_02] }\n")
    out = tmp_path / "o.json"
    assert subprocess.run([sys.executable, str(SCRIPT), str(src), str(out)], capture_output=True, text=True).returncode == 0
    pack = json.loads(out.read_text())
    # common blank top rows (2) and left cols (3) removed; relative 2-col shift preserved
    assert pack["cell"] == {"cols": 3, "rows": 1}
    assert pack["frames"]["a_01"] == "X  "
    assert pack["frames"]["a_02"] == "  X"
