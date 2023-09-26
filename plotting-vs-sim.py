import matplotlib.pyplot as plt
import numpy as np


fig, ax = plt.subplots(1, 1)

data_exp = np.loadtxt("data/jul21/1gc_20220407_161301_1.csv", delimiter=',', skiprows=12).T

ax.plot(data_exp[0], data_exp[1] * 1e9, label="measured")
ax.set_title("Grating Measurement Comparison")
ax.set_xlabel("Angle [deg]")
ax.set_ylabel("Photocurrent [nA] (Measured)")
ax.legend()

data_sim_te = np.loadtxt("simulation/angle-sweep-8-12-te.txt", delimiter=',', skiprows=1).T
data_sim_tm = np.loadtxt("simulation/angle-sweep-5-10-tm.txt", delimiter=',', skiprows=1).T
ax2 = ax.twinx()
ax2.plot(data_sim_te[0], data_sim_te[1], '--', label='simulated,te')
ax2.plot(data_sim_tm[0], data_sim_tm[1]*0.6, '--', label='simulated,tm')
ax2.set_ylabel("Coupling Efficiency [%] (Simulated)")

ax2.legend()
ax.grid()

plt.tight_layout()
plt.show()
