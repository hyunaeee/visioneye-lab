"""Privacy-first OpenCV dashboard for VisionEye.

All source imagery is copied and masked before it is resized into the output.
Only detection geometry, never source crops, is used by the side panels.
"""

from collections import deque
import math

import cv2
import numpy as np


BG = (19, 16, 12)
PANEL = (32, 28, 23)
PANEL_SOFT = (39, 34, 28)
BORDER = (61, 53, 43)
TEXT = (238, 241, 235)
MUTED = (155, 161, 149)
MINT = (180, 237, 112)
CYAN = (234, 199, 91)
AMBER = (107, 194, 255)
RED = (111, 117, 244)


def _text(image, label, origin, size=0.5, color=TEXT, thickness=1):
    cv2.putText(image, str(label), tuple(map(int, origin)),
                cv2.FONT_HERSHEY_SIMPLEX, size, color, thickness, cv2.LINE_AA)


def _panel(image, x, y, w, h, color=PANEL):
    cv2.rectangle(image, (x, y), (x + w, y + h), color, -1)
    cv2.rectangle(image, (x, y), (x + w, y + h), BORDER, 1)


def _badge(image, label, x, y, color=MINT, fill=PANEL_SOFT):
    width = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.39, 1)[0][0] + 20
    cv2.rectangle(image, (x, y), (x + width, y + 25), fill, -1)
    _text(image, label, (x + 10, y + 17), 0.39, color)
    return width


def _normalized_points(value, count, name):
    points = np.asarray(value, dtype=np.float32)
    if points.shape != (count, 2) or not np.isfinite(points).all():
        raise ValueError(f"{name} must contain {count} finite [x, y] points")
    if np.any(points < 0) or np.any(points > 1):
        raise ValueError(f"{name} points must be normalized to [0, 1]")
    return points


