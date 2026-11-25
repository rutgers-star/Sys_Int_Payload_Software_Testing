#!/usr/bin/env python3
"""Capture the torque sensor and the Arducam at the same time and verify the run.

Default is a 20 s capture. The sensor is started and tared first. Then the
camera (libcamera-vid, as in the payload) is launched, and this process logs
the sensor until the camera finishes. Everything goes into one timestamped
results folder with the two streams kept in separate, identifiable files:

  torque_sensor.csv    stream TORQUE  - one row per sensor frame
  camera.h264          stream CAMERA  - raw video
  camera_pts.txt       stream CAMERA  - per-frame camera timestamps (ms)
  camera_frames.csv    stream CAMERA  - those frames placed on the shared clock
  run.log              timestamped log of both streams and the run
  run_info.json        stream manifest, shared clock zero, Pi details
  validation.txt       PASS/FAIL report from validate_run.py

Both streams carry UTC time, the Pi monotonic clock and met_s: seconds since
camera launch, the shared mission elapsed time (MET) zero. Camera frames are
placed on that clock from the moment the camera's file first has data.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import validate_run
from test_arducam import (
    STARTUP_GRACE_S, CameraError, FirstDataWatcher, add_camera_args, camera_command,
    find_camera_command, list_cameras, read_pts, report, start_recording, stop_process,
    wait_recording,
)
from test_torque_sensor import (
    DEFAULT_OUT_DIR, SensorError, SensorStats, add_sensor_args, check_payload_config,
    load_config, log_sensor, prepare_config, print_stats, sensor_passed, start_driver,
    stop_driver, utc_stamp,
)

STREAM_TORQUE = "TORQUE"
STREAM_CAMERA = "CAMERA"


def setup_logging(path: Path) -> logging.Logger:
    """Log to the console and to run.log, both with UTC timestamps."""
    log = logging.getLogger("capture")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s.%(msecs)03dZ %(levelname)-7s %(message)s",
                            datefmt="%Y-%m-%dT%H:%M:%S")
    fmt.converter = time.gmtime
    for handler in (logging.FileHandler(path, mode="w"), logging.StreamHandler(sys.stdout)):
        handler.setFormatter(fmt)
        log.addHandler(handler)
    return log


def _read(path: str) -> str | None:
    try:
        with open(path, errors="replace") as f:
            return f.read().replace("\x00", "").strip()
    except OSError:
        return None


def _run(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def get_throttled() -> str | None:
    """Pi firmware power/thermal flags (e.g. '0x0'), or None if vcgencmd is absent."""
    out = _run(["vcgencmd", "get_throttled"])
    return out.split("=", 1)[1] if out and "=" in out else None


def system_info() -> dict:
    """Details of the computer the run happened on (memory, model, OS)."""
    mem_mb = None
    for line in (_read("/proc/meminfo") or "").splitlines():
        if line.startswith("MemTotal:"):
            mem_mb = round(int(line.split()[1]) / 1024)
    return {
        "hostname": platform.node(),
        "pi_model": _read("/proc/device-tree/model"),
        "mem_total_mb": mem_mb,
        "os": platform.platform(),
        "machine": platform.machine(),
        "python_bits": 64 if sys.maxsize > 2**32 else 32,
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "cpu_temp": _run(["vcgencmd", "measure_temp"]),
    }


def write_camera_frames(pts_path: Path, out_path: Path, first_mono: float, first_utc: str,
                        t0: float) -> int:
    """Place every camera frame on the shared clock. Returns the frame count.

    --save-pts times start at the first frame, so frame k happened at
    first-data time + (pts_k - pts_0).
    """
    pts = read_pts(pts_path)
    base_utc = datetime.fromisoformat(first_utc)
    with open(out_path, "w") as f:
        f.write("frame_index,pts_ms,utc_time,monotonic_s,met_s\n")
        for i, p in enumerate(pts):
            dt = (p - pts[0]) / 1000.0
            mono = first_mono + dt
            utc = (base_utc + timedelta(seconds=dt)).isoformat(timespec="microseconds")
            f.write(f"{i},{p:.3f},{utc},{mono:.6f},{mono - t0:.6f}\n")
    return len(pts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-d", "--duration", type=float, default=20.0,
                        help="seconds to run both (default: %(default)s)")
    add_sensor_args(parser)
    add_camera_args(parser)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR,
                        help="base folder for results (default: %(default)s)")
    parser.add_argument("--min-mem-gb", type=float,
                        help="fail the memory check if the Pi has less RAM than this (the "
                             "payload memory spec); without it memory is only reported")
    args = parser.parse_args()

    out_dir = args.out_dir / f"both_{utc_stamp()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "torque_sensor.csv"
    log = setup_logging(out_dir / "run.log")

    sysinfo = system_info()
    throttled_before = get_throttled()
    log.info("Run folder: %s", out_dir)
    log.info("Computer: %s | RAM %s MB | %s | %d-bit Python %s | throttled=%s",
             sysinfo["pi_model"] or sysinfo["hostname"], sysinfo["mem_total_mb"],
             sysinfo["machine"], sysinfo["python_bits"], sysinfo["python"], throttled_before)

    # Check both devices before starting either, so a missing camera tool
    # does not leave the sensor half set up.
    try:
        exe = find_camera_command()
        _, camera_list = list_cameras(exe)
        log.info("Camera tool: %s (libcamera)", exe)
        log.info("libcamera cameras: %s", " | ".join(l.strip() for l in camera_list.splitlines() if l.strip()))
        config_used = prepare_config(args.config, args.port, out_dir, args.sinc_length)
        config = load_config(config_used)
    except (CameraError, SensorError) as e:
        log.error("%s", e)
        return 2
    diffs = check_payload_config(config)
    if diffs:
        for d in diffs:
            log.warning("sensor config differs from the payload repo - %s", d)
    else:
        log.info("Sensor config matches the payload repo (sinc_length %s, baud %s, port %s)",
                 config["driver_config"]["sensor_operation_params"]["sinc_length"],
                 config["driver_config"]["communication_interface_params"]["baudrate"],
                 config["driver_config"]["communication_interface_params"]["com_port"])

    log.info("Starting sensor ...")
    try:
        driver = start_driver(config_used)
    except SensorError as e:
        log.error("%s", e)
        return 2
    log.info("Sensor configured, tared and active")

    cmd, cam = camera_command(exe, args, out_dir)
    proc = None
    watcher = None
    stats: SensorStats | None = None
    t0 = sensor_start = time.monotonic()
    t0_utc = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    try:
        log.info("MET zero: camera launch. Starting camera: %s", " ".join(cmd))
        t0 = time.monotonic()
        t0_utc = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        proc = start_recording(cmd, cam.stderr_path)
        watcher = FirstDataWatcher(cam.video_path).start()

        log.info("Capturing both for %g s (Ctrl+C to stop early). Sensor logs until the "
                 "camera finishes.", args.duration)
        sensor_start = time.monotonic()
        stats = log_sensor(driver, args.duration + STARTUP_GRACE_S, csv_path, print_hz=1.0,
                           stop_when=lambda: proc.poll() is not None, t0=t0, emit=log.info)
    finally:
        stop_driver(driver)
        if watcher is not None:
            watcher.stop()
        if proc is not None:
            if stats is not None and not stats.interrupted:
                cam.interrupted = wait_recording(proc, STARTUP_GRACE_S)
            else:
                cam.interrupted = True
                stop_process(proc)

    cam.returncode = proc.returncode
    cam.wall_s = time.monotonic() - t0
    throttled_after = get_throttled()
    log.info("Camera exited with code %s after %.2f s", cam.returncode, cam.wall_s)
    if watcher.monotonic_s is None:
        log.warning("The camera never wrote any data, so its frames cannot be placed on the shared clock")
    else:
        log.info("Camera first data %.3f s after launch (MET); sensor logged %d frames",
                 watcher.monotonic_s - t0, stats.reads)
        n = write_camera_frames(cam.pts_path, out_dir / "camera_frames.csv",
                                watcher.monotonic_s, watcher.utc, t0)
        log.info("Wrote %d camera frame times to camera_frames.csv", n)

    (out_dir / "run_info.json").write_text(json.dumps({
        "duration_s": args.duration,
        "camera_command": cmd,
        "camera_launch_utc": t0_utc,
        "camera_launch_monotonic_s": t0,
        "sensor_start_monotonic_s": sensor_start,
        "camera_first_data_monotonic_s": watcher.monotonic_s,
        "camera_first_data_utc": watcher.utc,
        "met": {"zero": "camera launch", "utc": t0_utc, "monotonic_s": t0,
                "columns": "met_s in torque_sensor.csv and camera_frames.csv"},
        "streams": {
            STREAM_TORQUE: {"file": "torque_sensor.csv", "format": "csv",
                            "source": "Bota BFT-SENS-SER-M8 over serial"},
            STREAM_CAMERA: {"file": "camera.h264", "format": "raw H.264",
                            "frame_times": ["camera_pts.txt", "camera_frames.csv"],
                            "source": "Arducam via libcamera"},
        },
        "sensor_stats": {"reads": stats.reads, "failed_reads": stats.failed_reads,
                         "invalid_frames": stats.invalid_frames, "elapsed_s": stats.elapsed_s},
        "system": sysinfo,
        "throttled_before": throttled_before,
        "throttled_after": throttled_after,
        "sensor_config": config,
    }, indent=4))

    print_stats(stats, csv_path)
    cam_ok = report(cam, args.duration)
    sensor_ok = sensor_passed(stats)
    log.info("Sensor: %s   Camera: %s", "PASS" if sensor_ok else "FAIL", "PASS" if cam_ok else "FAIL")

    # Full pass/fail report on the saved files, kept next to them.
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = validate_run.validate(out_dir, argparse.Namespace(
            unloaded=False, reference=None, axis="tz", direction=None, duration=args.duration,
            duration_tol=1.0, drift_tol_ms=validate_run.DEFAULT_DRIFT_TOL_MS,
            min_mem_gb=args.min_mem_gb))
    print(buf.getvalue())
    (out_dir / "validation.txt").write_text(buf.getvalue())

    verdict = sensor_ok and cam_ok and rc == 0
    log.info("Overall: %s. Output folder: %s", "PASS" if verdict else "FAIL", out_dir)
    return 0 if verdict else 1


if __name__ == "__main__":
    sys.exit(main())
