#import os
#import signal
#import bota_driver
#import sys
import time
import math
import numpy as np 
from sensor_start import sensor_start
from sensor_read import sensor_read
from sensor_stop import sensor_stop
from control import control
from plotforcestorques import plotforcestorques



maxiter = 100
t = np.empty(maxiter)
force = np.empty((maxiter,3))
torque = np.empty((maxiter,3))
status = np.empty((maxiter,3))
u = np.empty(maxiter)


###### defining these ONLY to test. 
theta_d = 90
t[0]=0
k=0
# Reaction wheel MoI
Jx=2.491E-4 # kg m^2 Reacton Wheel MoI
Jy=2.250E-4 # kg m^2 Reacton Wheel MoI
Jz=4.703E-4 # kg m^2 Reacton Wheel MoI
J=math.sqrt(Jx**2 + Jy**2 + Jz**2)
I = 0.01180  #kg m^2 Tank MoI
theta = np.empty(maxiter)
vel = np.empty(maxiter)
acc = np.empty(maxiter)
err = np.empty(maxiter)
errdot = np.empty(maxiter)
ecumul = np.empty(maxiter)
u = np.empty(maxiter)
#err[0]=0.0
#errdot[0]=0.0
#ecumul[0]=0.0

# Define the Bota sensor and start it up
bota_ft_sensor_driver = sensor_start()


tstart=time.time()
dt=0
while (k < maxiter):
    t[k]=time.time() - tstart
    [s,force[k,:],torque[k,:]] = sensor_read(bota_ft_sensor_driver)
    print(k, t[k], force[k,:], torque[k,:])
    time.sleep(0.1)
    u[k] = control(theta_d, k, t, dt, I, J, theta, vel, acc, err, errdot, ecumul,torque[k,:])
    k=k+1
#    dt=t[k] - t[k-1]



# Fix this later
#force[0,:] = force[1,:]
#torque[0,:] = torque[1,:]
#u[0] = u[1]

#print("Bota Sensor Complete")

sensor_stop(bota_ft_sensor_driver)
#print("Bota Sensor Shutdown")

#print("Plotting")
plotforcestorques(t, u, force, torque)
#print("Done Plotting")
