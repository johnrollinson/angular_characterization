import matplotlib
import matplotlib.pyplot as plt
import matplotlib.tri as tri
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

grat_style = [
    "slgc",
    "dlgc"
]

taper_style = [
    "sine",
    "linear"
]

num_grats = [
    "1x",
    "2x",
    "4x",
    "4x2",
    "4x4",
    "6x",
    "6x2",
    "8x",
]

conn_style = [
    "ref",
    "tree",
    "folded"
]

for grat in grat_style:
    for taper in taper_style:
        file_list = os.listdir(f"data/feb22/{grat}/{taper}/2d")

        for fname in sorted(file_list):
            print(fname)
            if fname.startswith("_"):
                continue
            if not (set(fname.split("_")) & set(num_grats)):
                continue
            if not (set(fname.split("_")) & set(conn_style)):
                continue
            data_in = np.loadtxt(f"data/feb22/{grat}/{taper}/2d/{fname}", delimiter=',', skiprows=16).T
            roll_angle = abs(data_in[0])
            pitch_angle = data_in[1]
            photocurrent = data_in[2] * 1e9

            # Perform triangular interpolation of photocurrent data for 2D plot
            x = np.linspace(0, 20, 4000)
            y = np.linspace(-5, 5, 4000)
            triang = tri.Triangulation(roll_angle, pitch_angle)
            interpolator = tri.LinearTriInterpolator(triang, photocurrent)
            Xi, Yi = np.meshgrid(x, y)
            zi = interpolator(Xi, Yi)

            # Reshape arrays for plotting slices
            pitch_angle = pitch_angle.reshape(len(pitch_angle)//201, 201)[:, 0]
            roll_angle = roll_angle.reshape(len(roll_angle) // 201, 201)[0, :]
            photocurrent = np.reshape(photocurrent, newshape=(len(photocurrent)//201, 201))
            peak_ind = np.unravel_index(photocurrent.argmax(), photocurrent.shape)
            peak = np.max(photocurrent)

            # Plotting
            gs_kw = dict(hspace=0, wspace=0, width_ratios=[0.2, 2, 0.75], height_ratios=[2, 0.75])
            fig, ax = plt.subplot_mosaic(
                [["cbar", "main", "pitch"], ["cblank", "roll", "blank"]],
                dpi=300,
                figsize=(6, 6/1.618),
                gridspec_kw=gs_kw
            )
            ax["blank"].set_axis_off()
            ax["cbar"].set_axis_off()
            ax["cblank"].set_axis_off()

            # Plot the main photocurrent heatmap
            im = ax["main"].imshow(
                zi, cmap="plasma", origin='lower',
                extent=[0, 20, -5, 5],
                interpolation=None,
                aspect="auto"
            )
            plt.colorbar(im, ax=ax["cbar"], use_gridspec=True, location="left", fraction=1, anchor=(-1.5, 0.5))
            ax["main"].axvline(roll_angle[peak_ind[1]], color='black', linestyle='--', lw=1)
            ax["main"].axhline(pitch_angle[peak_ind[0]], color='black', linestyle='--', lw=1)
            ax["main"].xaxis.tick_top()
            ax["main"].grid(alpha=0.5)
            ax["main"].set_xlabel("Roll Angle [deg]")
            ax["main"].xaxis.set_label_position("top")
            ax["main"].set_ylabel("Pitch Angle [deg]")

            # Plot and configure the roll slice plot
            ax["roll"].plot(roll_angle, photocurrent[peak_ind[0], :], label=fname.split("_")[2:4])
            ax["roll"].set_xlim(0, 20)
            ax["roll"].set_ylim(ax["roll"].get_ylim()[0], ax["roll"].get_ylim()[1] * 1.05)
            ax["roll"].minorticks_on()
            ax["roll"].grid(which='major')
            ax["roll"].grid(which='minor', alpha=0.4)
            ax["roll"].set_xlabel("Roll Angle [deg]")
            ax["roll"].set_ylabel("Photocurrent [nA]")

            # Plot and configure the pitch slice plot
            ax["pitch"].plot(-photocurrent[:, peak_ind[1]], pitch_angle, label=fname.split("_")[2:4])
            ax["pitch"].set_ylim(-5, 5)
            ax["pitch"].set_xlim(ax["pitch"].get_xlim()[0] * 1.05, ax["pitch"].get_xlim()[1])
            ax["pitch"].minorticks_on()
            ax["pitch"].grid(which='major')
            ax["pitch"].grid(which='minor', alpha=0.4)
            xticklabels = [label.get_text().strip("\N{MINUS SIGN}") for label in ax["pitch"].get_xticklabels()]
            ax["pitch"].set_xticklabels(xticklabels)
            ax["pitch"].yaxis.tick_right()
            ax["pitch"].yaxis.set_label_position("right")
            ax["pitch"].set_ylabel("Pitch Angle [deg]")
            ax["pitch"].set_xlabel("Photocurrent [nA]")

            # Add statistics on the blank axes
            ax["blank"].text(0.2, 0.3, f"Peak: {peak:.1f}nA")
            ax["blank"].text(0.2, 0.1, f"Roll: {roll_angle[peak_ind[1]]:.1f}deg")
            ax["blank"].text(0.2, -0.1, f"Pitch: {pitch_angle[peak_ind[0]]:.1f}deg")

            # Finalize plot and save
            title = ', '.join(fname.split("_")[:4])
            fig.suptitle(title)

            plt.tight_layout()
            plt.subplots_adjust(hspace=0, wspace=0)
            img_name = "_".join(fname.split("_")[:4])
            plt.savefig(f"plots/feb22/{img_name}_2d.png")
            # plt.show()
            plt.close()
