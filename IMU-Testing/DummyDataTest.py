import math

def fake_imu_data(t):
    # Yaw has constant spin
    spin_rate = 90  # deg/sec
    yaw = (spin_rate * t) % 360

    # Simulate slight wobble for pitch and roll
    pitch = 5 * math.sin(2 * math.pi * 0.5 * t)
    roll  = 5 * math.cos(2 * math.pi * 0.5 * t)

    return yaw, pitch, roll
