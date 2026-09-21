# Source review protocol · 2026-09-21

## Scope and independence

- Clips: `crossing`, `occlusion`, `reentry`; approximately 10–15 seconds each, intended 1280 × 720 / 24 fps. Actual decoded metadata governs the review.
- Review uses the generated original video only. No detector boxes, tracker IDs, count logs, or model comparison results may be opened before source annotations are locked.
- Prompted people, routes, timestamps, and actions are generation instructions, not ground truth. An intended challenge counts as present only if it can be observed in the finished source.
- Reviewer: Codex source-only visual review agent. These are AI visual annotations, not independent human consensus or a public benchmark ground truth.
- Save source SHA-256 and review lock time with each clip. Any later annotation correction must retain the earlier record and explain source evidence for the change.

## Fixed counting gate

- Normalized segment: `(0.10, 0.55)` to `(0.90, 0.55)`.
- At 1280 × 720: `(128, 396)` to `(1152, 396)`; hysteresis bands at image `y=388` and `y=404`.
- IN: towards larger image y / downward. OUT: towards smaller image y / upward.
- Foot proxy: lowest visible foot / shoe belonging to a person, excluding cast shadows. It is a visual approximation to the inference counter's bottom-of-person-box midpoint, not a pixel-accurate pose label.
- Count only a transition from beyond one hysteresis band to beyond the opposite band with the path intersecting the finite segment. Foot motion into the central band followed by retreat is not a crossing. Lateral passage parallel to the gate may produce zero events.
- A person first seen inside the band, occluded over the crossing, or beyond a segment endpoint is not assigned a certain count solely from narrative intent. Record ambiguous candidates separately, with the reason and source frames.
- Initial room occupancy is unknown. Neither visible people nor arithmetic net flow establishes absolute occupancy.

## Review sequence

1. Decode metadata, count frames, verify dimensions, duration, and readable first/last frames; calculate original SHA-256.
2. Produce source-only overview contact sheets at 0.25-second steps, including first and final frames. Add frame/time labels and optional fixed gate ticks outside the person crops; no model overlays.
3. Inventory observable subjects using clothing and path descriptions (`S01`, `S02`, etc.). These identifiers are source reviewer labels and have no relationship to tracker IDs.
4. Inspect candidate line crossings with original foot-region crops every 1–2 frames. Create conservative time windows for confirmation beyond the opposite hysteresis band. Save frame windows and time windows, never guess a single exact timestamp.
5. Independently inspect challenge intervals: pre-overlap, deepest overlap/occlusion, first clear emergence, and later path. Compare clothing and uninterrupted spatial trajectory where available.
6. Save `source-review.json`, a concise `source-review.md`, and referenced evidence contact sheets under the clip review folder. Lock the source review before the inference results are compared.

## Challenge checks

| Clip | Required source observation | Review record |
|---|---|---|
| crossing | Two or more paths intersect in image space; distinguish side-by-side walking from body overlap | Subjects, overlap interval, visibility, exit paths, line events |
| occlusion | A person is visibly hidden behind a static obstacle or another person and later becomes visible | Last clear frame, partial/full occlusion interval, first clear frame, same-person confidence |
| reentry | A subject leaves the image or defined visible region and later returns | Last exit frame, absence interval, first return frame, appearance/path continuity, uncertainty |

At most 1–3 well-evidenced subject episodes per clip are selected for identity spot checks. Similar clothing alone does not prove identity. If generation alters clothing, body shape, direction, or subject count, preserve that limitation in the record. A failed or ambiguous challenge remains a failed or ambiguous generation outcome; it is not silently relabeled successful.

## Structured annotation fields

```json
{
  "review_type": "source-only visual event and challenge annotation",
  "reviewer": "Codex independent AI visual review; not human consensus",
  "review_locked_at_utc": "<UTC timestamp>",
  "clip_id": "crossing|occlusion|reentry",
  "source": "source.mp4",
  "source_sha256": "<sha256>",
  "source_width": 1280,
  "source_height": 720,
  "source_frames": 0,
  "source_fps": 24,
  "model_outputs_seen": false,
  "generation_prompt_used_as_ground_truth": false,
  "fixed_parameters": {
    "line_normalized": [[0.1, 0.55], [0.9, 0.55]],
    "line_px": [[128, 396], [1152, 396]],
    "in_side": 1,
    "hysteresis_px": 8
  },
  "manual_events": [
    {
      "manual_id": "S01",
      "subject": "<appearance and source path>",
      "direction": "IN|OUT",
      "frame_window": [0, 0],
      "window_seconds": [0.0, 0.0],
      "status": "confirmed",
      "detail_evidence": "contact-images/<filename>.jpg",
      "note": "<uncertainty if relevant>"
    }
  ],
  "ambiguous_events": [],
  "manual_totals": {"IN": 0, "OUT": 0, "confirmed_events": 0, "unknown_events": 0},
  "source_identity_episodes": [],
  "challenge_present": {"crossing": "confirmed|partial|absent|uncertain", "occlusion": "confirmed|partial|absent|uncertain", "reentry": "confirmed|partial|absent|uncertain"},
  "limitations": ["No full-frame boxes, masks, keypoints, or identity ground truth."]
}
```

Final episode entries include `subject`, `before_frame`, `visibility_interval_frames`, `after_frame`, `same_person_assessment` (`likely`, `uncertain`, or `not_supported`), source reasoning, and image evidence. Off-screen identity is necessarily an appearance/path inference and is described as such.

## Allowed subsequent comparisons

- Direction plus source-locked event-window one-to-one matching; report matched / unmatched predictions / unmatched review events. A secondary tolerance must be declared in advance and shown separately from strict windows.
- Count totals and conditional timing agreement. These are not identity-verified detection precision/recall or a general counting-accuracy benchmark.
- For source-reviewed identity episodes, inspect model IDs at source-selected frames and report a qualitative continuation, ID change, duplicate ID, or missing assignment. ID counts are not person counts; fewer IDs alone do not establish improvement.
- Without full per-frame person boxes and identity labels, do not compute or claim HOTA, IDF1, MOTA, detection recall, or mask IoU.

## Generation recommendation

Use a locked elevated camera and clear floor around the fixed gate. Include both upward and downward routes that cross `y=0.55` within `x=0.1–0.9`; purely horizontal crowd movement is insufficient for counting comparisons. Place a static occluder above or to the side of the gate so feet are visible before and after gate crossing. A useful sequence crosses the gate, undergoes a separate occlusion, then returns across it. Keep clothing distinctive while allowing genuine body overlap. Do not require a count result from the prompt.
