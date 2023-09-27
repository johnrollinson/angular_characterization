import logging
from time import sleep
from typing import List

import numpy as np
from pymeasure.adapters import VISAAdapter
from pymeasure.experiment import (
    BooleanParameter,
    FloatParameter,
    IntegerParameter,
    Parameter,
    Procedure,
)
from stage.ctrl_msg import MGMSG_MOT_MOVE_JOG, MGMSG_MOT_SET_JOGPARAMS
from stage.motor_ctrl import MotorCtrl
from stage.motor_ini.core import find_stages

from agilent import E364A
from keithley import Keithley6487
from procedures import move_jog, move_stage_to, set_jog_step

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

# Connect to motors and set both stages to 0deg
# SerNo's:
# Pitch Axis = 27259854
# Roll Axis = 27259431
log.info("Connecting to motors.")
stages = list(find_stages())  # type: List[MotorCtrl]
if len(stages) != 0:
    log.info("Found motor stages:")
    [log.info(s) for s in stages]
    for s in stages:
        if s.ser_no == 27259854:
            pitch_stage = s
        elif s.ser_no == 27259431:
            roll_stage = s
            roll_stage.status_in_motion_jogging_forward
        else:
            log.error("Unrecognized motor stage: {}".format(s))
else:
    log.error("No motor stages found.")


