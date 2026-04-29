# -*- coding: utf-8 -*-
"""
Created on Mon Aug 26 10:37:52 2024

@author: mfogel
"""

import math
#import numpy as np 

# function definition
#OLD def control(theta_d, k, t, dt, I, J, theta, vel, acc, err, errdot, ecumul,torque):
def control(kt, kp, kd, ki, theta_d, k, t, dt, I, J, theta, vel, acc, err, errdot, ecumul, torque):
#    print("In Control Algorithm")
    

#    torquex=torque[0]
#    torquey=torque[1]
    torquez=torque[2]


    ucontrol = (I/J)*(kp*err[k] + kd*errdot[k] + ki*ecumul[k])*(60/2*math.pi) - torquez

    return ucontrol