class Dashboard:
    """Render a fixed-size 1360 x 820 dashboard with letterboxed video.

    ``line`` and ``floor_quad`` use normalized source-image coordinates.
    The quad must be ordered top-left, top-right, bottom-right, bottom-left
    around the physical floor. Its result is a relative floor map, not meters.
    Positive ``in_side`` is the cross-product-positive side of line A -> B.
    """

    width = 1360
    height = 820

    def __init__(self, line, floor_quad=None, privacy="solid", in_side=1):
        self.line = _normalized_points(line, 2, "line")
        if np.linalg.norm(self.line[1] - self.line[0]) < 1e-5:
            raise ValueError("Counting line endpoints must be different")
        if privacy not in {"solid", "pixelate", "off"}:
            raise ValueError("privacy must be solid, pixelate, or off")
        if in_side not in {-1, 1}:
            raise ValueError("in_side must be -1 or 1")
        self.privacy = privacy
        self.in_side = in_side
        self.floor_quad = None
        self.homography = None
        if floor_quad is not None:
            points = _normalized_points(floor_quad, 4, "floor_quad")
            if not cv2.isContourConvex(points) or abs(cv2.contourArea(points)) < 1e-4:
                raise ValueError("floor_quad must be a non-degenerate convex floor polygon")
            self.floor_quad = points
            self.homography = cv2.getPerspectiveTransform(
                points, np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32))
        self.trails = {}
        self.last_frame = -1

    def _mask(self, frame, detections):
        safe = frame.copy()
        h, w = safe.shape[:2]
        geometry = []
        for detection in detections:
            box = np.asarray(detection.get("xyxy", []), dtype=float)
            if box.shape != (4,) or not np.isfinite(box).all():
                continue
            x1, y1, x2, y2 = box.tolist()
            if x2 <= x1 or y2 <= y1:
                continue
            # Mask a little beyond each detected body, including untracked boxes.
            px = max(5, int(math.ceil((x2 - x1) * 0.08)))
            py = max(5, int(math.ceil((y2 - y1) * 0.04)))
            left, top = max(0, math.floor(x1) - px), max(0, math.floor(y1) - py)
            right, bottom = min(w, math.ceil(x2) + px), min(h, math.ceil(y2) + py)
            if right <= left or bottom <= top:
                continue
            if self.privacy == "solid":
                safe[top:bottom, left:right] = (46, 53, 48)
            elif self.privacy == "pixelate":
                crop = safe[top:bottom, left:right]
                # At most six cells across a body, with proportionate height.
                rows = max(1, min(12, int(round(6 * crop.shape[0] / crop.shape[1]))))
                tiny = cv2.resize(crop, (6, rows), interpolation=cv2.INTER_AREA)
                safe[top:bottom, left:right] = cv2.resize(
                    tiny, (right - left, bottom - top), interpolation=cv2.INTER_NEAREST)
            foot = np.array([((x1 + x2) / 2) / max(w - 1, 1), y2 / max(h - 1, 1)], np.float32)
            item = dict(detection)
            item["foot"] = foot
            item["box"] = np.array([x1 / w, y1 / h, x2 / w, y2 / h])
            geometry.append(item)
        return safe, geometry

    def _map_point(self, point):
        if self.floor_quad is None:
            return point if np.all((point >= 0) & (point <= 1)) else None
        if cv2.pointPolygonTest(self.floor_quad, tuple(map(float, point)), False) < 0:
            return None
        mapped = cv2.perspectiveTransform(np.array([[point]], np.float32), self.homography)[0, 0]
        return mapped if np.isfinite(mapped).all() and np.all((mapped >= -0.01) & (mapped <= 1.01)) else None

    def _update_trails(self, geometry, frame_index):
        if frame_index < self.last_frame:
            self.trails.clear()
        for item in geometry:
            track_id = item.get("track_id")
            if track_id is None:
                continue
            entry = self.trails.setdefault(int(track_id), {"points": deque(maxlen=48), "last": -1})
            if entry["last"] != frame_index:
                entry["points"].append(item["foot"].copy())
            entry["last"] = frame_index
        self.trails = {key: value for key, value in self.trails.items()
                       if frame_index - value["last"] <= 90}
        self.last_frame = frame_index

    def _video(self, canvas, safe, geometry, frame_index):
        vx, vy, vw, vh = 24, 120, 936, 526
        _panel(canvas, vx, vy, vw, vh, (12, 11, 9))
        h, w = safe.shape[:2]
        scale = min((vw - 2) / w, (vh - 2) / h)
        rw, rh = max(1, round(w * scale)), max(1, round(h * scale))
        ox, oy = vx + (vw - rw) // 2, vy + (vh - rh) // 2
        canvas[oy:oy + rh, ox:ox + rw] = cv2.resize(safe, (rw, rh), interpolation=cv2.INTER_AREA)

        def screen(point):
            return tuple(np.round([ox + point[0] * (rw - 1), oy + point[1] * (rh - 1)]).astype(int))

        if self.floor_quad is not None:
            corners = np.array([screen(point) for point in self.floor_quad], np.int32)
            cv2.polylines(canvas, [corners], True, CYAN, 1, cv2.LINE_AA)
        active_ids = {int(item["track_id"]) for item in geometry if item.get("track_id") is not None}
        for track_id in active_ids:
            points = self.trails[track_id]["points"]
            if len(points) > 1:
                trail = np.array([screen(point) for point in points], np.int32)
                cv2.polylines(canvas, [trail], False, (126, 174, 91), 2, cv2.LINE_AA)
        a, b = screen(self.line[0]), screen(self.line[1])
        cv2.line(canvas, a, b, MINT, 2, cv2.LINE_AA)
        for p in (a, b):
            cv2.circle(canvas, p, 5, BG, -1, cv2.LINE_AA)
            cv2.circle(canvas, p, 4, MINT, 1, cv2.LINE_AA)
        delta = np.array(b, float) - np.array(a, float)
        normal = self.in_side * np.array([-delta[1], delta[0]]) / max(np.linalg.norm(delta), 1)
        middle = (np.array(a, float) + b) / 2
        start = tuple(np.round(middle - normal * 24).astype(int))
        end = tuple(np.round(middle + normal * 32).astype(int))
        cv2.arrowedLine(canvas, start, end, MINT, 2, cv2.LINE_AA, tipLength=0.3)
        _text(canvas, "IN", (end[0] + 9, end[1] + 4), 0.46, MINT, 1)
        for item in geometry:
            x1, y1, x2, y2 = item["box"]
            p1 = screen(np.clip([x1, y1], 0, 1))
            p2 = screen(np.clip([x2, y2], 0, 1))
            track_id = item.get("track_id")
            color = MINT if track_id is not None else AMBER
            cv2.rectangle(canvas, p1, p2, color, 1, cv2.LINE_AA)
            label = f"ID {int(track_id):02d}" if track_id is not None else "PERSON"
            confidence = item.get("confidence")
            if confidence is not None and math.isfinite(float(confidence)):
                label += f"  {float(confidence):.0%}"
            label_width = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, .37, 1)[0][0] + 12
            tx = max(ox, min(p1[0], ox + rw - label_width))
            ty = max(oy + 20, p1[1])
            cv2.rectangle(canvas, (tx, ty - 20), (tx + label_width, ty), BG, -1)
            _text(canvas, label, (tx + 6, ty - 6), .37, color)
            foot = screen(np.clip(item["foot"], 0, 1))
            cv2.circle(canvas, foot, 4, color, -1, cv2.LINE_AA)
        _badge(canvas, "COUNTING LINE", vx + 14, vy + vh - 39, MINT)
        _text(canvas, f"FRAME {frame_index:06d}", (vx + vw - 145, vy + vh - 21), .4, TEXT)

    def _map(self, canvas, geometry):
        x, y, w, h = 984, 310, 352, 332
        _panel(canvas, x, y, w, h)
        _text(canvas, "SCENE MAP", (x + 20, y + 29), .49, TEXT, 1)
        calibrated = self.homography is not None
        _text(canvas, "RELATIVE FLOOR COORDINATES" if calibrated else "IMAGE SPACE", (x + 20, y + 50), .33, CYAN)
        mx, my, mw, mh = x + 20, y + 68, w - 40, 203
        cv2.rectangle(canvas, (mx, my), (mx + mw, my + mh), BG, -1)
        for i in range(1, 6):
            gx = mx + i * mw // 6
            cv2.line(canvas, (gx, my), (gx, my + mh), (39, 38, 29), 1)
        for i in range(1, 4):
            gy = my + i * mh // 4
            cv2.line(canvas, (mx, gy), (mx + mw, gy), (39, 38, 29), 1)
        cv2.rectangle(canvas, (mx, my), (mx + mw, my + mh), BORDER, 1)

        def screen(point):
            return tuple(np.round([mx + np.clip(point[0], 0, 1) * mw,
                                   my + np.clip(point[1], 0, 1) * mh]).astype(int))

        # Sample only the part of the counting line inside the calibrated floor.
        segment = []
        for t in np.linspace(0, 1, 80):
            point = self._map_point(self.line[0] * (1 - t) + self.line[1] * t)
            if point is not None:
                segment.append(screen(point))
        if len(segment) > 1:
            cv2.polylines(canvas, [np.array(segment, np.int32)], False, (97, 132, 68), 1, cv2.LINE_AA)
        for item in geometry:
            track_id = item.get("track_id")
            if track_id is not None and int(track_id) in self.trails:
                previous = None
                for foot in self.trails[int(track_id)]["points"]:
                    point = self._map_point(foot)
                    if point is None:
                        previous = None
                        continue
                    current = screen(point)
                    if previous is not None:
                        cv2.line(canvas, previous, current, (112, 127, 56), 1, cv2.LINE_AA)
                    previous = current
            point = self._map_point(item["foot"])
            if point is None:
                continue
            position = screen(point)
            color = MINT if track_id is not None else AMBER
            cv2.circle(canvas, position, 9, (68, 76, 40), -1, cv2.LINE_AA)
            cv2.circle(canvas, position, 4, color, -1, cv2.LINE_AA)
            if track_id is not None:
                tx = min(mx + mw - 30, position[0] + 10)
                ty = max(my + 14, min(my + mh - 4, position[1] - 6))
                _text(canvas, str(int(track_id)), (tx, ty), .34, TEXT)
        _text(canvas, "Footpoint projection / floor polygon only" if calibrated else "CALIBRATION REQUIRED for top-view",
              (x + 20, y + 294), .37, MUTED if calibrated else AMBER)
        _text(canvas, "Dots represent detected persons", (x + 20, y + 314), .34, MUTED)

    def render(self, frame, detections, stats, fps, frame_index, source_label="VIDEO", demo=False):
        """Return a BGR dashboard; never modify or expose the unmasked input."""
        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3 or frame.size == 0:
            raise ValueError("frame must be a non-empty BGR image")
        if frame.dtype != np.uint8:
            raise ValueError("frame must have uint8 pixel values")
        detections = list(detections)
        frame_index = int(frame_index)
        safe, geometry = self._mask(frame, detections)
        self._update_trails(geometry, frame_index)
        canvas = np.full((self.height, self.width, 3), BG, np.uint8)

        cv2.circle(canvas, (38, 37), 12, MINT, 2, cv2.LINE_AA)
        cv2.circle(canvas, (38, 37), 4, MINT, -1, cv2.LINE_AA)
        _text(canvas, "VISIONEYE", (62, 46), .79, TEXT, 2)
        _text(canvas, "REAL-TIME FOOT TRAFFIC INTELLIGENCE", (24, 78), .42, MUTED)
        _badge(canvas, "SYNTHETIC DEMO" if demo else "LIVE ANALYTICS", 1115, 27, AMBER if demo else MINT)
        cv2.line(canvas, (24, 96), (1336, 96), BORDER, 1)
        _text(canvas, str(source_label).encode("ascii", "replace").decode()[:68], (24, 112), .33, MUTED)
        safe_fps = float(fps) if math.isfinite(float(fps)) else 0.0
        _text(canvas, f"{safe_fps:.1f} FPS", (880, 112), .36, MINT)

        self._video(canvas, safe, geometry, frame_index)
        _panel(canvas, 984, 120, 352, 170)
        _text(canvas, "LIVE OCCUPANCY", (1004, 150), .49, MUTED)
        occupancy = int(stats.get("occupancy", 0))
        _text(canvas, str(occupancy), (1000, 222), 2.0, MINT, 3)
        _text(canvas, "people / estimated", (1135, 219), .38, TEXT)
        cv2.line(canvas, (1004, 240), (1316, 240), BORDER, 1)
        active = len({int(item["track_id"]) for item in geometry if item.get("track_id") is not None})
        _text(canvas, f"{active:02d} active tracks", (1004, 268), .41, TEXT)
        _text(canvas, f"{len(geometry):02d} detected", (1198, 268), .36, MUTED)
        self._map(canvas, geometry)

        metrics = [
            (24, "TOTAL IN", int(stats.get("total_in", 0)), "Entries across the line", MINT),
            (344, "TOTAL OUT", int(stats.get("total_out", 0)), "Exits across the line", CYAN),
            (664, "NET CHANGE", int(stats.get("total_in", 0)) - int(stats.get("total_out", 0)), "IN minus OUT / session", TEXT),
        ]
        for x, name, value, description, color in metrics:
            _panel(canvas, x, 666, 296, 124)
            _text(canvas, name, (x + 18, 693), .44, MUTED)
            _text(canvas, str(value), (x + 15, 748), 1.38, color, 2)
            _text(canvas, description, (x + 18, 774), .36, MUTED)

        _panel(canvas, 984, 662, 352, 128)
        privacy_label = {"solid": "PRIVACY / SOLID", "pixelate": "PRIVACY / PIXELATE", "off": "PRIVACY / OFF"}[self.privacy]
        _badge(canvas, privacy_label, 1004, 676, MINT if self.privacy == "solid" else AMBER)
        _text(canvas, "Detected persons masked" if self.privacy != "off" else "Source imagery is visible",
              (1004, 722), .42, TEXT)
        _text(canvas, "Detection misses remain visible", (1004, 743), .35, MUTED)
        underflow = bool(stats.get("underflow", False)) or int(stats.get("raw_occupancy", occupancy)) < 0
        _text(canvas, "CHECK INITIAL OCCUPANCY" if underflow else "Counting uses tracked line crossings",
              (1004, 774), .36, AMBER if underflow else MUTED)
        _text(canvas, "VISIONEYE  /  SESSION ANALYTICS", (24, 811), .3, MUTED)
        _text(canvas, "DEMO DATA - NO MODEL INFERENCE" if demo else "YOLO + MULTI-OBJECT TRACKING", (1053, 811), .3, MUTED)
        return canvas
