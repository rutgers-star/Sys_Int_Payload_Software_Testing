# -*- coding: utf-8 -*-
"""
Created on Sun Jul  2 09:26:28 2023

@author: mfogel
"""

#To Do
#
# V10b changes the output order to RPY (x,y,z) aerospace standard. This way w1, w2,w3 = wx, wy,wz
#
import RPi.GPIO as GPIO
import math
import numpy as np 
import matplotlib.pyplot as plt
import time
from init_imu import init_imu
from imudata import imudata
from init_maxon import init_maxon
from plotsloshy import plotsloshy
from plotsloshy2 import plotsloshy2
from motion_in_velocity import MotionInVelocity
from close_maxon import close_maxon
from control import control
from ctypes import *
from sensor_start import sensor_start
from sensor_read import sensor_read
from sensor_stop import sensor_stop
from plotforcestorques import plotforcestorques
import subprocess

# theta = platform angle
# vel = platform angular velocity
# acc = platform angular acceleration
# u = RPM calculated by algrithm for motor
# umotor = RPM commanded to motor
# Omega = RPM measured from motor


#maxiter=150 # Max number of allowed iterations to meet desired angle
maxiter=200 # Max number of allowed iterations to meet desired angle 
amax=10000 # Max RPM of the maxon motor. SAFETY stop. 3500 is allowable.
vmax=3000 # Max RPM of the maxon motor. SAFETY stop. 3500 is allowable.
umax=amax
acceleration0=4000

    

# Reaction wheel MoI
Jx=2.491E-4 # kg m^2 Reacton Wheel MoI
Jy=2.250E-4 # kg m^2 Reacton Wheel MoI
Jz=4.703E-4 # kg m^2 Reacton Wheel MoI
J=math.sqrt(Jx**2 + Jy**2 + Jz**2)
I = 0.01180  #kg m^2 Tank MoI

# Initialization
theta_d=65 #Desired angle
tol=2  # Tolerance to angle reaching desired angle

# Small Gains March 2026
kp0=0.011   # as of 03/08/2026
kd0=0.01    # as of 03/08/2026
ki0=0.001   # as of 03/08/2026
kt0 = 0.01  # as of 03/08/2026  For torque sensor

#Large Gains March 2026
#kp0=0.09   # Test as of 03/15/2026
#kd0=0.05   # Test as of 03/15/2026
#ki0=0.01    # Test as of 03/15/2026
#kt0 = 0.01   # Test as of 03/15/2026




#kp0=0.0    # No movement for static testing
#kd0=0.0    # No movement for static testing
#ki0=0.0    # No movement for static testing
#kt0 = 0.0  # No movement for static testing




########### OPEN DATA FILE FOR WRITING OPEN ###############
file = open("1g-dynamics.csv","w")
header=["time","roll","pitch","yaw","wx_roll","wy_pitch","wz_yaw","wdotx_roll","wdoty_pitch","wdotz_yaw","ax","ay","az","ux","uy","uz","Fx","Fy","Fz","Tx","Ty","Tz"]
file.write(",".join(header) + "\n")
########### OPEN DATA FILE FOR WRITING CLOSE ##############

########### OPEN DATA FILE FOR WRITING OPEN ###############   OLD
#file = open("1g-dynamics.csv","w")
########### OPEN DATA FILE FOR WRITING CLOSE ##############   OLD


########### TORQUE SENSOR STARTUP CODE BEGIN ##############
force = np.zeros((maxiter,3))
torque = np.zeros((maxiter,3))
status = np.zeros((maxiter,3))
# Define the Bota sensor and start it up
bota_ft_sensor_driver = sensor_start()
########### TORQUE SENSOR STARTUP CODE END ##############


