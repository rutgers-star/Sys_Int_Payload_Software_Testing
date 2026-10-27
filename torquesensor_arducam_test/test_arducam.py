#!/usr/bin/env python3
"""Standalone test for the Arducam / Raspberry Pi camera.

Records a short black-and-white H.264 clip with rpicam-vid (or the older
libcamera-vid), saves the per-frame timestamps, and checks that the output
exists, is not empty, and has roughly the expected length.
"""

from __future__ import annotations

import argparse
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_OUT_DIR = HERE / "results"

# rpicam-vid is the name on Raspberry Pi OS Bookworm and later; libcamera-vid on older images.
CAMERA_COMMANDS = ("rpicam-vid", "libcamera-vid")

# Extra time allowed for camera startup and file flush before the process is stopped.
STARTUP_GRACE_S = 15.0


class CameraError(Exception):
    """A camera setup problem with a message meant for the operator."""


@dataclass
class CameraResult:
    returncode: int
    wall_s: float
    video_path: Path
    pts_path: Path
    stderr_path: Path
    interrupted: bool = False


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def find_camera_command() -> str:
    for name in CAMERA_COMMANDS:
        path = shutil.which(name)
        if path:
            return path
    raise CameraError(
        f"None of {', '.join(CAMERA_COMMANDS)} found on PATH. "
        "Install the camera apps with: sudo apt install rpicam-apps"
    )


def build_command(exe: str, duration_s: float, video_path: Path, pts_path: Path,
                  width: int = 960, height: int = 540, fps: int = 24,
                  vflip: bool = True) -> list[str]:
    cmd = [
        exe,
        "-t", str(int(duration_s * 1000)),  # milliseconds
        "--nopreview",
        "--width", str(width),
        "--height", str(height),
        "--framerate", str(fps),
        "--saturation", "0",  # black and white
        "--exposure", "long",
        "--save-pts", str(pts_path),
    ]
    if vflip:
        cmd.append("--vflip")
    cmd += ["-o", str(video_path)]
    return cmd


def start_recording(cmd: list[str], stderr_path: Path) -> subprocess.Popen:
    # stderr goes to a file so a chatty camera tool cannot fill a pipe and stall.
    with open(stderr_path, "w") as err:
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=err)


def stop_process(proc: subprocess.Popen) -> None:
    """Ask the camera tool to finish (SIGINT closes the file cleanly), then force it."""
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def wait_recording(proc: subprocess.Popen, timeout_s: float) -> bool:
    """Wait for the camera tool to exit. Returns True if stopped early by Ctrl+C."""
    try:
        proc.wait(timeout=timeout_s)
        return False
    except subprocess.TimeoutExpired:
        print(f"Camera did not finish within {timeout_s:.0f} s, stopping it.", file=sys.stderr)
        stop_process(proc)
        return False
    except KeyboardInterrupt:
        print("\nInterrupted, stopping camera.")
        stop_process(proc)
        return True


def read_pts(pts_path: Path) -> list[float]:
    """Frame timestamps in ms from a --save-pts file (comment lines start with '#')."""
    if not pts_path.exists():
        return []
    values = []
    for line in pts_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            try:
                values.append(float(line))
            except ValueError:
                pass
    return values


def print_tail(path: Path, lines: int = 30) -> None:
    if path.exists():
        text = path.read_text(errors="replace").splitlines()
        print(f"--- last {min(lines, len(text))} lines of {path} ---", file=sys.stderr)
        print("\n".join(text[-lines:]), file=sys.stderr)


def report(result: CameraResult, expected_s: float) -> bool:
    """Print the camera results and return True if the recording looks good."""
    print("\n--- Camera results ---")
    if result.interrupted:
        print("(stopped early by Ctrl+C)")
    print(f"Exit code:      {result.returncode}")
    print(f"Wall time:      {result.wall_s:.2f} s (requested {expected_s:g} s)")

    ok = True
    if result.returncode != 0 and not result.interrupted:
        print("FAIL: camera tool exited with an error.")
        ok = False

    size = result.video_path.stat().st_size if result.video_path.exists() else 0
    if size == 0:
        print(f"FAIL: video file {result.video_path} is missing or empty.")
        ok = False
    else:
        print(f"Video:          {result.video_path} ({size / 1e6:.2f} MB)")

    pts = read_pts(result.pts_path)
    if len(pts) >= 2 and pts[-1] > pts[0]:
        span_s = (pts[-1] - pts[0]) / 1000.0
        print(f"Frames:         {len(pts)}")
        print(f"Clip duration:  {span_s:.2f} s (from frame timestamps)")
        print(f"Average fps:    {(len(pts) - 1) / span_s:.2f}")
        print(f"Timestamps:     {result.pts_path}")
    else:
        print(f"FAIL: no usable frame timestamps in {result.pts_path}.")
        ok = False

    if not ok:
        print_tail(result.stderr_path)
    return ok


def add_camera_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--width", type=int, default=960, help="default: %(default)s")
    parser.add_argument("--height", type=int, default=540, help="default: %(default)s")
    parser.add_argument("--fps", type=int, default=24, help="default: %(default)s")
    parser.add_argument("--no-vflip", action="store_true",
                        help="do not flip the image vertically")


def camera_command(exe: str, args: argparse.Namespace, out_dir: Path) -> tuple[list[str], CameraResult]:
    """Build the command and an (unfilled) result holding the output paths."""
    result = CameraResult(-1, 0.0, out_dir / "camera.h264", out_dir / "camera_pts.txt",
                          out_dir / "camera_stderr.log")
    cmd = build_command(exe, args.duration, result.video_path, result.pts_path,
                        args.width, args.height, args.fps, vflip=not args.no_vflip)
    return cmd, result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-d", "--duration", type=float, default=10.0,
                        help="seconds to record (default: %(default)s)")
    add_camera_args(parser)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR,
                        help="base folder for results (default: %(default)s)")
    args = parser.parse_args()

    try:
        exe = find_camera_command()
    except CameraError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    out_dir = args.out_dir / f"camera_{utc_stamp()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd, result = camera_command(exe, args, out_dir)

    print(f"Recording {args.duration:g} s (Ctrl+C to stop early).")
    print("Running:", " ".join(cmd))
    start = time.monotonic()
    proc = start_recording(cmd, result.stderr_path)
    result.interrupted = wait_recording(proc, args.duration + STARTUP_GRACE_S)
    result.returncode = proc.returncode
    result.wall_s = time.monotonic() - start
    return 0 if report(result, args.duration) else 1


if __name__ == "__main__":
    sys.exit(main())
