def sensor_read(bota_ft_sensor_driver):
#    print("ENTERING sensor_read")


#    import os
    import time
#    import signal
    import bota_driver
#    import sys

    ########################
    ## CONTROL LOOP START ##
    ########################

    # Define the example duration
#    EXAMPLE_DURATION = 10.0  # seconds

    # Define the reading frequency
#    READING_FREQUENCY = 10.0  # Hz

#    start_time = time.perf_counter()  # High-resolution start time
#    next_execution_time = start_time

#    while time.perf_counter() - start_time < EXAMPLE_DURATION and not stop_flag:
        # Read frame
    bota_frame = bota_ft_sensor_driver.read_frame()

        # Extract the data from the bota_frame
    status = bota_frame.status
    force = bota_frame.force  
    torque = bota_frame.torque
#    timestamp = bota_frame.timestamp
#    temperature = bota_frame.temperature
#    acceleration = bota_frame.acceleration
#    angular_rate = bota_frame.angular_rate

    #################################
    ## YOUR CONTROL LOOP CODE HERE ##
    #################################
#    print(force,"  ", torque)

    # Wait until next execution time
#    next_execution_time += 1.0/READING_FREQUENCY
#    sleep_time = max(0, next_execution_time - time.perf_counter())
#    time.sleep(sleep_time)

    # Transition driver from ACTIVE to INACTIVE state
#    if not bota_ft_sensor_driver.deactivate():
#        raise RuntimeError("Failed to deactivate driver")
    
    # Shutdown the driver
#    if not bota_ft_sensor_driver.shutdown():
#        raise RuntimeError("Failed to shutdown driver")

#    print("SENSOR READ - Completition WITHOUT errors.")
    
    return [status, force, torque]



