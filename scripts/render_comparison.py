"""Render a transparent analysis overlay from existing per-frame detections.

No detector is loaded or rerun. Faces and bodies remain visible: this is an
analysis visualization, not a privacy mask. The original evaluator output is
read-only. H.264 output preserves decoded frame order, dimensions and nominal
FPS so a comparison UI can synchronize the original and overlay videos.
"""
from __future__ import annotations

import argparse
from collections import deque
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import time

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]

MINT = (178, 239, 111)
CYAN = (239, 208, 104)
TEXT = (246, 248, 244)
INK = (25, 32, 28)


def published_input_name(path):
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.name


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def find_ffmpeg(explicit):
    if explicit:
        candidate = explicit
    else:
        candidate = shutil.which("ffmpeg")
        if candidate is None:
            try:
                import imageio_ffmpeg
                candidate = imageio_ffmpeg.get_ffmpeg_exe()
            except ImportError as exc:
                raise RuntimeError("Supply --ffmpeg or install imageio-ffmpeg") from exc
    if not Path(candidate).is_file():
        raise ValueError("FFmpeg executable does not exist")
    return str(Path(candidate).resolve())


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--evaluation", help="Directory containing tracks.jsonl and summary.json")
    parser.add_argument("--tracks", help="Override tracks.jsonl path")
    parser.add_argument("--summary", help="Override evaluator summary.json path")
    parser.add_argument("--output", required=True, help="New output directory")
    parser.add_argument("--opacity", type=float, default=0.12)
    parser.add_argument("--trail-frames", type=int, default=18)
    parser.add_argument("--ffmpeg", help="FFmpeg executable, auto-discovered by default")
    args = parser.parse_args()
    if not 0 <= args.opacity <= 1 or not math.isfinite(args.opacity):
        parser.error("--opacity must be finite and between zero and one")
    if args.trail_frames < 1:
        parser.error("--trail-frames must be positive")
    evaluation = Path(args.evaluation) if args.evaluation else None
    if not args.tracks and evaluation:
        args.tracks = str(evaluation / "tracks.jsonl")
    if not args.summary and evaluation:
        args.summary = str(evaluation / "summary.json")
    if not args.tracks or not args.summary:
        parser.error("Supply --evaluation or both --tracks and --summary")
    for value in (args.source, args.tracks, args.summary):
        if not Path(value).is_file():
            parser.error(f"Input file does not exist: {value}")
    return args


def label(frame, text, x, y, color=TEXT, scale=0.48):
    """Small opaque label background only; no full person obfuscation."""
    h, w = frame.shape[:2]
    (tw, th), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
    x = int(np.clip(x, 2, max(2, w - tw - 12)))
    y = int(np.clip(y, th + 10, max(th + 10, h - baseline - 5)))
    cv2.rectangle(frame, (x - 5, y - th - 5), (x + tw + 5, y + baseline + 4), INK, -1)
    cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def validate_telemetry(rows, summary, fps, size):
    if len(rows) != summary.get("processed_frames") or summary.get("status") != "completed":
        raise ValueError("Comparison requires a completed evaluation and matching telemetry row count")
    if summary.get("input_size_px") != list(size):
        raise ValueError("Source dimensions differ from evaluator dimensions")
    if not math.isclose(summary["source_fps"], fps, abs_tol=1e-6):
        raise ValueError("Source FPS differs from evaluator FPS")
    maximum_timestamp_error = 0.0
    for index, row in enumerate(rows):
        if row.get("frame") != index:
            raise ValueError(f"Telemetry must contain every source frame in order; mismatch at {index}")
        timestamp = float(row["timestamp"])
        error = abs(timestamp - index / fps)
        if not math.isfinite(timestamp) or error > 1e-6:
            raise ValueError(f"Telemetry timestamp is not aligned to source frame {index}")
        maximum_timestamp_error = max(maximum_timestamp_error, error)
        detections = row["detections"]
        if row["detection_count"] != len(detections):
            raise ValueError(f"Detection count mismatch at frame {index}")
        ids = set()
        for detection in detections:
            box = np.asarray(detection["xyxy"], dtype=float)
            if box.shape != (4,) or not np.isfinite(box).all() or box[2] <= box[0] or box[3] <= box[1]:
                raise ValueError(f"Invalid detection box at frame {index}")
            foot = np.array([(box[0] + box[2]) / 2, box[3]])
            if not np.allclose(detection["footpoint_px"], foot, atol=1e-5, rtol=0):
                raise ValueError(f"Recorded footpoint differs from detection box at frame {index}")
            if detection["track_id"] is not None:
                ids.add(detection["track_id"])
        if row["confirmed_track_count"] != len(ids):
            raise ValueError(f"Confirmed ID count mismatch at frame {index}")
    if rows:
        for key in ("total_in", "total_out", "raw_occupancy"):
            if rows[-1]["stats"][key] != summary[key]:
                raise ValueError(f"Final telemetry and summary differ for {key}")
    return maximum_timestamp_error


