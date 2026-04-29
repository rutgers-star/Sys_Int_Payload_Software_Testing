def sensor_stop(bota_ft_sensor_driver):
#    print("ENTERING sensor_stop")



    # Transition driver from ACTIVE to INACTIVE state
    if not bota_ft_sensor_driver.deactivate():
        raise RuntimeError("Failed to deactivate driver")
    
    # Shutdown the driver
    if not bota_ft_sensor_driver.shutdown():
        raise RuntimeError("Failed to shutdown driver")
