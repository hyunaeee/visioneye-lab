# 2026-09-21 comparison reproduction

The portable entry point is `run.py`. It runs one detector/tracker/clip combination at a time with the source and source-review SHA-256 values locked in the published protocol. It requires an NVIDIA CUDA device. It does not generate new videos or treat a generation prompt as ground truth.

## Preparation

From the repository root, using Python 3.12 (the measured interpreter was 3.12.14):

```powershell
python scripts/experiments/2026-09-21/prepare.py --environment
python scripts/experiments/2026-09-21/prepare.py --code --assets all
```

`prepare.py` creates a new isolated environment with Torch 2.11.0+cu128 and torchvision 0.26.0+cu128, and installs the pinned main dependencies in `requirements.txt`. It clones the official RT-DETR repository at `29320b6fd828f8e0987a71426cf2d961b09dfed7`, downloads only official release checkpoints, and verifies every checkpoint's fixed SHA-256 and byte size. Model files, the third-party checkout, and the environment stay under ignored `.runtime/`; none are vendored here. Existing mismatched weights, modified checkouts, and existing environments are preserved rather than overwritten.

The original experiment reused an existing CUDA environment; its RT-DETR environment referenced the base environment's packages and added separate dependencies. The portable preparation instead creates one standalone environment. Main versions match, but a fresh environment's transitive packages, OS, driver, and background processes can differ. `preparation/rtdetr-environment-versions.json` records the original visible package versions. Fresh installation was **not** executed while packaging; the package's smoke verification is syntax and CLI help only.

## Execution

The Windows executable after preparation is `scripts/experiments/2026-09-21/.runtime/env/Scripts/python.exe`. On Linux use `.runtime/env/bin/python` and compatible CUDA drivers. Commands below assume repository-root working directory.

```powershell
& scripts/experiments/2026-09-21/.runtime/env/Scripts/python.exe -B scripts/experiments/2026-09-21/run.py --engine yolo26n --tracker bytetrack --clip crossing --output runs/robustness/yolo26n-crossing --repeats 3
& scripts/experiments/2026-09-21/.runtime/env/Scripts/python.exe -B scripts/experiments/2026-09-21/run.py --engine yolov8n --tracker bytetrack --clip crossing --output runs/robustness/yolov8n-crossing --repeats 3
& scripts/experiments/2026-09-21/.runtime/env/Scripts/python.exe -B scripts/experiments/2026-09-21/run.py --engine yolo11n --tracker bytetrack --clip crossing --output runs/robustness/yolo11n-crossing --repeats 3
& scripts/experiments/2026-09-21/.runtime/env/Scripts/python.exe -B scripts/experiments/2026-09-21/run.py --engine rtdetrv2_s --tracker bytetrack --clip crossing --output runs/robustness/rtdetrv2-crossing --repeats 3
```

Repeat using the other clip keys present in the protocol. The default protocol is `experiments/results/2026-09-21/protocol.json`; `--protocol path/to/protocol.json` overrides it. Its `file` and `review_file` values are repository-relative. Output directories must be new. `--max-frames` creates a labeled partial run for local debugging; it is not a completed comparison.

To compare association on the same postprocessed YOLO26n boxes, create the YOLO26n run first, then reuse its first repetition for each tracker:

```powershell
& scripts/experiments/2026-09-21/.runtime/env/Scripts/python.exe -B scripts/experiments/2026-09-21/run.py --engine yolo26n --tracker botsort --clip crossing --cache runs/robustness/yolo26n-crossing/rep01/tracks.jsonl --output runs/robustness/cached-botsort-crossing --repeats 3
```

Run analogous cached commands with `--tracker bytetrack` and `--tracker tracktrack`. The cache must have its adjacent `summary.json` and the full source frame count. Cached tracking excludes detector inference and is not full-pipeline FPS. A per-package lock prevents simultaneous jobs through this runner; also avoid other GPU workloads when measuring speed.

## Fixed methods

- All four detectors: FP32, batch 1, 640 × 640 native input preset, person confidence 0.1. Nano YOLO models and RT-DETRv2-S are not parameter/FLOP matched.
- YOLO26n/YOLOv8n/YOLO11n: Ultralytics 8.4.150, square letterbox, one-to-many head plus external NMS at IoU 0.7 (`nms=None` in this pinned version). This YOLO26n condition is **not** its NMS-free branch. Runtime FP32 and non-end-to-end conditions are asserted.
- RT-DETRv2-S: official ResNet18-vd 48.1-named checkpoint, strict EMA weight load, official deploy conversion, PIL bilinear warp resize, `/255`, no ImageNet normalization, official top-300 and no additional NMS. The checkpoint filename is the provider's benchmark label, not locally measured accuracy.
- ByteTrack/BoT-SORT/TrackTrack: pinned Ultralytics implementations; approximately one-second lost-track buffer; ReID OFF and camera-motion compensation OFF. Native association thresholds remain different. Raw box/score order is preserved and IDs are attached by validated original detection indices.
- Counter: `(128,396)–(1152,396)`, 8-pixel hysteresis, downward IN, max gap 15, TTL 120, arithmetic initial occupancy zero; actual room occupancy remains unknown.
- Three repeats, five first-frame warmup calls before each repeat, reset tracking history before frame zero. Processing includes source read, detection if enabled, association, counting, and JSONL telemetry; initialization, warmup, visualization, and video export are excluded.
- Event comparison is one-to-one direction/time correspondence against source-only AI review windows, plus a separately reported ±0.5 s tolerance. It is not identity-verified accuracy. No full-frame box/ID ground truth, HOTA, or IDF1 is implied.

## Executed sources and portable changes

`executed/` stores byte-for-byte snapshots of the three original measured-program source files. They preserve their original private-workspace **relative layout assumptions**, and are archival evidence rather than executable entry points in that folder. No private absolute user path is embedded. The `runner_sha256` and `adapter_sha256` fields in measured outputs refer to these original bytes, not the portable copies.

Portable copies change only repository/runtime path resolution, the protocol path/CLI option, and the RT-DETR module usage text. Measurement, model, tracker, event matching, precision, and counter logic remain the same. Consequently source hashes differ. `SOURCE_PROVENANCE.json` records both sets of SHA-256 values and the path adaptation. Newly reproduced outputs will correctly record the portable file hashes and may differ in hardware timing.

`preparation/` contains recorded preparation checks, not comparison results. Baseline CPU smoke ran on an earlier crowd frame and used no GPU. RT-DETR CPU preparation checked strict loading and synthetic postprocessor contracts; it did not perform detector forward or GPU inference. These checks must not be described as benchmark runs. The measured runner's result files are published separately with the source-locked protocol.

## Upstream licenses

Ultralytics models/code and the integrated tracker implementations retain their [upstream license and usage terms](https://github.com/ultralytics/ultralytics/blob/v8.4.150/LICENSE) (AGPL-3.0 or separately obtained commercial terms). The [RT-DETR repository license](https://github.com/lyuwenyu/RT-DETR/blob/29320b6fd828f8e0987a71426cf2d961b09dfed7/LICENSE) is Apache-2.0; the original preparation did not identify a separate checkpoint license declaration in that release. No third-party license is replaced by this wrapper. The model and source links are recorded so their upstream notices can be retained when obtaining those artifacts.