def overlay_frame(frame, row, cfg, trails, opacity, trail_frames):
    height, width = frame.shape[:2]
    scale = max(0.36, min(width / 1280, height / 720) * 0.48)
    radius = max(2, round(height / 240))
    index = row["frame"]
    trails = {key: value for key, value in trails.items()
              if index - value["last"] <= cfg.get("max_gap_frames", 15)}
    # Blend the actual box interiors once; the source body remains visible.
    fill = frame.copy()
    for detection in row["detections"]:
        x1, y1, x2, y2 = detection["xyxy"]
        left, top = max(0, math.floor(x1)), max(0, math.floor(y1))
        right, bottom = min(width, math.ceil(x2)), min(height, math.ceil(y2))
        if right <= left or bottom <= top:
            continue
        track_id = detection["track_id"]
        color = MINT if track_id is not None and track_id % 2 == 0 else CYAN
        fill[top:bottom, left:right] = color
    canvas = cv2.addWeighted(frame, 1 - opacity, fill, opacity, 0)
    start, end = np.asarray(cfg["line"], dtype=float) * [width, height]
    a, b = tuple(np.rint(start).astype(int)), tuple(np.rint(end).astype(int))
    cv2.line(canvas, a, b, MINT, 1, cv2.LINE_AA)
    for point in (a, b):
        cv2.circle(canvas, point, radius, MINT, 1, cv2.LINE_AA)
    delta = end - start
    normal = cfg.get("in_side", 1) * np.array([-delta[1], delta[0]]) / np.linalg.norm(delta)
    middle = (start + end) / 2
    arrow_start = tuple(np.rint(middle - normal * 14).astype(int))
    arrow_end = tuple(np.rint(middle + normal * 21).astype(int))
    cv2.arrowedLine(canvas, arrow_start, arrow_end, MINT, 1, cv2.LINE_AA, tipLength=0.27)
    label(canvas, "IN", arrow_end[0] + 8, arrow_end[1] + 4, MINT, scale)
    for detection in row["detections"]:
        x1, y1, x2, y2 = detection["xyxy"]
        p1 = tuple(np.rint(np.clip([x1, y1], [0, 0], [width - 1, height - 1])).astype(int))
        p2 = tuple(np.rint(np.clip([x2, y2], [0, 0], [width - 1, height - 1])).astype(int))
        track_id = detection["track_id"]
        color = MINT if track_id is not None and track_id % 2 == 0 else CYAN
        foot = tuple(np.rint(np.clip(detection["footpoint_px"], [0, 0], [width - 1, height - 1])).astype(int))
        if track_id is not None:
            trail = trails.setdefault(track_id, {"last": index, "points": deque(maxlen=trail_frames)})
            trail["points"].append(foot)
            trail["last"] = index
            if len(trail["points"]) > 1:
                cv2.polylines(canvas, [np.asarray(trail["points"], dtype=np.int32)], False, color, 1, cv2.LINE_AA)
        cv2.rectangle(canvas, p1, p2, color, 1, cv2.LINE_AA)
        cv2.circle(canvas, foot, radius, color, -1, cv2.LINE_AA)
        label(canvas, f"ID {track_id}" if track_id is not None else "PERSON",
              p1[0] + 4, p1[1] - 8, color, scale)
    stats = row["stats"]
    label(canvas, f"TRACKED ANALYSIS   IN {stats['total_in']}   OUT {stats['total_out']}", 22, 30, TEXT, scale)
    label(canvas, f"{row['timestamp']:05.2f}s   FRAME {index:03d}   DETECTED {row['detection_count']}",
          22, 56, TEXT, scale * 0.88)
    return canvas, trails


