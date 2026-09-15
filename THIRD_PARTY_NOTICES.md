# Third-party notices and licensing status

No project-wide license file was found in the supplied VisionEye source. This packaging step does not assign a new license, claim corporate ownership, or grant rights to third-party components or generated media.

The following identifiers were read from the installed distributions used for the recorded experiment, rather than inferred as a license for this whole repository.

| Component | Recorded version | Distribution metadata |
|---|---|---|
| ultralytics | 8.4.150 | AGPL-3.0 |
| torch | 2.11.0+cu128 | BSD-3-Clause |
| torchvision | 0.26.0+cu128 | BSD |
| opencv-python | 4.14.0.94 | Apache 2.0 |
| numpy | 2.5.2 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| lap | 0.5.13 | BSD-2-Clause |
| imageio-ffmpeg | 0.6.0 | BSD-2-Clause |

Ultralytics, PyTorch and the other packages are dependencies, not vendored source. The model weights are excluded. `scripts/download_model.py` obtains the upstream YOLO26n asset and verifies the recorded SHA256 `9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef`.

An unmodified copy of the installed Ultralytics AGPL-3.0 license is included in `third-party-licenses/ultralytics-LICENSE.txt` for reference; this does not designate the project's own license. The imageio-ffmpeg wrapper license is also included. Its optional bundled FFmpeg executable has its own build-dependent licensing; no executable is included here. The overlay renderer invokes libx264 for H.264 encoding.

The static viewer requests Noto Sans KR and IBM Plex Mono from Google Fonts; font files are not bundled. The two source clips were generated through Higgsfield (Seedance 2.5) for this experiment; original files, derived analysis clips, posters and visual review data are included as demonstration assets. No independent human annotation study, ownership determination, or legal review of generated-media distribution was performed.

Upstream references: [Ultralytics licensing](https://www.ultralytics.com/license), [Ultralytics source](https://github.com/ultralytics/ultralytics), [PyTorch](https://github.com/pytorch/pytorch), [OpenCV Python](https://github.com/opencv/opencv-python), [NumPy](https://github.com/numpy/numpy), [lap](https://github.com/gatagat/lap), [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg), [FFmpeg](https://ffmpeg.org/legal.html).
