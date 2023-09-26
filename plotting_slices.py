import matplotlib.pyplot as plt
import numpy as np
import os

grat_style = [
    # "slgc",
    "dlgc"
]
taper_style = [
    "sine",
    # "linear"
]

num_grats = [
    "1x",
    # "2x",
    # "4x",
    # "4x2",
    # "6x",
    # "8x",
]

conn_style = [
    "ref",
    # "tree",
    "folded"
]

fig, axes = plt.subplots(2, 1)

for grat in grat_style:
    for taper in taper_style:
        file_list = os.listdir(f"data/feb22/{grat}/{taper}/2d")

        for fname in sorted(file_list):

            if fname.startswith("_"):
                continue
            if not (set(fname.split("_")) & set(num_grats)):
                continue
            if not (set(fname.split("_")) & set(conn_style)):
                continue

            data_in = np.loadtxt(f"data/feb22/{grat}/{taper}/2d/{fname}", delimiter=',', skiprows=16).T
            roll_angle = abs(data_in[0])
            pitch_angle = data_in[1]
            photocurrent = data_in[2]*1e9

            pitch_angle = pitch_angle.reshape(len(pitch_angle)//201, 201)[:, 0]
            roll_angle = roll_angle.reshape(len(roll_angle) // 201, 201)[0, :]

            photocurrent = np.reshape(photocurrent, newshape=(len(photocurrent)//201, 201))
            peak_ind = np.unravel_index(photocurrent.argmax(), photocurrent.shape)
            print(peak_ind)

            axes[0].plot(roll_angle, photocurrent[peak_ind[0], :], label=fname.split("_")[2:4])
            axes[1].plot(pitch_angle, photocurrent[:, peak_ind[1]], label=fname.split("_")[2:4])

axes[0].legend()
axes[1].legend()
plt.show()
