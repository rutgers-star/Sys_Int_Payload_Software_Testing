def sensor_start():
#    print("ENTERING sensor_start")


    import os
    #import time
    #import signal
    import bota_driver
    #import sys

#################
## CONFIG FILE ##
#################

# Bota Serial Binary Gen0
    cwd = os.getcwd()
    config_path = os.path.join(cwd, "bota_binary_gen0.json")
#    print(config_path)

##################
## DRIVER USAGE ##
##################

    try:
    # Create driver instance
        bota_ft_sensor_driver = bota_driver.BotaDriver(config_path)
#        print( bota_ft_sensor_driver)
    
    # Transition driver from UNCONFIGURED to INACTIVE state
        if not bota_ft_sensor_driver.configure():
            raise RuntimeError("Failed to configure driver")

    # Uncomment to tare the sensor
        if not bota_ft_sensor_driver.tare():
            raise RuntimeError("Failed to tare sensor")

    # Transition driver from INACTIVE to ACTIVE state
        if not bota_ft_sensor_driver.activate():
            raise RuntimeError("Failed to activate driver")

#    finally:
#       print("Done Trying in sensor_start")

    except:    
       print("Bota sensor failed to start")
  
#    print("EXITING sensor_start")
    
    return bota_ft_sensor_driver
