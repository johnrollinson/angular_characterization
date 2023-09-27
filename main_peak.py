import os
import sys
import tempfile
import random
from time import sleep
from pymeasure.log import console_log
from pymeasure.display.Qt import QtWidgets
from pymeasure.display.windows import ManagedWindow
from pymeasure.experiment import Procedure, Results
from pymeasure.experiment.results import unique_filename
from pymeasure.experiment import IntegerParameter, FloatParameter, Parameter

from procedures_peak_finding import PeakFinding


class MainWindow(ManagedWindow):

    def __init__(self):
        super(MainWindow, self).__init__(
            procedure_class=PeakFinding,
            inputs=['test_name', 'bias_voltage', 'roll_angle_init',
                    'pitch_angle_init', 'max_meas', 'threshold', 'delay', 'laser_current'],
            displays=['roll_angle_init', 'pitch_angle_init', 'angle_step', 'laser_current'],
            x_axis='Roll Angle',
            y_axis='Detector Current',
            directory_input=True,
            hide_groups=True
        )
        self.setWindowTitle('Peak Finding and Coupling Angle Characterization')

    def queue(self, *, procedure=None):
        directory = self.directory

        if procedure is None:
            procedure = self.make_procedure()

        prefix = str(procedure.test_name)
        filename = unique_filename(
            directory,
            prefix=prefix + "_",
            datetimeformat="%Y%m%d_%H%M%S"
        )

        results = Results(procedure, filename)
        experiment = self.new_experiment(results)

        self.manager.queue(experiment)


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
