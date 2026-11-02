# -*- coding: utf-8 -*-
"""按 总体使用规则.md 第 15 条组装最终成片。

只读 完成分段 里的 mp4，按 补齐生成用/原始帧数.txt 裁到原始帧数后按编号拼接。
只装前 44 段。002 全段没有人、不生成；004、007、017 按用户决定用原片、不做替换。这四段都直接用 补齐生成用 里的原片。
整条换成 APT 原片的音轨，成品只写到 完成分段/最终组装。
少一段就停，不跳过、不拿别的段补。
"""
import os
import subprocess
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
CLIPS = os.path.join(ROOT, "完成分段")
# 002 全段没有人；004/007/017 按用户决定用原片。这四段不走生成，组装时直接用原片。
SRC = os.path.join(ROOT, "补齐生成用")
TABLE = os.path.join(SRC, "原始帧数.txt")
SOURCE_SEGMENTS = {"002.mp4", "004.mp4", "007.mp4", "017.mp4"}


def source_path(name):
    """补齐生成用 里的源文件带帧数（如 004 39.mp4），按编号前缀找唯一一个。"""
    num = name[:3]
    hits = [f for f in os.listdir(SRC)
            if f.startswith(num + " ") and f.endswith(".mp4")]
    if len(hits) != 1:
        return None
    return os.path.join(SRC, hits[0])
AUDIO = os.path.join(ROOT, "原片音轨.m4a")
OUTDIR = os.path.join(CLIPS, "最终组装")
LAST = "044.mp4"
# 优先用交接包里自带的便携版，没有才退回 PATH
_BIN = os.path.join(ROOT, "ffmpeg")
FFMPEG = os.path.join(_BIN, "ffmpeg.exe")
FFPROBE = os.path.join(_BIN, "ffprobe.exe")
if not (os.path.isfile(FFMPEG) and os.path.isfile(FFPROBE)):
    FFMPEG, FFPROBE = "ffmpeg", "ffprobe"


def probe(path, *args):
    r = subprocess.run(
        [FFPROBE, "-v", "error", *args, path],
        capture_output=True, text=True, check=True)
    return r.stdout.strip()


def parse_table():
    rows = []
    with open(TABLE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("合计"):
                continue
            parts = line.split()
            if len(parts) < 2 or not parts[0].endswith(".mp4"):
                continue
            rows.append((parts[0], int(parts[1])))
            if parts[0] == LAST:
                break
    return rows


def main():
    rows = parse_table()
    missing = []
    for name, _ in rows:
        if name in SOURCE_SEGMENTS:
            path = source_path(name)
        else:
            path = os.path.join(CLIPS, name)
        if not path or not os.path.isfile(path):
            missing.append(name)
    if missing:
        print("停：完成分段里缺这些文件，不组装：")
        for n in missing:
            print(" ", n)
        sys.exit(1)

    os.makedirs(OUTDIR, exist_ok=True)
    work = os.path.join(OUTDIR, "_work")
    os.makedirs(work, exist_ok=True)

    sizes = []
    trimmed = []
    for name, keep in rows:
        if name in SOURCE_SEGMENTS:
            src = source_path(name)
        else:
            src = os.path.join(CLIPS, name)
        frames = int(probe(src, "-select_streams", "v:0",
                           "-count_frames", "-show_entries",
                           "stream=nb_read_frames", "-of", "csv=p=0"))
        if frames < keep:
            print(f"停：{name} 实际 {frames} 帧，少于原始帧数 {keep}，不补帧。")
            sys.exit(1)
        fps = probe(src, "-select_streams", "v:0",
                    "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0")
        dest = os.path.join(work, name)
        subprocess.run([
            FFMPEG, "-y", "-i", src,
            "-vf", f"trim=end_frame={keep},setpts=PTS-STARTPTS",
            "-an", "-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv420p",
            "-r", fps, dest
        ], check=True, capture_output=True)
        w, h = probe(dest, "-select_streams", "v:0",
                     "-show_entries", "stream=width,height",
                     "-of", "csv=p=0").split(",")
        sizes.append((int(w), int(h)))
        trimmed.append(dest)
        print(f"trim {name} -> {keep} frames {w}x{h}", flush=True)

    (tw, th), n = Counter(sizes).most_common(1)[0]
    print(f"majority size {tw}x{th} ({n}/{len(sizes)})", flush=True)

    scaled = []
    for src, size in zip(trimmed, sizes):
        if size == (tw, th):
            scaled.append(src)
            continue
        dest = src.replace(".mp4", "_s.mp4")
        subprocess.run([
            FFMPEG, "-y", "-i", src,
            "-vf", f"scale={tw}:{th}:flags=lanczos",
            "-an", "-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv420p",
            dest
        ], check=True, capture_output=True)
        scaled.append(dest)
        print(f"scale {os.path.basename(src)} {size[0]}x{size[1]} -> {tw}x{th}",
              flush=True)

    concat = os.path.join(work, "concat.txt")
    with open(concat, "w", encoding="utf-8") as f:
        for p in scaled:
            f.write("file '" + p.replace("\\", "/") + "'\n")
    silent = os.path.join(work, "silent.mp4")
    subprocess.run([
        FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", concat,
        "-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv420p",
        "-an", silent
    ], check=True, capture_output=True)

    # 原片是 24000/1001；分段按 24fps 生成，直接拼会让画面比音频快 0.1%。
    # 不增帧、不减帧，用 setpts 重新计时到原片帧率，再按新时长切音轨。
    target_fps = "24000/1001"
    cur_fps = probe(silent, "-select_streams", "v:0",
                    "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0")

    def fps_value(rate):
        num, den = rate.split("/")
        return float(num) / float(den)

    factor = fps_value(cur_fps) / fps_value(target_fps)
    if abs(factor - 1.0) > 1e-6:
        timed = os.path.join(work, "silent_timed.mp4")
        subprocess.run([
            FFMPEG, "-y", "-i", silent,
            "-vf", f"setpts=PTS*{factor:.9f}",
            "-r", target_fps, "-an",
            "-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv420p",
            timed
        ], check=True, capture_output=True)
        silent = timed
        print(f"retime {cur_fps} -> {target_fps} (x{factor:.6f})", flush=True)

    dur = float(probe(silent, "-show_entries", "format=duration", "-of", "csv=p=0"))
    out = os.path.join(OUTDIR, "APT_final_Made-by-wuwukasi.mp4")
    # LICENSE.txt 全文写进文件 metadata（description），只在文件内部，不显示在画面上
    lic_path = os.path.join(ROOT, "LICENSE.txt")
    lic_text = ""
    if os.path.isfile(lic_path):
        with open(lic_path, encoding="utf-8") as f:
            lic_text = f.read().strip()
    meta = [
        "-metadata", "title=APT_final (Made by wuwukasi)",
        "-metadata", "artist=wuwukasi",
        "-metadata", "comment=Made by wuwukasi",
        "-metadata", "copyright=Made by wuwukasi",
    ]
    if lic_text:
        meta += ["-metadata", "description=" + lic_text]
    subprocess.run([
        FFMPEG, "-y", "-i", silent, "-i", AUDIO,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        *meta,
        "-t", f"{dur:.6f}",
        out
    ], check=True, capture_output=True)
    print(f"wrote {out} ({dur:.3f}s)", flush=True)


if __name__ == "__main__":
    main()