def run(args):
    tick = time.perf_counter()
    source_path, summary_path, tracks_path = map(Path, (args.source, args.summary, args.tracks))
    summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    rows = [json.loads(line) for line in tracks_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    source_hash = sha256(source_path)
    expected_hash = summary.get("reproducibility", {}).get("source_sha256")
    if not expected_hash or source_hash != expected_hash:
        raise ValueError("Source SHA256 does not match evaluated source; refusing unaligned comparison")
    ffmpeg = find_ffmpeg(args.ffmpeg)
    capture = cv2.VideoCapture(str(source_path.resolve()))
    if not capture.isOpened():
        raise RuntimeError("Cannot open source video")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    size = (round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    if not math.isfinite(fps) or fps <= 0 or min(size) <= 0 or any(v % 2 for v in size):
        capture.release()
        raise ValueError("H.264 yuv420p comparison requires finite FPS and positive even source dimensions")
    timestamp_error = validate_telemetry(rows, summary, fps, size)
    fps_fraction = str(Fraction(fps).limit_denominator(100000))
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    output_path = out / "overlay.mp4"
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
        "-f", "rawvideo", "-pixel_format", "bgr24", "-video_size", f"{size[0]}x{size[1]}",
        "-framerate", fps_fraction, "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "medium",
        "-crf", "18", "-pix_fmt", "yuv420p", "-fps_mode", "passthrough", "-movflags", "+faststart",
        str(output_path)]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    trails, processed, preview = {}, 0, None
    # File-backed stderr cannot deadlock the rawvideo pipe during an encoder error.
    with (out / "encoder.log").open("wb") as encoder_log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                   stderr=encoder_log, creationflags=flags)
        try:
            for row in rows:
                ok, frame = capture.read()
                if not ok:
                    raise RuntimeError(f"Source ended before telemetry frame {row['frame']}")
                if (frame.shape[1], frame.shape[0]) != size:
                    raise RuntimeError(f"Source resolution changed at frame {row['frame']}")
                canvas, trails = overlay_frame(frame, row, summary["config"], trails,
                                                args.opacity, args.trail_frames)
                process.stdin.write(canvas.tobytes())
                processed += 1
                if row["events"] or preview is None or row["confirmed_track_count"] > preview[0]:
                    preview = (row["confirmed_track_count"], canvas.copy(), row["frame"])
                if processed % 120 == 0:
                    print(f"Rendered {processed}/{len(rows)} aligned frames", flush=True)
            if capture.read()[0]:
                raise RuntimeError("Source has additional frames missing from telemetry")
            process.stdin.close()
            if process.wait(timeout=60) != 0:
                raise RuntimeError("H.264 encoding failed; inspect encoder.log")
        except BaseException:
            process.kill()
            process.wait()
            raise
        finally:
            capture.release()
    render_seconds = time.perf_counter() - tick
    # Decode every encoded frame to verify count, dimensions, and playback FPS.
    encoded = cv2.VideoCapture(str(output_path))
    if not encoded.isOpened():
        raise RuntimeError("Encoded comparison cannot be decoded")
    output_fps = float(encoded.get(cv2.CAP_PROP_FPS))
    decoded_frames = 0
    try:
        while True:
            ok, frame = encoded.read()
            if not ok:
                break
            if (frame.shape[1], frame.shape[0]) != size:
                raise RuntimeError("Encoded frame dimensions changed")
            decoded_frames += 1
    finally:
        encoded.release()
    if decoded_frames != processed or not math.isclose(output_fps, fps, abs_tol=1e-6):
        raise RuntimeError("Encoded comparison frame count or FPS differs from source")
    probe = subprocess.run([ffmpeg, "-hide_banner", "-i", str(output_path), "-f", "null", "-"],
                           capture_output=True, text=True, creationflags=flags, timeout=60)
    if probe.returncode or not re.search(r"Video:\s+h264\b.*yuv420p", probe.stderr):
        raise RuntimeError("Encoded comparison is not verified decodable H.264 yuv420p")
    if preview is None or not cv2.imwrite(str(out / "preview.jpg"), preview[1]):
        raise RuntimeError("Cannot save overlay preview")
    metadata = {
        "status": "completed", "source_path": published_input_name(source_path),
        "source_sha256": source_hash, "tracks_sha256": sha256(tracks_path),
        "evaluation_summary_sha256": sha256(summary_path), "renderer_sha256": sha256(__file__),
        "overlay_sha256": sha256(output_path), "overlay": "overlay.mp4",
        "input_size_px": list(size), "output_size_px": list(size),
        "source_fps": fps, "output_fps": output_fps, "fps_rational": fps_fraction,
        "source_decoded_frames": processed, "telemetry_frames": len(rows),
        "output_decoded_frames": decoded_frames, "duration_seconds": processed / fps,
        "frame_alignment_verified": True, "telemetry_frame_indices": "contiguous from zero",
        "maximum_telemetry_timestamp_error_seconds": timestamp_error,
        "codec": "H.264", "pixel_format": "yuv420p", "faststart": True,
        "fill_opacity": args.opacity, "trail_frames": args.trail_frames,
        "privacy_protection": False, "people_remain_visible": True, "detector_rerun": False,
        "counting_config": summary["config"], "total_in": summary["total_in"],
        "total_out": summary["total_out"], "preview_frame": preview[2],
        "render_wall_seconds": round(render_seconds, 6),
        "total_wall_seconds_including_verification": round(time.perf_counter() - tick, 6),
        "notes": [
            "Transparent boxes are an analysis overlay, not a privacy mask; faces and bodies remain visible.",
            "Every output frame uses the corresponding source frame and existing measured detections; no detector was rerun.",
            "Source SHA256, each telemetry index and timestamp, complete source/output decoding, dimensions and FPS were checked.",
            "No frames were intentionally skipped, duplicated or interpolated. Input and output use the evaluator's nominal frame-index/FPS timeline.",
            "The original solid-masked evaluation and app defaults were not modified.",
            "Audio is omitted so a comparison UI can play the original source audio once.",
        ],
    }
    (out / "summary.json").write_text(json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2))
    return metadata


if __name__ == "__main__":
    run(parse_args())
