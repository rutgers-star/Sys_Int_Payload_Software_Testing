import matplotlib.pyplot as plt

def plotforcestorques(t, u, force, torque):

    
    # Graph Solution
#    print("Starting GRAPHS")    
    fig,ax = plt.subplots(3,1)
    font = {'size'   : 6}
    plt.rc('font', **font)


    ax[0].plot(t,torque)
    ax[0].set_xlabel('t (s)',fontsize=6)
    ax[0].set_ylabel('Bota Torque (N-m)',fontsize=6)
    ax[0].set_xlim([0,t[-1]])
    ax[0].legend([r"$\Gamma_x$",r"$\Gamma_y$",r"$\Gamma_z$"], loc = "upper right")

    
    ax[1].plot(t,force)
    ax[1].set_xlabel('t (s)',fontsize=6)
    ax[1].set_ylabel('Bota Forces (N)',fontsize=6)
    ax[1].set_xlim([0,t[-1]])
    ax[1].legend([r"$F_x$",r"$F_y$",r"$F_z$"], loc = "upper right")

    
    ax[2].plot(t,u)
    ax[2].set_xlabel('t (s)',fontsize=6)
    ax[2].set_ylabel('Controller u(t)',fontsize=6)
    ax[2].set_xlim([0,t[-1]])
    ax[2].legend([r"$u(t)_{calc}$"], loc = "upper right")
        
    
    fig.suptitle('Bota Torque Sensor', fontsize=8, fontweight='bold')
    
    #print("END GRAPHS")  