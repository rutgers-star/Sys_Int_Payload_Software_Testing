#!/usr/bin/env python3
"""Standalone test for the Bota torque sensor (BFT-SENS-SER-M8) over USB serial.

Configures, tares and activates the driver, reads frames for a fixed time,
prints readings at about 10 Hz, logs every sample to a CSV and reports the
achieved sample rate. The driver is always deactivated and shut down.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import platform
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / "bota_binary_gen0.json"
DEFAULT_OUT_DIR = HERE / "results"

# Value used in Bota's sample bota_binary_gen0.json. The payload config uses 2,
# which has not been confirmed on the sensor.
BOTA_SAMPLE_SINC_LENGTH = 128

CSV_HEADER = [
    "utc_time", "monotonic_s", "elapsed_s", "sensor_timestamp",
    "status_val", "invalid", "overrange", "throttled",
    "fx", "fy", "fz", "tx", "ty", "tz", "temperature",
]


class SensorError(Exception):
    """A sensor setup problem with a message meant for the operator."""


@dataclass
class SensorStats:
    reads: int = 0
    failed_reads: int = 0
    invalid_frames: int = 0
    elapsed_s: float = 0.0
    interrupted: bool = False

    @property
    def rate_hz(self) -> float:
        return self.reads / self.elapsed_s if self.elapsed_s > 0 else 0.0


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_config(config_path: Path, port: str | None = None,
                sinc_length: int | None = None) -> dict[str, Any]:
    with open(config_path) as f:
        config = json.load(f)
    if port:
        config["driver_config"]["communication_interface_params"]["com_port"] = port
    if sinc_length is not None:
        config["driver_config"]["sensor_operation_params"]["sinc_length"] = sinc_length
    return config


def config_port(config: dict[str, Any]) -> str:
    return config["driver_config"]["communication_interface_params"]["com_port"]


def sinc_hint(config_path: Path) -> str:
    """Suggest the sample sinc_length when the configured one may be what failed."""
    try:
        sinc = load_config(config_path)["driver_config"]["sensor_operation_params"]["sinc_length"]
    except (OSError, KeyError, ValueError):
        return ""
    if sinc == BOTA_SAMPLE_SINC_LENGTH:
        return ""
    return (
        f"\n  The config has sinc_length = {sinc}. If the driver output above says "
        f"'Invalid sinc length', change sinc_length to {BOTA_SAMPLE_SINC_LENGTH} "
        f"in bota_binary_gen0.json,\n  or rerun with --sinc-length {BOTA_SAMPLE_SINC_LENGTH}."
    )


def check_port(port: str) -> None:
    if os.path.exists(port):
        return
    candidates = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
    hint = ", ".join(candidates) if candidates else "none found"
    raise SensorError(
        f"Serial port {port} does not exist. Is the sensor plugged in?\n"
        f"  Available serial ports: {hint}\n"
        f"  Pass a different port with --port, e.g. --port /dev/ttyACM1"
    )


def prepare_config(config_path: Path, port: str | None, out_dir: Path,
                   sinc_length: int | None = None) -> Path:
    """Apply overrides, check the port, and save the config used next to the results."""
    config = load_config(config_path, port, sinc_length)
    check_port(config_port(config))
    used = out_dir / "bota_config_used.json"
    used.write_text(json.dumps(config, indent=4))
    return used


def start_driver(config_path: Path) -> Any:
    """Create, configure, tare and activate the driver. Returns it ACTIVE."""
    try:
        import bota_driver
    except ImportError as e:
        msg = "bota_driver is not installed. Run: pip install -r requirements.txt"
        # bota-driver only ships 64-bit wheels. Check Python's own word size, since
        # 32-bit Raspberry Pi OS can run a 64-bit kernel that reports aarch64.
        if sys.maxsize <= 2**32:
            msg += (f"\n  This Python is 32-bit ({platform.machine()}). bota-driver needs a "
                    f"64-bit OS: install 64-bit Raspberry Pi OS (works on Pi 3 and Pi 4).")
        raise SensorError(msg) from e

    # The constructor already opens the serial port and raises RuntimeError on failure.
    try:
        driver = bota_driver.BotaDriver(str(config_path))
    except RuntimeError as e:
        raise SensorError(f"Driver could not open the sensor: {e}{sinc_hint(config_path)}") from e

    steps = [("configure", driver.configure), ("tare", driver.tare), ("activate", driver.activate)]
    for name, step in steps:
        try:
            ok = step()
        except Exception as e:
            ok = False
            print(f"  {name}() raised {type(e).__name__}: {e}", file=sys.stderr)
        if not ok:
            # Not active yet, so only shutdown is needed.
            stop_driver(driver, active=False)
            hint = sinc_hint(config_path) if name == "configure" else ""
            raise SensorError(
                f"Driver failed to {name}. Check the config file, the port, "
                f"and that no other program is using the sensor.{hint}"
            )
    return driver


def stop_driver(driver: Any, active: bool = True) -> None:
    """Deactivate (if active) and shut down, reporting but not raising errors."""
    if active:
        try:
            if not driver.deactivate():
                print("WARNING: driver.deactivate() returned False", file=sys.stderr)
        except Exception as e:
            print(f"WARNING: driver.deactivate() raised {e}", file=sys.stderr)
    try:
        if not driver.shutdown():
            print("WARNING: driver.shutdown() returned False", file=sys.stderr)
    except Exception as e:
        print(f"WARNING: driver.shutdown() raised {e}", file=sys.stderr)


def log_sensor(driver: Any, duration_s: float, csv_path: Path,
               print_hz: float = 10.0, quiet: bool = False) -> SensorStats:
    """Read frames for duration_s, writing every frame to csv_path.

    Uses read_frame_blocking() so each loop iteration is one new frame. With
    read_frame() the loop would spin and could return the same frame more
    than once, which inflates the sample count. If the sensor stops
    streaming, a blocking read waits for data, so the loop can overrun
    duration_s. Ctrl+C ends the loop early and the partial stats are returned.
    """
    stats = SensorStats()
    print_period = 1.0 / print_hz
    next_print = 0.0
    start = time.monotonic()

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        try:
            while time.monotonic() - start < duration_s:
                try:
                    frame = driver.read_frame_blocking()
                except Exception as e:
                    stats.failed_reads += 1
                    if stats.failed_reads <= 5:
                        print(f"Read failed: {type(e).__name__}: {e}", file=sys.stderr)
                    continue

                now = time.monotonic()
                elapsed = now - start
                s = frame.status
                fx, fy, fz = frame.force
                tx, ty, tz = frame.torque
                stats.reads += 1
                if s.invalid:
                    stats.invalid_frames += 1

                writer.writerow([
                    datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                    f"{now:.6f}", f"{elapsed:.6f}", frame.timestamp,
                    int(s.val), int(s.invalid), int(s.overrange), int(s.throttled),
                    fx, fy, fz, tx, ty, tz, frame.temperature,
                ])

                if not quiet and elapsed >= next_print:
                    next_print = elapsed + print_period
                    flags = "".join(c for c, on in (("I", s.invalid), ("O", s.overrange),
                                                     ("T", s.throttled)) if on) or "ok"
                    print(f"{elapsed:7.2f}s  status={flags:<3}  "
                          f"F=[{fx:8.3f} {fy:8.3f} {fz:8.3f}] N  "
                          f"T=[{tx:8.4f} {ty:8.4f} {tz:8.4f}] Nm")
        except KeyboardInterrupt:
            stats.interrupted = True
        finally:
            stats.elapsed_s = time.monotonic() - start
    return stats


def print_stats(stats: SensorStats, csv_path: Path) -> None:
    print("\n--- Torque sensor results ---")
    if stats.interrupted:
        print("(stopped early by Ctrl+C)")
    print(f"Duration:       {stats.elapsed_s:.2f} s")
    print(f"Reads:          {stats.reads}")
    print(f"Failed reads:   {stats.failed_reads}")
    print(f"Invalid frames: {stats.invalid_frames}")
    print(f"Sample rate:    {stats.rate_hz:.1f} Hz")
    print(f"CSV:            {csv_path}")


def sensor_passed(stats: SensorStats) -> bool:
    return stats.reads > 0 and stats.failed_reads == 0


def add_sensor_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                        help="Bota driver JSON config (default: %(default)s)")
    parser.add_argument("--port", help="serial port, overrides com_port in the config "
                                       "(config default: /dev/ttyACM0)")
    parser.add_argument("--sinc-length", type=int,
                        help="overrides sinc_length in the config (config default: 2, "
                             f"Bota's sample uses {BOTA_SAMPLE_SINC_LENGTH})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-d", "--duration", type=float, default=10.0,
                        help="seconds to read for (default: %(default)s)")
    add_sensor_args(parser)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR,
                        help="base folder for results (default: %(default)s)")
    args = parser.parse_args()

    out_dir = args.out_dir / f"sensor_{utc_stamp()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "torque_sensor.csv"

    try:
        config_used = prepare_config(args.config, args.port, out_dir, args.sinc_length)
        print(f"Starting sensor using {config_used} ...")
        driver = start_driver(config_used)
    except SensorError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print(f"Sensor active. Reading for {args.duration:g} s (Ctrl+C to stop early).")
    try:
        stats = log_sensor(driver, args.duration, csv_path)
    finally:
        stop_driver(driver)

    print_stats(stats, csv_path)
    return 0 if sensor_passed(stats) else 1


if __name__ == "__main__":
    sys.exit(main())
