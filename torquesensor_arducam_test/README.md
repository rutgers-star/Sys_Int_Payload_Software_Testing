# Torque sensor and Arducam hardware tests

Standalone tests for the Bota torque sensor (BFT-SENS-SER-M8, SN000853) and the
Arducam on a Raspberry Pi 4B. They need only the sensor, the camera and the Pi:
no DCE, reaction wheels, Maxon motor or IMU, and nothing from the PayloadSoftware repo.

| Script | What it does |
| --- | --- |
| `test_torque_sensor.py` | Configures, tares and activates the sensor, reads it for N seconds, prints Fx Fy Fz Tx Ty Tz at about 10 Hz, logs every sample to CSV, reports the sample rate and failed reads. |
| `test_arducam.py` | Records an N second black-and-white 960x540 24 fps H.264 clip with frame timestamps and checks the output. |
| `test_both.py` | Runs both at the same time for N seconds and writes both outputs to one folder. |

All three default to 10 seconds and write to `results/` inside this folder
(ignored by git).

## Hardware setup

- **Torque sensor:** plug the sensor's USB serial cable into the Pi. It normally
  shows up as `/dev/ttyACM0`; check with `ls /dev/ttyACM* /dev/ttyUSB*`. Your user
  must be in the `dialout` group (`sudo usermod -aG dialout $USER`, then log out and back in).
  Keep the sensor unloaded and still when a test starts, because the scripts tare
  (zero) it at startup.
- **Camera:** connect the Arducam ribbon cable to the Pi's CAMERA port with the Pi
  powered off. Check it is detected with `rpicam-hello --list-cameras` (or
  `libcamera-hello --list-cameras` on older images). Some Arducam modules need a
  `dtoverlay=` line in `/boot/firmware/config.txt`; see Arducam's docs for your module.

## Install

Use 64-bit Raspberry Pi OS (Bookworm or later). `bota-driver` only ships Linux
wheels for 64-bit ARM (aarch64) and x86_64, so it will not install on 32-bit
Raspberry Pi OS.

```bash
sudo apt install rpicam-apps          # camera tools, usually already installed
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
python3 test_both.py -d 20
```

Run any script with `--help` for all options. Ctrl+C stops early; the sensor is
still deactivated and shut down, and the camera is asked to finish its file.

`--port` overrides `com_port` in `bota_binary_gen0.json` without editing it.
The config actually used is saved as `bota_config_used.json` in the results folder.

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
- If the camera tool rejects an option (for example `--save-pts` on a version of
  rpicam-apps that dropped it), the error is in `camera_stderr.log` and is
  printed in the summary.
