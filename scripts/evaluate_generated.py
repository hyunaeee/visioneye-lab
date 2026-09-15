"""Run the existing VisionEye YOLO26 pipeline on a local evaluation video.

Example:
  python scripts/evaluate_generated.py \
      --source web/assets/crowd-source.mp4 --output runs/crowd

This records model observations and observed finite-gate crossings, not accuracy.
No prompt-intended movement is treated as ground truth. Only the masked dashboard
is saved as imagery; detection misses can still remain visible in that dashboard.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import time

WALL_START = time.perf_counter()
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "visioneye"
sys.path.insert(0, str(APP))

import cv2
import numpy as np

from app import read_config
from analytics import DirectionalCounter
from detector import PersonTracker
from recording import TimedVideoWriter
from rendering import Dashboard
from sources import VideoSource


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


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Local video path")
    parser.add_argument("--config", default=str(APP / "config.json"))
    parser.add_argument("--output", required=True, help="New output directory")
    parser.add_argument("--model", default=str(APP / "models" / "yolo26n.pt"))
    parser.add_argument("--device", default="auto")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--confidence", type=float, default=0.1)
    parser.add_argument("--privacy", choices=("solid", "pixelate"), default="solid")
    parser.add_argument("--max-frames", type=int, default=0, help="0 means all frames")
    args = parser.parse_args()
    if args.imgsz < 32 or not 0 < args.confidence < 1 or args.max_frames < 0:
        parser.error("Invalid image size, confidence, or max-frames")
    if not Path(args.source).is_file():
        parser.error("--source must be an existing local file")
    if not Path(args.model).is_file():
        parser.error("--model must be an existing model file")
    return args


def timing_stats(values):
    array = np.asarray(values, dtype=float)
    if not len(array):
        return {"calls": 0, "total_seconds": 0, "mean_ms": 0,
                "p50_ms": 0, "p95_ms": 0, "max_ms": 0}
    return {"calls": len(values), "total_seconds": round(float(array.sum()), 6),
            "mean_ms": round(float(array.mean()) * 1000, 3),
            "p50_ms": round(float(np.percentile(array, 50)) * 1000, 3),
            "p95_ms": round(float(np.percentile(array, 95)) * 1000, 3),
            "max_ms": round(float(array.max()) * 1000, 3)}


def run(args):
    cfg = read_config(args.config)
    cfg["privacy"] = args.privacy
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    stages = {name: [] for name in ("source_read", "detector_and_tracker",
                                    "counter_and_geometry", "dashboard_render",
                                    "video_record", "telemetry_write")}
    processed = total_detections = confirmed_observations = zero_person_frames = 0
    unique_ids = set()
    processing_seconds = 0.0
    last_stats = {}
    frame_shape = first_timestamp = last_timestamp = None
    detector = counter = source = writer = display = None
    line = None
    status = "completed"
    initialization_seconds = 0.0
    eof_read_seconds = 0.0
    metadata = {}
    caught_error = None
    startup_tick = time.perf_counter()
    try:
        metadata = {
            "source_path": published_input_name(args.source),
            "source_sha256": sha256(args.source),
            "model_path": published_input_name(args.model),
            "model_sha256": sha256(args.model),
            "implementation_sha256": {name: sha256(APP / name) for name in
                                      ("detector.py", "analytics.py", "sources.py",
                                       "rendering.py", "recording.py", "app.py")},
            "evaluator_sha256": sha256(__file__),
            "python_version": platform.python_version(),
            "package_versions": {name: importlib.metadata.version(name) for name in
                                 ("ultralytics", "torch", "opencv-python", "numpy")},
            "model_imgsz": args.imgsz,
            "detector_confidence": args.confidence,
            "requested_device": args.device,
        }
        source = VideoSource(str(Path(args.source).resolve()))
        detector = PersonTracker(args.model, args.device, args.imgsz,
                                 args.confidence, source.fps)
        dashboard = Dashboard(cfg["line"], cfg.get("floor_quad"),
                              cfg["privacy"], cfg.get("in_side", 1))
        initialization_seconds = time.perf_counter() - startup_tick
        print(f"YOLO26 + ByteTrack | device={detector.device} | privacy={cfg['privacy']}", flush=True)
        with (out / "events.csv").open("w", newline="", encoding="utf-8") as event_file, \
                (out / "tracks.jsonl").open("w", encoding="utf-8") as track_file:
            events_csv = csv.DictWriter(event_file, fieldnames=["track_id", "direction", "frame", "timestamp"])
            events_csv.writeheader()
            while True:
                frame_tick = tick = time.perf_counter()
                ok, frame, source_index, timestamp = source.read()
                read_seconds = time.perf_counter() - tick
                if not ok:
                    eof_read_seconds += read_seconds
                    break
                stages["source_read"].append(read_seconds)
                if counter is None:
                    frame_shape = frame.shape
                    height, width = frame.shape[:2]
                    line = tuple((p[0] * width, p[1] * height) for p in cfg["line"])
                    counter = DirectionalCounter(line, in_side=cfg.get("in_side", 1),
                        hysteresis=cfg.get("hysteresis_px", 8.0),
                        initial_occupancy=cfg.get("initial_occupancy", 0),
                        max_gap_frames=cfg.get("max_gap_frames", 15),
                        ttl_frames=cfg.get("ttl_frames", 120))
                    first_timestamp = timestamp
                elif frame.shape != frame_shape:
                    raise RuntimeError("Input resolution changed; a new calibration/run is required")
                tick = time.perf_counter()
                # Exactly one real inference/tracking pass per processed frame.
                detections = detector.process(frame)
                stages["detector_and_tracker"].append(time.perf_counter() - tick)
                tick = time.perf_counter()
                points = {d["track_id"]: ((d["xyxy"][0] + d["xyxy"][2]) / 2, d["xyxy"][3])
                          for d in detections if d["track_id"] is not None}
                events = counter.update(points, source_index, timestamp)
                last_stats = counter.stats()
                last_stats["visible"] = len(points)
                unique_ids.update(points)
                total_detections += len(detections)
                confirmed_observations += len(points)
                zero_person_frames += int(not detections)
                geometry = []
                dx, dy = line[1][0] - line[0][0], line[1][1] - line[0][1]
                length = float(np.hypot(dx, dy))
                for detection in detections:
                    x1, y1, x2, y2 = detection["xyxy"]
                    foot = ((x1 + x2) / 2, y2)
                    distance = (dx * (foot[1] - line[0][1]) - dy * (foot[0] - line[0][0])) / length
                    geometry.append({**detection, "footpoint_px": foot,
                                     "signed_gate_distance_px": distance})
                stages["counter_and_geometry"].append(time.perf_counter() - tick)
                tick = time.perf_counter()
                display = dashboard.render(frame, detections, last_stats,
                    processed / processing_seconds if processing_seconds else 0.0,
                    source_index, "GENERATED TEST FOOTAGE | YOLO26 + BYTETRACK", False)
                stages["dashboard_render"].append(time.perf_counter() - tick)
                tick = time.perf_counter()
                if writer is None:
                    writer = TimedVideoWriter(out / "dashboard.mp4", source.fps,
                                              (display.shape[1], display.shape[0]))
                writer.write(display, timestamp)
                stages["video_record"].append(time.perf_counter() - tick)
                tick = time.perf_counter()
                events_csv.writerows(events)
                if events:
                    event_file.flush()
                track_file.write(json.dumps({"frame": source_index, "timestamp": timestamp,
                    "detection_count": len(detections), "confirmed_track_count": len(points),
                    "detections": geometry, "events": events, "stats": last_stats},
                    separators=(",", ":"), allow_nan=False) + "\n")
                stages["telemetry_write"].append(time.perf_counter() - tick)
                processed += 1
                last_timestamp = timestamp
                processing_seconds += time.perf_counter() - frame_tick
                if processed == 1 or events or processed % 60 == 0:
                    print(f"frame={source_index} t={timestamp:.3f}s detected={len(detections)} "
                          f"confirmed={len(points)} IN={counter.total_in} OUT={counter.total_out}", flush=True)
                if args.max_frames and processed >= args.max_frames:
                    status = "frame_limit"
                    break
        if processed == 0:
            raise RuntimeError("No input frames were processed")
    except KeyboardInterrupt as exc:
        status, caught_error = "interrupted", exc
    except Exception as exc:
        status, caught_error = "error", exc
    finally:
        finalize_tick = time.perf_counter()
        if writer is not None:
            writer.close()
        if source is not None:
            source.close()
        if display is not None and not cv2.imwrite(str(out / "preview.jpg"), display):
            status, caught_error = "error", RuntimeError("Cannot save final dashboard preview")
        finalization_seconds = time.perf_counter() - finalize_tick
        summary = dict(mode="yolo26", status=status, processed_frames=processed,
            processing_fps=round(processed / processing_seconds, 2) if processing_seconds else 0,
            wall_seconds=round(time.perf_counter() - WALL_START, 6),
            source_fps=source.fps if source is not None else None,
            device=detector.device if detector is not None else None, privacy=cfg["privacy"],
            recording_start_seconds=writer.origin if writer is not None else None,
            floor_calibrated=cfg.get("floor_quad") is not None, config=cfg, **last_stats)
        summary.update(processing_seconds=round(processing_seconds, 6),
            initialization_seconds=round(initialization_seconds, 6),
            finalization_seconds=round(finalization_seconds, 6),
            eof_read_seconds=round(eof_read_seconds, 6),
            stage_elapsed={name: timing_stats(values) for name, values in stages.items()},
            frames=processed, detector_count=total_detections,
            confirmed_track_observations=confirmed_observations,
            confirmed_tracks=len(unique_ids), confirmed_track_ids=sorted(unique_ids),
            zero_person_frame_count=zero_person_frames,
            input_size_px=[frame_shape[1], frame_shape[0]] if frame_shape else None,
            counting_line_px=line, source_first_timestamp_seconds=first_timestamp,
            source_last_timestamp_seconds=last_timestamp,
            processed_source_duration_seconds=processed / source.fps if source else None,
            recording_frames=writer.frames_written if writer is not None else 0,
            reproducibility=metadata,
            measurement_notes=[
                "All detections come from one PersonTracker.process call per frame; no scripted detections.",
                "detector_count sums detected boxes across frames; confirmed_tracks counts distinct tracker IDs, not people.",
                "zero_person_frame_count counts frames without detector boxes, not verified empty scenes.",
                "Events are confirmed finite-gate footpoint crossings using source frame indices and index/source_fps timestamps.",
                "processing_seconds includes file reads, inference/tracking, counter, render, recording and telemetry; excludes startup/finalization and console progress.",
                "wall_seconds includes imports, parsing, initialization and finalization; measured before writing this summary.",
                "Stage measurements are wall-clock call latency; detector_and_tracker includes inference, CPU transfer and tracking, and first-call warmup.",
                "The run has no annotated ground truth, so counts and timing are observations, not accuracy measurements.",
                "Masked imagery covers detected boxes only; detection misses can remain visible.",
            ])
        if caught_error is not None:
            summary["error"] = f"{type(caught_error).__name__}: {caught_error}"
        (out / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Saved: {out}")
    if caught_error is not None:
        raise caught_error
    return summary


if __name__ == "__main__":
    run(parse_args())
