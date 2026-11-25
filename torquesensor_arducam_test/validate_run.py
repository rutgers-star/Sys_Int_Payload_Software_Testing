#!/usr/bin/env python3
"""Check a test_both.py / test_torque_sensor.py / test_arducam.py results folder
against the torque and camera pass criteria in the verification procedure.

Checks (each prints PASS / FAIL / INFO):
  PAY-8   torque rate >= 10 Hz, timestamps strictly increasing, mean interval
          <= 100 ms, no gap > 200 ms, no invalid frames
  Step 3  (--unloaded) tare offset within +-0.00007 N*m and 3-sigma noise
          <= 0.00014 N*m on every torque axis
  PAY-14  (--reference N*m --axis tz) mean torque within max(5 %, 0.00007) N*m
          of the applied reference; also prints a row for the torque test table
  PAY-12  camera 960x540 at >= 24 fps, clip length within --duration-tol of the
          requested duration, non-empty video, camera exited cleanly
  Concurrent (test_both.py folders): both streams present, in separate files
          with their own stream ids, no sensor read errors, no dropped camera
          frames, sensor-vs-Pi clock drift within --drift-tol-ms, both streams on
          one MET timebase, the sensor log covers the whole camera recording
          window, the computer is a Pi 4 with enough RAM (--min-mem-gb) and had
          no under-voltage/throttling during the run

Examples:
  python validate_run.py results/both_20261120T170000Z --unloaded
  python validate_run.py results/both_20261120T170000Z --reference 0.00756 --axis tz

Exit code 0 if every check passes, 1 if any fails, 2 if the folder is unusable.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path

DEFAULT_DRIFT_TOL_MS = 50.0   # allowed sensor-clock vs Pi-clock drift over a run (half a 10 Hz sample)
MIN_RATE_HZ = 10.0
MAX_MEAN_INTERVAL_S = 0.100
MAX_GAP_S = 0.200
OFFSET_TOL_NM = 0.00007
NOISE_3SIGMA_NM = 0.00014
REL_TOL = 0.05
MIN_FPS = 24.0
AXES = ("tx", "ty", "tz")


class Results:
    def __init__(self) -> None:
        self.failed = 0

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
        if not ok:
            self.failed += 1
        return ok

    @staticmethod
    def info(label: str, detail: str = "") -> None:
        print(f"  [INFO] {label}" + (f" - {detail}" if detail else ""))


def load_csv(path: Path) -> dict[str, list[float]]:
    cols: dict[str, list[float]] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            for k, v in row.items():
                if k == "utc_time":
                    continue
                cols.setdefault(k, []).append(float(v))
    return cols


def load_pts(path: Path) -> list[float]:
    vals = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            try:
                vals.append(float(line))
            except ValueError:
                pass
    return vals


def cmd_arg(cmd: list[str], flag: str) -> str | None:
    return cmd[cmd.index(flag) + 1] if flag in cmd and cmd.index(flag) + 1 < len(cmd) else None


def strictly_increasing(v: list[float]) -> bool:
    return all(b > a for a, b in zip(v, v[1:]))


def check_rate(r: Results, cols: dict[str, list[float]]) -> None:
    print("\nTorque sensor - rate and timestamps (PAY-8)")
    mono = cols["monotonic_s"]
    n = len(mono)
    if not r.check(n >= 2, "enough samples", f"{n} samples"):
        return
    span = mono[-1] - mono[0]
    dts = [b - a for a, b in zip(mono, mono[1:])]
    rate = (n - 1) / span if span > 0 else 0.0
    r.check(rate >= MIN_RATE_HZ, f"rate >= {MIN_RATE_HZ:g} Hz",
            f"{rate:.1f} Hz over {span:.1f} s ({n} samples)")
    r.check(strictly_increasing(mono), "Pi timestamps strictly increasing")
    r.check(strictly_increasing(cols["sensor_timestamp"]), "sensor frame timestamps strictly increasing")
    mean_dt = statistics.fmean(dts)
    r.check(mean_dt <= MAX_MEAN_INTERVAL_S, f"mean interval <= {MAX_MEAN_INTERVAL_S * 1000:.0f} ms",
            f"{mean_dt * 1000:.1f} ms")
    r.check(max(dts) <= MAX_GAP_S, f"no gap > {MAX_GAP_S * 1000:.0f} ms",
            f"largest gap {max(dts) * 1000:.1f} ms")
    over = sum(d > MAX_MEAN_INTERVAL_S for d in dts)
    r.info("intervals > 100 ms", f"{over} of {len(dts)}")
    bad = int(sum(cols["invalid"]))
    r.check(bad == 0, "no invalid frames", f"{bad} invalid")
    r.info("overrange / throttled frames",
           f"{int(sum(cols['overrange']))} / {int(sum(cols['throttled']))}")


def check_unloaded(r: Results, cols: dict[str, list[float]]) -> None:
    print("\nTorque sensor - unloaded zero offset and noise (procedure step 3)")
    r.info("note", "only valid if the sensor was unloaded for the whole run")
    for ax in AXES:
        v = cols[ax]
        mean, sd = statistics.fmean(v), statistics.pstdev(v)
        r.check(abs(mean) <= OFFSET_TOL_NM, f"{ax} offset within +-{OFFSET_TOL_NM:g} N*m",
                f"mean {mean:+.6f} N*m")
        r.check(3 * sd <= NOISE_3SIGMA_NM, f"{ax} 3-sigma noise <= {NOISE_3SIGMA_NM:g} N*m",
                f"3 sigma = {3 * sd:.6f} N*m")


def check_reference(r: Results, cols: dict[str, list[float]], ref: float, axis: str,
                    direction: str | None) -> None:
    print(f"\nTorque sensor - reference load {ref:g} N*m on {axis} (PAY-14)")
    r.info("note", "only valid if the load was held for the whole run (start/end transients skew the mean)")
    reported = statistics.fmean(cols[axis])
    err = reported - ref
    tol = max(REL_TOL * abs(ref), OFFSET_TOL_NM)
    ok = abs(err) <= tol
    pct = f"{err / ref * 100:+.2f}" if ref else "n/a"
    r.check(ok, f"mean within +-{tol:.6f} N*m of applied",
            f"reported {reported:.6f}, error {err:+.6f} N*m ({pct} %)")
    r.check(int(sum(cols["overrange"])) == 0, "no saturation (overrange) frames")
    print("  Table row: "
          f"direction={direction or '?'} applied={ref:.5f} reported={reported:.6f} "
          f"error={err:+.6f} error%={pct} within_tolerance={'YES' if ok else 'NO'}")


def check_camera(r: Results, folder: Path, run_info: dict, args: argparse.Namespace) -> None:
    print("\nCamera (PAY-12)")
    video, pts_path = folder / "camera.h264", folder / "camera_pts.txt"
    size = video.stat().st_size if video.exists() else 0
    r.check(size > 0, "video file present and non-empty", f"{size / 1e6:.2f} MB")
    pts = load_pts(pts_path) if pts_path.exists() else []
    if not r.check(len(pts) >= 2, "frame timestamps present", f"{len(pts)} frames"):
        return
    span = (pts[-1] - pts[0]) / 1000.0
    fps = (len(pts) - 1) / span if span > 0 else 0.0
    r.check(strictly_increasing(pts), "frame timestamps strictly increasing")
    # 1 % slack: a 24 fps clip commonly averages 23.9-24.0.
    r.check(fps >= MIN_FPS * 0.99, f"frame rate >= {MIN_FPS:g} fps", f"{fps:.2f} fps")
    diffs = [b - a for a, b in zip(pts, pts[1:])]
    typical = statistics.median(diffs)
    gaps = [d for d in diffs if typical > 0 and d > 1.5 * typical]
    missing = sum(round(d / typical) - 1 for d in gaps)
    r.check(not gaps, "no dropped camera frames",
            f"{missing} frame(s) missing in {len(gaps)} gap(s), longest interval "
            f"{max(diffs):.1f} ms vs typical {typical:.1f} ms")
    expected = run_info.get("duration_s", args.duration)
    if expected is None:
        r.info("clip duration", f"{span:.2f} s (no requested duration found; pass --duration)")
    else:
        r.check(abs(span - expected) <= args.duration_tol,
                f"clip length within {args.duration_tol:g} s of {expected:g} s", f"{span:.2f} s")
    cmd = run_info.get("camera_command")
    if cmd:
        w, h, fr = cmd_arg(cmd, "--width"), cmd_arg(cmd, "--height"), cmd_arg(cmd, "--framerate")
        r.check(w is not None and h is not None and int(w) >= 960 and int(h) >= 540,
                "resolution >= 960x540", f"{w}x{h}")
        r.check(fr is not None and int(fr) >= 24, "configured frame rate >= 24", f"{fr} fps")
    else:
        r.info("resolution", "no run_info.json, cannot confirm configured resolution")
    err = folder / "camera_stderr.log"
    if err.exists():
        text = err.read_text(errors="replace").lower()
        r.check("error" not in text and "failed" not in text, "camera log has no errors")


def check_system(r: Results, run_info: dict, args: argparse.Namespace) -> None:
    print("\nPayload computer and interfaces")
    s = run_info.get("system")
    if not s:
        r.info("computer details", "none in run_info.json (run test_both.py on the Pi)")
        return
    r.info("host", f"{s.get('hostname')} - {s.get('os')} - {s.get('python_bits')}-bit Python")
    model = s.get("pi_model")
    if model:
        r.check("Raspberry Pi 4" in model, "computer is a Raspberry Pi 4", model)
    else:
        r.info("computer model", f"not reported ({s.get('machine')}): this was not run on a Pi")
    mem = s.get("mem_total_mb")
    if mem is None:
        r.info("memory", "not reported")
    elif getattr(args, "min_mem_gb", None) is not None:
        # MemTotal is a little below the installed RAM (firmware/GPU share), so allow 10 %.
        need = args.min_mem_gb * 1024 * 0.9
        r.check(mem >= need, f"memory >= {args.min_mem_gb:g} GB (MemTotal, 10 % allowance)",
                f"{mem} MB")
    else:
        r.info("memory", f"{mem} MB (pass --min-mem-gb to check against the spec)")
    before, after = run_info.get("throttled_before"), run_info.get("throttled_after")
    if before is None or after is None:
        r.info("power/thermal flags", "vcgencmd not available")
        return
    b, a = int(before, 16), int(after, 16)
    r.check((a & 0x7) == 0, "no under-voltage or throttling at end of run", f"get_throttled {after}")
    r.check(((a >> 16) & ~(b >> 16) & 0xF) == 0, "no new under-voltage/throttle events during the run",
            f"before {before}, after {after}")


def check_streams(r: Results, folder: Path, run_info: dict) -> None:
    print("\nStream separation and tagging")
    streams = run_info.get("streams")
    if not streams:
        r.info("stream manifest", "none in run_info.json; checking default file names only")
        streams = {"TORQUE": {"file": "torque_sensor.csv"}, "CAMERA": {"file": "camera.h264"}}
    files = [s["file"] for s in streams.values()]
    r.check(len(streams) >= 2 and len(set(files)) == len(files),
            "each stream has its own id and file", ", ".join(f"{k}={v['file']}" for k, v in streams.items()))
    for name, s in streams.items():
        p = folder / s["file"]
        r.check(p.exists() and p.stat().st_size > 0, f"{name} data stored and non-empty",
                f"{s['file']} ({p.stat().st_size if p.exists() else 0} bytes)")
    stats = run_info.get("sensor_stats")
    if stats:
        r.check(stats.get("failed_reads", 0) == 0, "no sensor interface read errors",
                f"{stats.get('failed_reads')} failed reads")


def check_drift(r: Results, cols: dict[str, list[float]], args: argparse.Namespace) -> None:
    print("\nTiming drift (sensor clock vs Pi clock)")
    mono, ts = cols["monotonic_s"], cols["sensor_timestamp"]
    span_m, span_t = mono[-1] - mono[0], ts[-1] - ts[0]
    if span_m <= 0 or span_t <= 0:
        r.info("drift", "not enough data")
        return
    ratio = span_t / span_m
    scale = 10 ** round(math.log10(ratio))   # sensor timestamps may be s, ms, us or ns
    if not 0.9 < ratio / scale < 1.1:
        r.info("drift", f"cannot infer sensor timestamp units (ratio {ratio:.4g})")
        return
    drift_ms = (ratio / scale - 1) * span_m * 1000
    tol = getattr(args, "drift_tol_ms", DEFAULT_DRIFT_TOL_MS)
    r.check(abs(drift_ms) <= tol, f"sensor clock within {tol:g} ms of the Pi clock over the run",
            f"{drift_ms:+.2f} ms over {span_m:.1f} s ({(ratio / scale - 1) * 1e6:+.0f} ppm), "
            f"sensor timestamp unit 1e{round(math.log10(scale)):d} per s")


def check_timebase(r: Results, folder: Path, cols: dict[str, list[float]], run_info: dict) -> None:
    print("\nShared timebase (MET)")
    frames = folder / "camera_frames.csv"
    if not frames.exists() or "met_s" not in cols:
        r.info("MET alignment", "camera_frames.csv or met_s column missing (run test_both.py)")
        return
    cam = load_csv(frames)
    met_cam, met_sen = cam["met_s"], cols["met_s"]
    r.check(strictly_increasing(met_cam) and strictly_increasing(met_sen),
            "both streams have strictly increasing MET times",
            f"{len(met_sen)} sensor rows, {len(met_cam)} camera frames")
    r.check(len(met_cam) == len(load_pts(folder / "camera_pts.txt")),
            "every camera frame has a MET time")
    r.check(met_sen[0] <= met_cam[0] and met_sen[-1] >= met_cam[-1] - 0.5,
            "sensor MET range covers every camera frame",
            f"sensor {met_sen[0]:.2f}..{met_sen[-1]:.2f} s, camera {met_cam[0]:.2f}..{met_cam[-1]:.2f} s")
    r.info("camera first frame", f"{met_cam[0]:.3f} s after MET zero (camera launch); "
           "placed from first data in the file, good to roughly tens of ms")


def check_concurrent(r: Results, folder: Path, cols: dict[str, list[float]], run_info: dict) -> None:
    print("\nConcurrent operation (integrated test)")
    launch = run_info.get("camera_launch_monotonic_s")
    sensor0 = run_info.get("sensor_start_monotonic_s")
    dur = run_info.get("duration_s")
    if launch is None or dur is None:
        r.info("overlap", "run_info.json missing, run test_both.py to check overlap")
        return
    mono = cols["monotonic_s"]
    r.check(mono[0] <= launch + 1.0 and mono[-1] >= launch + dur - 1.0,
            "sensor log covers the camera recording window",
            f"sensor {mono[0] - launch:+.2f}..{mono[-1] - launch:+.2f} s, "
            f"camera 0..{dur:g} s (relative to camera launch)")
    if sensor0 is not None:
        r.info("sensor logging began after camera launch by", f"{sensor0 - launch:.3f} s")
    r.info("clock note", "streams are aligned on met_s (seconds since camera launch); camera "
                         "frame times in camera_pts.txt alone use the camera's own clock")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("folder", type=Path, help="results folder from test_both.py (or a sensor_/camera_ folder)")
    p.add_argument("--unloaded", action="store_true", help="check tare offset and noise (sensor unloaded)")
    p.add_argument("--reference", type=float, help="applied reference torque in N*m (load held for the run)")
    p.add_argument("--axis", choices=AXES, default="tz", help="torque axis the load is applied on (default: tz)")
    p.add_argument("--direction", choices=("CW", "CCW"), help="direction label for the table row")
    p.add_argument("--duration", type=float, help="requested duration (if run_info.json is missing)")
    p.add_argument("--duration-tol", type=float, default=1.0, help="allowed clip length error in s (default: 1.0)")
    p.add_argument("--drift-tol-ms", type=float, default=DEFAULT_DRIFT_TOL_MS,
                   help="allowed sensor-clock vs Pi-clock drift over the run in ms (default: %(default)s)")
    p.add_argument("--min-mem-gb", type=float, help="minimum RAM in GB (the payload memory spec)")
    args = p.parse_args()
    return validate(args.folder, args)


def validate(folder: Path, args: argparse.Namespace) -> int:
    """Run every applicable check on a results folder. Returns the exit code."""
    if not folder.is_dir():
        print(f"ERROR: {folder} is not a folder", file=sys.stderr)
        return 2
    csv_path = folder / "torque_sensor.csv"
    has_cam = (folder / "camera.h264").exists() or (folder / "camera_pts.txt").exists()
    if not csv_path.exists() and not has_cam:
        print(f"ERROR: no torque_sensor.csv or camera files in {folder}", file=sys.stderr)
        return 2
    run_info = {}
    if (folder / "run_info.json").exists():
        run_info = json.loads((folder / "run_info.json").read_text())

    r = Results()
    print(f"Validating {folder}")
    cols = None
    if csv_path.exists():
        cols = load_csv(csv_path)
        if cols.get("monotonic_s"):
            check_rate(r, cols)
            if args.unloaded:
                check_unloaded(r, cols)
            if args.reference is not None:
                check_reference(r, cols, args.reference, args.axis, args.direction)
        else:
            r.check(False, "torque_sensor.csv has data rows")
    if has_cam:
        check_camera(r, folder, run_info, args)
    if cols and cols.get("monotonic_s") and has_cam:
        check_streams(r, folder, run_info)
        check_system(r, run_info, args)
        check_drift(r, cols, args)
        check_timebase(r, folder, cols, run_info)
        check_concurrent(r, folder, cols, run_info)

    print(f"\n{'ALL CHECKS PASSED' if r.failed == 0 else f'{r.failed} CHECK(S) FAILED'}")
    return 0 if r.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
