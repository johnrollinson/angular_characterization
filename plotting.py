import matplotlib.pyplot as plt
import numpy as np

files = [
    "1gc_20220407_161301_1.csv",
    "2gc_20220407_162304_1.csv",
    "4gc_20220407_165108_1.csv"
]
legend = [
    "1GC",
    "2GC",
    "4GC"
]
peaks = []

for i, f in enumerate(files):
    data = np.loadtxt("data/" + f, delimiter=',', skiprows=12).T
    peaks.append(np.max(data[1]))
    plt.plot(data[0], data[1], label=legend[i])

peak_rel = ["", "", ""]
peak_rel[1] = "({}%)".format(int(peaks[1]/peaks[0]*100))
peak_rel[2] = "({}%)".format(int(peaks[2]/peaks[0]*100))
pk_str = "\n".join(["{}: {:0.3f} nA {}".format(lab, p*1e9, rel) for lab, p, rel in zip(legend, peaks, peak_rel)])
plt.text(1, 0.7e-9, "Peaks:\n" + pk_str, bbox=dict(facecolor='white', alpha=0.5))
plt.title("Photonic Power Combining Comparison")
plt.xlabel("Angle [deg]")
plt.ylabel("Photocurrent [A]")
plt.legend()
plt.grid()
plt.show()
