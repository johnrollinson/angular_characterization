import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import os

params = {
    # "backend": "png",
    "pgf.preamble": [r"\usepackage{gensymb}", r"\usepackage{sansmath}"],
    "pgf.texsystem": "pdflatex",
    "axes.labelsize": 9,  # fontsize for x and y labels (was 10)
    "axes.titlesize": 9,
    "font.size": 9,  # was 10
    "legend.fontsize": 8,  # was 10
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "text.usetex": True,
    "font.family": "sans-serif",
    "font.sans-serif": "cm",
    "image.cmap": "gnuplot",
}

matplotlib.rcParams.update(params)


grat_style = ["slgc", "dlgc"]
grat_color = ["red", "green"]

conn_style = [
    ["sine", "folded"],
    ["sine", "tree"],
    ["linear", "folded"],
    ["linear", "tree"],
]
linestyle = ["-", "--", ":", "-."]

num_grats = [
    "1x",
    "2x",
    "4x",
    # "4x2",
    # "4x4"
    "6x",
    # "6x2"
    "8x",
]

fig, ax = plt.subplots(1, 1, dpi=300, figsize=(4, 4 / 1.618))

for grat, gc in zip(grat_style, grat_color):
    for conn, ls in zip(conn_style, linestyle):

        taper = conn[0]
        network = conn[1]
        file_list = os.listdir(f"data/feb22/{grat}/{taper}/2d")

        peak_list = []
        for fname in sorted(file_list):

            if fname.startswith("_"):
                continue
            if not (set(fname.split("_")) & set(num_grats)):
                continue
            if not (set(fname.split("_")) & set((network, "ref"))):
                continue

            data_in = np.loadtxt(
                f"data/feb22/{grat}/{taper}/2d/{fname}",
                delimiter=",",
                skiprows=16,
            ).T
            roll_angle = abs(data_in[0])
            pitch_angle = data_in[1]
            photocurrent = data_in[2] * 1e9

            pitch_angle = pitch_angle.reshape(len(pitch_angle) // 201, 201)[
                :, 0
            ]
            roll_angle = roll_angle.reshape(len(roll_angle) // 201, 201)[0, :]
            photocurrent = np.reshape(
                photocurrent, newshape=(len(photocurrent) // 201, 201)
            )

            peak = np.max(photocurrent)
            n_grats = int(fname.split("_")[2].strip("x"))

            peak_list.append([n_grats, peak])

        peak_list = np.array(peak_list).T
        plt.plot(peak_list[0], peak_list[1], "o", color=gc)
        plt.plot(
            peak_list[0],
            peak_list[1],
            ls=ls,
            color=gc,
            label=f"{grat}, {taper}, {network}",
        )


plt.title("Comparison of Linear Arrays")
plt.xlabel("No. Gratings")
plt.ylabel("Photocurrent [nA]")
plt.minorticks_on()
plt.grid(which="major")
plt.grid(which="minor", alpha=0.4)
plt.legend()
plt.tight_layout()
plt.savefig("plots/feb22/linear_array_comparison.png")
plt.show()
