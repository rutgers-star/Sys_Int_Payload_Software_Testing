# Torque sensor and Arducam hardware tests

Standalone tests for the Bota torque sensor (BFT-SENS-SER-M8, SN000853) and the
Arducam on a Raspberry Pi 4B or Pi 3 (64-bit OS required, see
[Install](#install)). They need only the sensor, the camera and the Pi:
no DCE, reaction wheels, Maxon motor or IMU, and nothing from the PayloadSoftware repo.

| Script | What it does |
| --- | --- |
| `test_torque_sensor.py` | Configures, tares and activates the sensor, reads it for N seconds, prints Fx Fy Fz Tx Ty Tz at about 10 Hz, logs every sample to CSV, reports the sample rate and failed reads. |
| `test_arducam.py` | Records an N second black-and-white 960x540 24 fps H.264 clip with frame timestamps and checks the output. |
| `test_both.py` | **Simultaneous capture.** Runs both at the same time (20 s by default), logs the run, keeps the two streams in separate files on one shared clock, and validates the result. See [Simultaneous capture](#simultaneous-capture-20-s). |
| `validate_run.py` | Checks a results folder against the pass criteria (10 Hz, gaps, tare noise, reference torque tolerance, camera 960x540 / 24 fps / duration, both streams overlap). See [Validate](#validate-a-run). |

The sensor and camera tests default to 10 seconds and `test_both.py` to 20.
All write to `results/` inside this folder (ignored by git).

## Matches the payload software

The tests are set up to behave like the flight code in
[rutgers-star/PayloadSoftware](https://github.com/rutgers-star/PayloadSoftware):

- **Bota config:** `bota_binary_gen0.json` here is a copy of the payload's file
  (BFT-SENS-SER-M8, SN000853, `/dev/ttyACM0`, 460800 baud, `sinc_length` 64, zero
  wrench offsets). The same bring-up order is used: configure, tare, activate.
  Every run compares the config it uses with these values and prints a warning
  for any difference (for example if you pass `--sinc-length`). The port can be
  overridden with `--port` without counting as a difference.
- **Camera:** recorded with `libcamera-vid` (the libcamera app, as in the
  payload's `camera_control.py`) using the payload's options: 960x540, 24 fps,
  `--saturation 0`, `--exposure long`, `--vflip`, `--save-pts`. On Bookworm the
  tool is called `rpicam-vid`, with `libcamera-vid` kept as a link; either is
  found, `libcamera-vid` first. Before recording, the tests ask libcamera
  (`libcamera-hello --list-cameras`) for the camera and stop with a clear message
  if it sees none.

One difference: the payload reads with the non-blocking `read_frame()` every
25 ms; these tests use `read_frame_blocking()` so every sensor frame is logged
exactly once.

## Hardware setup

- **Torque sensor:** plug the sensor's USB serial cable into the Pi. It normally
  shows up as `/dev/ttyACM0`; check with `ls /dev/ttyACM* /dev/ttyUSB*`. Your user
  must be in the `dialout` group (`sudo usermod -aG dialout $USER`, then log out and back in).
  Keep the sensor unloaded and still when a test starts, because the scripts tare
  (zero) it at startup.
- **Camera:** connect the Arducam ribbon cable to the Pi's CAMERA port with the Pi
  powered off. Check it is detected with `rpicam-hello --list-cameras` (or
  `libcamera-hello --list-cameras` on older images). Some Arducam modules need a
  `dtoverlay=` line in `/boot/firmware/config.txt` (`/boot/config.txt` on
  Bullseye); see Arducam's docs for your module. On Bullseye, the legacy camera
  option in `raspi-config` must be off, or libcamera will not see the camera.
- **Power:** use the official supply (2.5 A for a Pi 3, 3 A for a Pi 4). The
  sensor and camera both draw from the Pi, and an undervolted Pi can drop USB.

## Install

Use **64-bit** Raspberry Pi OS, Bullseye or Bookworm. This works on both the
Pi 3 and the Pi 4. `bota-driver` only ships 64-bit wheels (aarch64 and x86_64),
so `pip install` fails on 32-bit Raspberry Pi OS, which many Pi 3 SD cards still
run. Check with `getconf LONG_BIT` (must print `64`). If you run the sensor
test on a 32-bit OS anyway, it tells you so.

The camera tools are `rpicam-*` on Bookworm (package `rpicam-apps`) and
`libcamera-*` on Bullseye (package `libcamera-apps`). The camera test finds
either one. This is the same tool the payload code calls as `libcamera-vid`.

```bash
sudo apt install rpicam-apps          # on Bullseye: sudo apt install libcamera-apps
cd torquesensor_arducam_test
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The camera test uses only the standard library and the `rpicam-vid` /
`libcamera-vid` command, so it does not need the venv.

## Run

```bash
python3 test_torque_sensor.py                 # 10 s on /dev/ttyACM0
python3 test_torque_sensor.py -d 30 --port /dev/ttyACM1
python3 test_arducam.py                       # 10 s clip
python3 test_arducam.py -d 5 --no-vflip
python3 test_both.py                          # simultaneous capture, 20 s
```

Run any script with `--help` for all options. Ctrl+C stops early; the sensor is
still deactivated and shut down, and the camera is asked to finish its file.

`--port` overrides `com_port` and `--sinc-length` overrides `sinc_length` in
`bota_binary_gen0.json` without editing it. The config actually used is saved as
`bota_config_used.json` in the results folder.

### Simultaneous capture (20 s)

This is the integrated test: torque sensor and camera acquiring at the same time,
as in a real experiment. Run it on the payload Pi itself.

1. Do the [Hardware setup](#hardware-setup) and [Install](#install). With the
   venv active, check the camera is visible to libcamera:
   `libcamera-hello --list-cameras` (or `rpicam-hello --list-cameras`).
2. Leave the sensor unloaded and still (it is tared at start), then run:

   ```bash
   cd torquesensor_arducam_test
   source .venv/bin/activate
   python3 test_both.py                      # 20 s (-d N for another length)
   python3 test_both.py --min-mem-gb 4       # also check RAM against the payload spec
   ```

   Add `--port /dev/ttyACM1` if the sensor is not on `ttyACM0`. Ctrl+C stops
   early and still shuts everything down cleanly.
3. The run prints a one-line-per-second log of the sensor while the camera
   records, then a PASS/FAIL report. Exit code `0` means every check passed.
   Everything is saved in `results/both_<UTC time>/`:

   | File | Contents |
   | --- | --- |
   | `torque_sensor.csv` | Stream `TORQUE`: every sensor frame (UTC, Pi monotonic, `met_s`, sensor timestamp, status flags, F, T, temperature) |
   | `camera.h264` | Stream `CAMERA`: the video |
   | `camera_pts.txt` | Stream `CAMERA`: camera frame times in ms |
   | `camera_frames.csv` | Stream `CAMERA`: each frame placed on the shared clock (UTC, monotonic, `met_s`) |
   | `run.log` | Timestamped log of the whole run for both streams: Pi model/RAM, config check, camera launch, 1 Hz sensor readings, exit codes, results |
   | `run_info.json` | Stream manifest, shared clock zero, camera command, sensor config used, Pi details, power flags |
   | `validation.txt` | The PASS/FAIL report |
   | `bota_config_used.json`, `camera_stderr.log` | Exact sensor config and the camera tool's log |

**What the run checks** (against the verification procedure):

| Procedure step | Check |
| --- | --- |
| Dedicated Pi 4B with enough memory | Reports model, RAM and OS; fails if the model is not a Pi 4, or RAM is under `--min-mem-gb`. Without `--min-mem-gb` the RAM is only reported, so set it to the spec. |
| Both interfaces active at once | Camera must be seen by libcamera, the sensor must configure, tare and activate, and the camera must record while the sensor logs |
| Simultaneous acquisition | Camera and sensor start together; the sensor log covers the whole recording |
| Distinct, not merged | Separate files with their own stream ids (`TORQUE`, `CAMERA`) in `run_info.json` |
| Dropped data, drift, interface errors | Sensor rate, gaps over 200 ms, invalid frames and failed reads; missing camera frames and frame rate; sensor-clock vs Pi-clock drift (50 ms allowed, `validate_run.py --drift-tol-ms`); camera exit code and log; Pi under-voltage/throttling flags |
| Consistent timestamps | Both streams carry UTC, Pi monotonic time and `met_s`, seconds since camera launch (the shared MET zero). Camera frames are placed on it from when the video file first has data, so they are good to roughly tens of ms; the camera's own timestamps alone are on its own clock. |

Not automated: confirming the payload Pi is a separate unit from the main OBC is
a physical check, and the Pi 4B memory spec number has to come from the
requirements (pass it as `--min-mem-gb`; `MemTotal` reads a little below the
installed RAM, so the check allows 10 %). For the full-length experiment cycle
run `python3 test_both.py -d <seconds>` and read the same report.

### Validate a run

`validate_run.py` reads a results folder and prints PASS/FAIL per criterion. It
only needs the standard library, so it also runs on a laptop after you copy the
folder off the Pi.

```bash
python3 test_both.py -d 500                                   # full-length 500 s run, sensor unloaded
python3 validate_run.py results/both_<time> --unloaded        # tare offset and 3-sigma noise
python3 test_both.py -d 30                                    # hold a reference load for the whole run
python3 validate_run.py results/both_<time> --reference 0.00756 --axis tz --direction CW
```

`--reference` prints a row for the torque test table (applied, reported, error,
error %, within tolerance). The tolerance is the larger of 5 % and 0.00007 N*m.
The `--unloaded` and `--reference` checks use the whole run, so the sensor must
be unloaded or held at the reference for all of it. The sweep (procedure step 6)
is one run per load point. Use `--axis` for whichever torque axis your fixture loads.

### If the sensor fails to configure

`sinc_length` is `64`, the payload's value. If the driver prints
`Invalid sinc length`, the test says so. Bota's own sample config uses `128`, so
rerun with `--sinc-length 128` to see whether the sensor accepts that. If it does,
the payload config has the same problem and the payload team should be told: do
not just change it here, because then the test no longer matches the flight
software (the run warns about any difference). The sinc length also sets the
sensor's sample rate, so check the rate in the summary.

## Reading the results

Each run makes a folder named by UTC start time, e.g. `results/sensor_20261027T170000Z/`,
`results/camera_.../` or `results/both_.../`.

Exit codes: `0` pass, `1` ran but something failed (see the summary), `2` could
not start (missing port, driver error, no camera tool).

### Torque sensor

The summary shows duration, reads, failed reads, frames flagged invalid, and the
achieved sample rate. A healthy run has 0 failed reads, 0 invalid frames and a
steady rate. With the sensor unloaded after tare, forces should sit near 0 N and
torques near 0 Nm.

`torque_sensor.csv` has one row per frame:

| Column | Meaning |
| --- | --- |
| `utc_time` | Wall clock time on the Pi, ISO 8601 UTC |
| `monotonic_s` | Pi monotonic clock, for lining up with other data from the same boot |
| `elapsed_s` | Seconds since logging started |
| `sensor_timestamp` | The sensor's own frame timestamp |
| `status_val`, `invalid`, `overrange`, `throttled` | Frame status flags from the driver (1 = set) |
| `fx`, `fy`, `fz` | Force, N |
| `tx`, `ty`, `tz` | Torque, Nm |
| `temperature` | Sensor temperature |

The live printout shows `status=ok`, or the letters `I` (invalid), `O` (overrange)
and `T` (throttled) for any flags that are set.

### Camera

- `camera.h264`: the raw H.264 stream. It has no container, so some players show
  the wrong length. Convert it with
  `ffmpeg -framerate 24 -i camera.h264 -c copy camera.mp4`, or play it with `ffplay camera.h264`.
- `camera_pts.txt`: one timestamp in ms per frame. The summary uses it to report
  frame count, clip duration and average fps. Expect about 24 fps and a clip
  slightly shorter than requested, because the camera takes a moment to start.
- `camera_stderr.log`: the camera tool's log. It is printed automatically when
  the test fails.

The camera is run with `--width 960 --height 540 --framerate 24 --saturation 0
--exposure long --vflip --save-pts`, matching the payload settings.

### Both

`test_both.py` writes all of the above into one `both_<time>/` folder plus
`run_info.json`, which records the camera command and when the camera was
launched (UTC and monotonic) relative to the sensor start. Camera frame
timestamps use the camera's own clock, so line the two streams up using
`run_info.json` and the CSV `monotonic_s` column, allowing for the camera's
startup delay. The final `Sensor: PASS/FAIL  Camera: PASS/FAIL` line is the result.

## Notes

- The sensor test uses `read_frame_blocking()`, so each loop iteration gets one
  new frame and the sample count is the real frame count (`read_frame()` does not
  wait, so a fast loop could read the same frame twice). If the sensor stops
  sending data, the blocking read waits for it, so a run can last longer than
  `--duration`, and Ctrl+C may not take effect until the next frame arrives.
- On a Pi 3, the slower CPU has to keep up with every sensor frame while the
  camera records. Compare the sample rate from `test_torque_sensor.py` alone with
  the one from `test_both.py`. If the combined rate is clearly lower, or frames
  show `T` (throttled), the Pi is falling behind.
- If the camera tool rejects an option (for example `--save-pts` on a version of
  rpicam-apps that dropped it), the error is in `camera_stderr.log` and is
  printed in the summary.