########### MOTOR STARTUP CODE BEGIN ##############
# Folder created for example: /home/pi/src/python/
# Copy maxon motor Linux Library arm v7 into this folder
# Library must match according your cpu, eg. PI3 has arm v7
# Library must match according your cpu, eg. PI3 has arm v7
# Library must match according your cpu, eg. PI4 has arm v8  # Fogel added 6/25/2023
# EPOS Comand Library can be found here, when EPOS Studio has been installed:
# path="C:\Program Files (x86)\maxon motor ag\EPOS IDX\EPOS4\04 Programming\Linux Library"
# path='/home/pi/src/python/libEposCmd.so.6.6.2.0'
# From working version  path='/opt/EposCmdLib_6.7.1.0/lib/v8/libEposCmd.so.6.7.1.0'
#path='.\EposCmd64.dll'  # If WINDOWS
path='/opt/EposCmdLib_6.7.1.0/lib/v8/libEposCmd.so.6.7.1.0' # If Linux
cdll.LoadLibrary(path)
epos=CDLL(path)
ret=0
pErrorCode=c_uint()
pDeviceErrorCode=c_uint()
pVelocityIs=c_long()
keyhandle,NodeID = init_maxon(epos)
########### MOTOR STARTUP CODE END ##############

########### IMU STARTUP CODE BEGIN ##############
yaw0,imu = init_imu()
yawOld=0
print('Yaw0:',yaw0)
#print('YawOld:',yawOld)
#print('IMU Port:',imu)
########### IMU STARTUP CODE END ##############

########### LED STARTUP CODE BEGIN ##############
GPIO.setmode(GPIO.BCM)
# GPIO.setwarnings(False) dont' use this.
GPIO.setup(17, GPIO.OUT)
GPIO.output(17, GPIO.LOW)
print("Turning off LED initially")
########### LED STARTUP CODE END ##############

########### CAMERA STARTUP CODE BEGIN ##############
print("Staring camera")
subprocess.Popen(["rm", "sloshing.h264"])
camlog=open("camlog.txt",'w')
cam=subprocess.Popen(["/usr/local/bin/libcamera-vid", "-t 20000", "--nopreview","--save-pts","camtimes.txt","--framerate","24","-o","sloshing.h264"], text=True, stderr=camlog)
print("Camera started")
########### CAMERA STARTUP CODE END ##############


k=1
t = np.zeros(maxiter)
yaw = np.zeros(maxiter)
pitch = np.zeros(maxiter)
roll = np.zeros(maxiter)
dyawdt = np.zeros(maxiter)
dpitchdt = np.zeros(maxiter)
drolldt = np.zeros(maxiter)
ddyawdt2 = np.zeros(maxiter)
ddpitchdt2 = np.zeros(maxiter)
ddrolldt2 = np.zeros(maxiter)

theta = np.zeros(maxiter)
vel = np.zeros(maxiter)
acc = np.zeros(maxiter)
Omega = np.zeros(maxiter)
err = np.zeros(maxiter)
errdot = np.zeros(maxiter)
ecumul = np.zeros(maxiter)
u = np.zeros(maxiter)
umotor = np.zeros(maxiter)
meantheta=0
t[0]=0
err[0]=-theta_d
errdot[0]=0.0
ecumul[0]=0.0
tstart=time.time()
#time.sleep(1.0E-16)

##### MAIN CONTROL LOOP ####
#while (k <= maxiter-1) and abs(meantheta - theta_d) > tol):
while (k < maxiter):
#    print("LED on")
    GPIO.output(17, GPIO.HIGH)

    t[k]=time.time() - tstart
    dt=t[k] - t[k-1]
#    print('Iteration #        = {0:4d} {1:4f} '.format(k,t[k]))
#    time.sleep(1.0E-14)
    
# Get IMU data
    yaw[k],pitch[k],roll[k]=imudata(imu,yaw0,yawOld)
    theta[k]=yaw[k]
    vel[k] = (theta[k]) - theta[k-1]/dt
    acc[k]=(vel[k] - vel[k-1])/dt
    err[k]=(theta[k] - theta_d)
    errdot[k]=(err[k] - err[k-1])/dt
    ecumul[k]=ecumul[k-1] + err[k]*dt
    
    
    # Get Bota sensor data
    [s,force[k,:],torque[k,:]] = sensor_read(bota_ft_sensor_driver)


    # Control Algorithm Using PID Controller
    u[k] = control(kt0, kp0, kd0, ki0, theta_d, k, t, dt, I, J, theta, vel, acc, err, errdot, ecumul, torque[k,:])

    umotor[k]=u[k];
    acceleration=abs(umotor[k])
    if acceleration > amax:
        acceleration=amax

    velocity=np.sign(u[k])*vmax

