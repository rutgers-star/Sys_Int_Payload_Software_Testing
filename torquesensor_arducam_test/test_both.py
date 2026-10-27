#!/usr/bin/env python3
"""Run the torque sensor logging and the camera recording at the same time.

Confirms both work together on one Raspberry Pi. The sensor is started and
tared first, then the camera is launched as a background process, and the
sensor is logged in this process while the camera records. Both outputs go
into one timestamped folder.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from test_arducam import (
    STARTUP_GRACE_S, CameraError, add_camera_args, camera_command,
    find_camera_command, report, start_recording, stop_process, wait_recording,
)
from test_torque_sensor import (
    DEFAULT_OUT_DIR, SensorError, SensorStats, add_sensor_args, log_sensor,
    prepare_config, print_stats, sensor_passed, start_driver, stop_driver, utc_stamp,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-d", "--duration", type=float, default=10.0,
                        help="seconds to run both (default: %(default)s)")
    add_sensor_args(parser)
    add_camera_args(parser)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR,
                        help="base folder for results (default: %(default)s)")
    args = parser.parse_args()

    out_dir = args.out_dir / f"both_{utc_stamp()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "torque_sensor.csv"

    # Check both devices before starting either, so a missing camera tool
    # does not leave the sensor half set up.
    try:
        exe = find_camera_command()
        config_used = prepare_config(args.config, args.port, out_dir, args.sinc_length)
    except (CameraError, SensorError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print("Starting sensor ...")
    try:
        driver = start_driver(config_used)
    except SensorError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    cmd, cam = camera_command(exe, args, out_dir)
    proc = None
    stats: SensorStats | None = None
    try:
        print("Starting camera:", " ".join(cmd))
        cam_launch_utc = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        cam_launch = time.monotonic()
        proc = start_recording(cmd, cam.stderr_path)

        print(f"Running both for {args.duration:g} s (Ctrl+C to stop early).")
        sensor_start = time.monotonic()
        stats = log_sensor(driver, args.duration, csv_path)
    finally:
        stop_driver(driver)
        if proc is not None:
            if stats is not None and not stats.interrupted:
                cam.interrupted = wait_recording(proc, args.duration + STARTUP_GRACE_S)
            else:
                cam.interrupted = True
                stop_process(proc)

    cam.returncode = proc.returncode
    cam.wall_s = time.monotonic() - cam_launch

    (out_dir / "run_info.json").write_text(json.dumps({
        "duration_s": args.duration,
        "camera_command": cmd,
        "camera_launch_utc": cam_launch_utc,
        "camera_launch_monotonic_s": cam_launch,
        "sensor_start_monotonic_s": sensor_start,
    }, indent=4))

    print_stats(stats, csv_path)
    cam_ok = report(cam, args.duration)
    sensor_ok = sensor_passed(stats)

    print("\n--- Combined ---")
    print(f"Sensor: {'PASS' if sensor_ok else 'FAIL'}   Camera: {'PASS' if cam_ok else 'FAIL'}")
    print(f"Output folder: {out_dir}")
    return 0 if sensor_ok and cam_ok else 1


if __name__ == "__main__":
    sys.exit(main())
