import csv
import time
from DummyDataTest import fake_imu_data
# Data packet test

with open("imu_log.csv", mode="w", newline="") as file:
    writer = csv.writer(file)
    writer.writerow(["time", "yaw", "pitch", "roll"])
    start_time = time.time()
    
    try:
        while True:
            t = time.time() - start_time
            # Write and return simulated data
           
            yaw, pitch, roll = fake_imu_data(t)
            writer.writerow([t, yaw, pitch, roll])

            print(f"{t:.2f}, {yaw:.2f}, {pitch:.2f}, {roll:.2f}")
            time.sleep(0.01)

    except KeyboardInterrupt:
        print("End")