#    acceleration = 0.0 # Calibration ONLY
#    velocity = 0.0 # Calibration ONLY
# Drive the Motor

#    if ((k == 1) or (k % 5 == 0)):
    Omega[k] = MotionInVelocity(keyhandle, NodeID, epos, velocity, acceleration)
    time.sleep(0.025) # Good as of 11/5/2023 10:51 am
    
    dyawdt[k]=(yaw[k] - yaw[k-1])/dt
    dpitchdt[k]=(pitch[k] - pitch[k-1])/dt
    drolldt[k]=(roll[k] - roll[k-1])/dt
    dyawdt[0:1]=0.0
    dpitchdt[0:1]=0.0
    drolldt[0:1]=0.0

    ddyawdt2[k]=(dyawdt[k] - dyawdt[k-1])/dt
    ddpitchdt2[k]=(dpitchdt[k] - dpitchdt[k-1])/dt
    ddrolldt2[k]=(drolldt[k] - drolldt[k-1])/dt
    ddyawdt2[0:1]=0.0
    ddpitchdt2[0:1]=0.0
    ddrolldt2[0:1]=0.0
    
    print("%5.0i    %4.3f  %10.2f  %10.2f %10.2f %10.2f %10.2f %10.2f " % (k,t[k], theta[k], err[k], errdot[k], ecumul[k], umotor[k], u[k]))
#    file.write("%5.0i    %4.3f  %10.2f  %10.2f %10.2f %10.2f %10.2f %10.2f \n" % (k,t[k], theta[k], err[k], errdot[k], ecumul[k], umotor[k], u[k]))
    a=0.0  # Linear acceleration a is not needed. Included here just for unuiformity of input/output files into SINDy. Linear acceleration a is not needed.
    file.write("%4.3f,  %8.4f,  %8.4f, %8.4f, %8.4f, %8.4f, %8.4f, %8.4f, %8.4f, %8.4f, %8.4f, %8.4f, %8.4f, %8.4f, %8.4f, %8.4f, %8.4f, %8.4f, %8.4f, %8.4f, %8.4f, %8.4f \n" % 
                                                                                        (t[k], 
                                                                                         roll[k],        pitch[k],   yaw[k],
                                                                                         drolldt[k],     dpitchdt[k],   dyawdt[k],
                                                                                         ddrolldt2[k],   ddpitchdt2[k], ddyawdt2[k],
                                                                                         a,             a,             a,            
                                                                                         0.0      ,     0.0,           umotor[k],
                                                                                         force[k,0],    force[k,1],    force[k,2],
                                                                                         torque[k,0],   torque[k,1],   torque[k,2]))



    if (k > 10): 
        meantheta=np.mean(theta[k-10:k])

    yawOld=theta[k]
    k=k+1

print("End of MAIN LOOP")    
print("LED Off")
GPIO.output(17, GPIO.LOW)
GPIO.cleanup() # use this instead
print("Shutting Motor Down")    
close_maxon(keyhandle,NodeID, epos)
print("Motor Stopped")    
print("Closing Camera File")
print("Video file output: sloshing.h264")
camlog.close()
print("Camera Closed")
print("Shutting Bota Sensor Down")
sensor_stop(bota_ft_sensor_driver)
print("Bota Sensor Shutdown")
print("Closing File")
file.close()
print("File Closed")
print("Plotting")    
#
errdot[0]=0.0
errdot[1]=0.0
plotsloshy2(t, theta, theta_d, u, umotor, umax, Omega, vel, acc, err, errdot, ecumul)
plotforcestorques(t, u, force, torque)
#plt.show(block=False)
plt.show()

print("End of CODE")  