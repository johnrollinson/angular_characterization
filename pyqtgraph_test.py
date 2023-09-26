import pyqtgraph as pg
import numpy as np

x = np.linspace(0, 1, 100)
y = np.linspace(0, 10, 100)

win = pg.GraphicsLayoutWidget()
win.addPlot(x)
input()
