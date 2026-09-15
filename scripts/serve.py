"""Preview the static viewer locally, including HTTP byte ranges for video seek."""
from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re


WEB_ROOT = Path(__file__).resolve().parents[1] / "web"


class RangeHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self.range_length = None
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def send_head(self):
        self.range_length = None
        requested = self.headers.get("Range")
        path = Path(self.translate_path(self.path)).resolve()
        if not path.is_relative_to(WEB_ROOT.resolve()):
            self.send_error(403)
            return None
        if not requested or not path.is_file():
            return super().send_head()
        size = path.stat().st_size
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
        try:
            if not match or not any(match.groups()):
                raise ValueError
            first, last = match.groups()
            start = int(first) if first else max(0, size - int(last))
            end = min(int(last), size - 1) if first and last else size - 1
            if start < 0 or start > end or start >= size:
                raise ValueError
        except ValueError:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        try:
            stream = path.open("rb")
        except OSError:
            self.send_error(404)
            return None
        stream.seek(start)
        self.range_length = end - start + 1
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(str(path)))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(self.range_length))
        self.end_headers()
        return stream

    def copyfile(self, source, outputfile):
        try:
            if self.range_length is None:
                return super().copyfile(source, outputfile)
            remaining = self.range_length
            while remaining:
                block = source.read(min(65536, remaining))
                if not block:
                    break
                outputfile.write(block)
                remaining -= len(block)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # Browsers cancel obsolete range requests while seeking.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000, help="Local port (default: 8000)")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    if not (WEB_ROOT / "index.html").is_file():
        parser.error("The repository web/index.html file is missing")
    with ThreadingHTTPServer(("127.0.0.1", args.port), RangeHandler) as server:
        print(f"VisionEye: http://127.0.0.1:{server.server_address[1]} (Ctrl+C to stop)", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
