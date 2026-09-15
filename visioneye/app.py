"""VisionEye: local person tracking, directional counting, masking and floor mapping."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import sys
import time
from datetime import datetime

import cv2
import numpy as np

from analytics import DirectionalCounter
from rendering import Dashboard
from recording import TimedVideoWriter
from sources import SyntheticSource, VideoSource

ROOT = Path(__file__).resolve().parent


def read_config(path):
    cfg = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    def points(name, count):
        value = cfg.get(name)
        if name == "floor_quad" and value is None:
            return
        if not isinstance(value, list) or len(value) != count:
            raise ValueError(f"{name} requires {count} normalized [x,y] points.")
        for p in value:
            if not isinstance(p, list) or len(p) != 2 or not all(
                isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= 1 for v in p
            ):
                raise ValueError(f"{name} coordinates must be finite numbers from 0 to 1.")
        if len(set(map(tuple, value))) != count:
            raise ValueError(f"{name} has duplicate points.")
    points("line", 2)
    points("floor_quad", 4)
    if cfg.get("floor_quad") is not None:
        quad = np.float32(cfg["floor_quad"])
        if not cv2.isContourConvex(quad) or cv2.contourArea(quad) < .001:
            raise ValueError("floor_quad must be a convex TL,TR,BR,BL floor quadrilateral.")
    if cfg.get("in_side", 1) not in (-1, 1):
        raise ValueError("in_side must be 1 or -1.")
    if cfg.get("privacy", "solid") not in ("solid", "pixelate", "off"):
        raise ValueError("privacy must be solid, pixelate, or off.")
    initial = cfg.get("initial_occupancy", 0)
    if not isinstance(initial, int) or isinstance(initial, bool) or initial < 0:
        raise ValueError("initial_occupancy must be a nonnegative integer.")
    hysteresis = cfg.get("hysteresis_px", 8.)
    if not isinstance(hysteresis, (int, float)) or not math.isfinite(hysteresis) or hysteresis < 0:
        raise ValueError("hysteresis_px must be a finite nonnegative number.")
    gap = cfg.get("max_gap_frames", 15)
    if not isinstance(gap, int) or gap < 1:
        raise ValueError("max_gap_frames must be a positive integer.")
    return cfg


def calibrate(frame, cfg, path):
    """Raw local preview, explicitly requested with --calibrate, never recorded."""
    height, width = frame.shape[:2]
    scale = min(1., 1280 / width, 720 / height)
    display = cv2.resize(frame, (round(width * scale), round(height * scale)))
    chosen = []
    name = "Calibration - raw local preview"
    cv2.namedWindow(name)
    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(chosen) < 6:
            chosen.append([x / display.shape[1], y / display.shape[0]])
    cv2.setMouseCallback(name, on_mouse)
    try:
        while True:
            view = display.copy()
            instructions = ("Click count line START, then END" if len(chosen) < 2 else
                            "Click floor TOP LEFT, TOP RIGHT, BOTTOM RIGHT, BOTTOM LEFT")
            if len(chosen) == 6:
                instructions = "ENTER saves  |  R resets  |  ESC cancels"
            cv2.rectangle(view, (0, 0), (view.shape[1], 64), (15, 22, 29), -1)
            cv2.putText(view, instructions, (12, 25), cv2.FONT_HERSHEY_SIMPLEX, .57, (100, 240, 205), 1, cv2.LINE_AA)
            cv2.putText(view, "Raw preview - calibration only. R: reset | ESC: cancel", (12, 50), cv2.FONT_HERSHEY_SIMPLEX, .46, (225, 225, 225), 1)
            for i, p in enumerate(chosen):
                xy = (round(p[0] * display.shape[1]), round(p[1] * display.shape[0]))
                cv2.circle(view, xy, 6, (90, 245, 195), -1)
                cv2.putText(view, str(i + 1), (xy[0] + 9, xy[1]), cv2.FONT_HERSHEY_SIMPLEX, .55, (255, 255, 255), 2)
            if len(chosen) >= 2:
                p = np.int32(np.array(chosen[:2]) * [display.shape[1], display.shape[0]])
                cv2.arrowedLine(view, tuple(p[0]), tuple(p[1]), (90, 245, 195), 2)
            cv2.imshow(name, view)
            key = cv2.waitKey(20) & 0xff
            if key == 27 or cv2.getWindowProperty(name, cv2.WND_PROP_VISIBLE) < 1:
                return False
            if key in (ord("r"), ord("R")):
                chosen.clear()
            if key in (10, 13) and len(chosen) == 6:
                quad = np.float32(chosen[2:])
                if np.linalg.norm(np.array(chosen[0]) - chosen[1]) < .005:
                    print("Line endpoints are too close. Press R and select a longer counting line.")
                    continue
                if not cv2.isContourConvex(quad) or cv2.contourArea(quad) < .001:
                    print("Invalid floor quadrilateral. Press R and select the four corners in order.")
                    continue
                cfg["line"], cfg["floor_quad"] = chosen[:2], chosen[2:]
                Path(path).write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
                print(f"Calibration saved: {Path(path).resolve()}")
                return True
    finally:
        cv2.destroyWindow(name)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--source", help="Local video path, webcam index (0), or RTSP URL")
    src.add_argument("--demo", action="store_true", help="Synthetic analytics demo; no detector or camera")
    p.add_argument("--config", default=str(ROOT / "config.json"))
    p.add_argument("--model", default=str(ROOT / "models" / "yolo26n.pt"))
    p.add_argument("--device", default="auto", help="auto, cpu, or CUDA index (0)")
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--confidence", type=float, default=.1, help="Detection threshold; includes low-confidence privacy boxes")
    p.add_argument("--privacy", choices=["solid", "pixelate", "off"])
    p.add_argument("--initial-occupancy", type=int)
    p.add_argument("--reverse", action="store_true", help="Reverse IN/OUT direction")
    p.add_argument("--live", action="store_true", help="Use latest-frame capture, also auto-enabled for webcam/RTSP")
    p.add_argument("--calibrate", action="store_true", help="Select line and floor corners in a raw local preview, then exit")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--max-frames", type=int, default=0, help="Stop after N processed frames; 0 = until end")
    p.add_argument("--save-video", action="store_true", help="Save the rendered, masked dashboard")
    p.add_argument("--output-dir", help="New run directory; default runs/date-time")
    return p.parse_args()


def run(args):
    cfg = read_config(args.config)
    if args.privacy:
        cfg["privacy"] = args.privacy
    if args.initial_occupancy is not None:
        if args.initial_occupancy < 0:
            raise ValueError("--initial-occupancy must be nonnegative.")
        cfg["initial_occupancy"] = args.initial_occupancy
    if args.reverse:
        cfg["in_side"] = -cfg.get("in_side", 1)
    if args.imgsz < 32 or not 0 < args.confidence < 1 or args.max_frames < 0:
        raise ValueError("Invalid image size, confidence, or max-frames.")
    if args.calibrate and (args.headless or args.demo):
        raise ValueError("Calibration requires a real input and a visible window.")
    source = SyntheticSource() if args.demo else VideoSource(args.source, live=args.live)
    detector = counter = writer = None
    processed = 0
    last_stats = {}
    frame_shape = None
    elapsed_processing = 0.
    start = time.perf_counter()
    out = Path(args.output_dir) if args.output_dir else ROOT / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    with source:
        if args.calibrate:
            ok, frame, _, _ = source.read()
            if not ok:
                raise RuntimeError("Cannot read a frame for calibration.")
            calibrate(frame, cfg, args.config)
            return
        out.mkdir(parents=True, exist_ok=False)
        dashboard = Dashboard(cfg["line"], cfg.get("floor_quad"), cfg.get("privacy", "solid"), cfg.get("in_side", 1))
        if not args.demo:
            from detector import PersonTracker
            Path(args.model).parent.mkdir(parents=True, exist_ok=True)
            detector = PersonTracker(args.model, args.device, args.imgsz, args.confidence, source.fps)
            print(f"YOLO26 + ByteTrack | device={detector.device} | privacy={cfg.get('privacy', 'solid')}")
        else:
            print("SYNTHETIC DEMO: generated detections; this does not measure YOLO accuracy or speed.")
        status = "completed"
        with (out / "events.csv").open("w", newline="", encoding="utf-8") as event_file:
            events_csv = csv.DictWriter(event_file, fieldnames=["track_id", "direction", "frame", "timestamp"])
            events_csv.writeheader()
            try:
                while True:
                    tick = time.perf_counter()
                    ok, frame, source_index, timestamp = source.read()
                    if not ok:
                        break
                    if counter is None:
                        height, width = frame.shape[:2]
                        frame_shape = frame.shape
                        line = tuple((p[0] * width, p[1] * height) for p in cfg["line"])
                        counter = DirectionalCounter(line, in_side=cfg.get("in_side", 1),
                            hysteresis=cfg.get("hysteresis_px", 8.), initial_occupancy=cfg.get("initial_occupancy", 0),
                            max_gap_frames=cfg.get("max_gap_frames", 15))
                    elif frame.shape != frame_shape:
                        raise RuntimeError("Input resolution changed. Recalibrate and start a new run.")
                    detections = source.detections if args.demo else detector.process(frame)
                    points = {d["track_id"]: ((d["xyxy"][0] + d["xyxy"][2]) / 2, d["xyxy"][3])
                              for d in detections if d["track_id"] is not None}
                    events = counter.update(points, source_index, timestamp)
                    events_csv.writerows(events)
                    if events:
                        event_file.flush()
                    last_stats = counter.stats()
                    last_stats["visible"] = len(points)
                    processing_fps = processed / elapsed_processing if elapsed_processing else 0.
                    display = dashboard.render(frame, detections, last_stats, processing_fps,
                        source_index, "SYNTHETIC" if args.demo else "LOCAL INPUT", args.demo)
                    if args.save_video:
                        if writer is None:
                            writer = TimedVideoWriter(str(out / "dashboard.mp4"), source.fps,
                                (display.shape[1], display.shape[0]))
                        writer.write(display, timestamp)
                    processed += 1
                    elapsed_processing += time.perf_counter() - tick
                    if processed == 1 or events or (args.max_frames and processed == args.max_frames):
                        if not cv2.imwrite(str(out / "preview.jpg"), display):
                            raise RuntimeError("Cannot save dashboard preview.")
                    if not args.headless:
                        cv2.imshow("VisionEye - Q or ESC to stop", display)
                        delay = max(1, round(1000 / source.fps - 1000 * (time.perf_counter() - tick)))
                        key = cv2.waitKey(delay) & 0xff
                        if key in (27, ord("q")) or cv2.getWindowProperty("VisionEye - Q or ESC to stop", cv2.WND_PROP_VISIBLE) < 1:
                            status = "stopped_by_user"
                            break
                    if args.max_frames and processed >= args.max_frames:
                        status = "frame_limit"
                        break
            except KeyboardInterrupt:
                status = "interrupted"
            except Exception:
                status = "error"
                raise
            finally:
                if processed:
                    cv2.imwrite(str(out / "preview.jpg"), display)
                if writer is not None:
                    writer.close()
                if not args.headless:
                    cv2.destroyAllWindows()
                summary = dict(mode="synthetic_demo" if args.demo else "yolo26", status=status,
                    processed_frames=processed, processing_fps=round(processed / elapsed_processing, 2) if elapsed_processing else 0,
                    wall_seconds=round(time.perf_counter() - start, 2), source_fps=source.fps,
                    device=detector.device if detector else "synthetic", privacy=cfg.get("privacy", "solid"),
                    recording_start_seconds=writer.origin if writer else None,
                    floor_calibrated=cfg.get("floor_quad") is not None, config=cfg, **last_stats)
                (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        if processed == 0:
            raise RuntimeError("No input frames were processed.")
    print(json.dumps(summary, indent=2))
    print(f"Saved: {out.resolve()}")


if __name__ == "__main__":
    try:
        run(parse_args())
    except Exception as exc:
        print(f"VisionEye error: {exc}", file=sys.stderr)
        sys.exit(1)