class PeakFinding(Procedure):
    """
    Find the peak coupling efficiency and coupling angle of a grating.
    """

    test_name = Parameter("Test Name")

    roll_angle_init = FloatParameter(
        "Roll Start Angle",
        minimum=-45,
        maximum=45,
        units="deg",
        default=0,
    )
    pitch_angle_init = FloatParameter(
        "Pitch Start Angle",
        minimum=-45,
        maximum=45,
        units="deg",
        default=0,
    )

    angle_step = FloatParameter("Initial Angle Step", units="deg", default=0.1)

    threshold = FloatParameter("Current Tolerance", units="nA", default=0.5)
    delay = FloatParameter("Trigger Delay", units="ms", default=10)
    max_meas = IntegerParameter("Max Samples", default=500)
    bias_voltage = FloatParameter(
        "Detector Bias Voltage", minimum=-3, maximum=3, units="V", default=0
    )
    laser_current = FloatParameter(
        "Optical Source Current", units="mA", maximum=300
    )

    DATA_COLUMNS = ["Roll Angle", "Pitch Angle", "Detector Current", "Peak Roll", "Peak Pitch", "Peak Current"]

    def __init__(self):
        super().__init__()
        self.picoammeter = None
        self.power_supply = None
        self.roll_stage = roll_stage
        self.pitch_stage = pitch_stage

        self.roll_offset = 45
        # NOTE: The pitch stage has a weird offset, may need to fix this at some point
        self.pitch_offset = -32.7

    def startup(self):
        # Connect to picoammeter and set up current measurement
        log.info("Connecting and configuring the picoammeter ...")
        adapter = VISAAdapter("GPIB0::22::INSTR", visa_library="@py")
        self.picoammeter = Keithley6487(adapter)
        self.picoammeter.configure(nplc=1)
        self.picoammeter.set_bias_voltage(self.bias_voltage)
        log.info("Picoammeter configuration complete.")

        # Set the laser diode power
        log.info("Connecting to power supply and configuring")
        adapter = VISAAdapter("GPIB0::5::INSTR", visa_library="@py")
        self.power_supply = E364A(adapter)
        self.power_supply.reset()
        self.power_supply.apply(5, self.laser_current / 1e3)
        self.power_supply.enabled = "OFF"
        log.info("Power supply current configured")
        log.info("Enabling and triggering power supply")
        self.power_supply.enabled = "ON"
        self.power_supply.trigger()

        # Set jog step size
        log.info(f"Setting roll jog step size to {self.angle_step}deg")
        set_jog_step(self.roll_stage, abs(self.angle_step), 9.98)
        log.info(f"Setting pitch jog step size to {self.angle_step}deg")
        set_jog_step(self.pitch_stage, abs(self.angle_step), 9.98)

        # Calibrate the stage positions
        self.roll_stage.set_vel_params(24.99, 25, 25)
        self.pitch_stage.set_vel_params(24.99, 25, 25)
        log.info("Homing the roll and pitch axes")
        self.roll_stage.set_home_dir(2)
        self.pitch_stage.set_home_dir(1)
        self.roll_stage.move_home(blocking=True)
        self.pitch_stage.move_home(blocking=True)
        check = 0
        while (
            not self.roll_stage.status_homed or not self.roll_stage.status_homed
        ):
            check += 1
            sleep(1)
            if check >= 20:
                log.warning(
                    "Homing timed out (20s), stages may not have homed successfully."
                )
                break

        log.info("Levelling the roll and pitch stages")
        move_stage_to(self.roll_stage, self.roll_offset, blocking=True)
        move_stage_to(self.pitch_stage, self.pitch_offset, blocking=True)
        check = 0
        while not np.isclose(
            self.roll_stage.pos, self.roll_offset, atol=0.01
        ) or not np.isclose(self.pitch_stage.pos, self.pitch_offset, atol=0.01):
            check += 1
            sleep(1)
            if check >= 20:
                log.warning(
                    "Levelling timed out (20s), stages may not have levelled successfully."
                )
                break

    def execute(self):
        log.info("Executing procedure.")

        # Move roll axis to the starting angle
        log.info(f"Moving roll axis to starting angle: {self.roll_angle_init}.")
        move_stage_to(
            self.roll_stage,
            self.roll_angle_init + self.roll_offset,
            blocking=True,
        )
        log.info(f"Moving pitch axis to starting angle: {self.pitch_angle_init}.")
        move_stage_to(
            self.pitch_stage,
            self.pitch_angle_init + self.pitch_offset,
            blocking=True,
        )

        log.info("Beginning measurement")

        stage = self.roll_stage
        step_size = self.angle_step
        curr_tol = self.threshold
        i = 0

        # Track the number of reversals and refinement steps
        n_reverse = 0
        rev_thresh = 4
        n_refine = 0
        ref_thresh = 4

        iterations = ref_thresh * rev_thresh * 2
        k = 0

        prev_meas = self.picoammeter.get_current()
        jog_dir = 1
        peak_meas = -np.inf
        peak_loc = [0.0, 0.0]
        while True:
            # Move one jog step and take new current measurement
            move_jog(stage, jog_dir)
            sleep(self.delay*1e-3)
            new_meas = self.picoammeter.get_current()
            roll_angle = self.roll_stage.pos - self.roll_offset
            pitch_angle = self.pitch_stage.pos - self.pitch_offset

            # Record measurement
            peak_meas = np.max([peak_meas, new_meas])
            if np.isclose(new_meas, peak_meas, atol=1e-15, rtol=1e-5):
                log.debug("New peak found")
                peak_loc = [roll_angle, pitch_angle]

            log.debug(
                (
                    f"Angle=({roll_angle:0.3f}, {pitch_angle:0.3f}), "
                    f"Current Meas={new_meas:0.3e}, Prev. Meas={prev_meas:0.3e}, "
                    f"Peak Angle=({peak_loc[0]:0.3f}, {peak_loc[1]:0.3f}), "
                    f"Peak Current={peak_meas:0.3e}"
                )
            )
            self.emit(
                "results",
                {
                    "Roll Angle": roll_angle,
                    "Pitch Angle": pitch_angle,
                    "Detector Current": new_meas,
                    "Peak Roll": peak_loc[0],
                    "Peak Pitch": peak_loc[1],
                    "Peak Current": peak_meas
                },
            )

            # If new meas < old meas, switch directions
            if new_meas < (prev_meas - curr_tol*1e-9):
                log.info("Reversing direction")
                jog_dir = jog_dir % 2 + 1
                n_reverse += 1
                k += 1
                self.emit("progress", 100 * k / iterations)
            prev_meas = new_meas

            # If we reverse directions multiple times, switch axes
            # Before switching axes, move the current stage to the peak position
            if n_reverse >= rev_thresh:
                log.info("Reversal threshold reached, switching axes")
                n_reverse = 0
                log.info(f"Move stages to current peak: ({peak_loc[0]:0.3f}, {peak_loc[1]:0.3f})")
                move_stage_to(self.roll_stage, peak_loc[0] + self.roll_offset, blocking=True)
                move_stage_to(self.pitch_stage, peak_loc[1] + self.pitch_offset, blocking=True)
                if stage == self.roll_stage:
                    stage = self.pitch_stage
                else:
                    stage = self.roll_stage
                n_refine += 1

            # If we refine both stages multiple times, halve the step size
            if n_refine >= ref_thresh:
                n_refine = 0
                log.info("Refinement threshold reached, halving step size and current threshold")
                step_size = step_size / 2
                curr_tol = curr_tol / 2
                if step_size < 0.04:
                    break
                set_jog_step(self.roll_stage, abs(step_size), 9.98)
                set_jog_step(self.pitch_stage, abs(step_size), 9.98)

            i += 1
            if i >= self.max_meas:
                log.info("Maximum number of measurements ({max_meas}) exceeded, stopping measurement.")
                break

            if self.should_stop():
                log.info("Caught stop flag during procedure.")
                break

        log.info("Procedure completed.")

    def shutdown(self):
        pass
        # TODO: After procedure completes, return both axes to 0deg
        # log.info("Executing procedure shutdown.")
        # log.info("Disconnecting from motors.")
        # self.pitch_stage._port.send_message(MGMSG_HW_STOP_UPDATEMSGS())
        # self.roll_stage._port.send_message(MGMSG_HW_STOP_UPDATEMSGS())
        # try:
        #     self.roll_stage._port._serial.close()
        # except:
        #     pass
        # try:
        #     self.pitch_stage._port._serial.close()
        # except:
        #     pass
        # sleep(2)
        # del self.roll_stage, self.pitch_stage
        # log.info("Procedure shutdown completed.")
