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
log.addHandler(logging.NullHandler())

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

    roll_angle_step = FloatParameter(
        "Roll Angle Step", units="deg", default=0.1
    )
    pitch_angle_step = FloatParameter(
        "Pitch Angle Step", units="deg", default=0.1
    )

    delay = FloatParameter("Trigger Delay", units="ms", default=10)
    bias_voltage = FloatParameter(
        "Detector Bias Voltage", minimum=-3, maximum=3, units="V", default=0
    )
    laser_current = FloatParameter(
        "Optical Source Current", units="mA", maximum=300
    )

    DATA_COLUMNS = ["Roll Angle", "Pitch Angle", "Detector Current"]

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
        adapter = VISAAdapter(
            "GPIB0::22::INSTR", visa_library="@py", query_delay=0.1
        )
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
        log.info(
            f"Setting roll jog step size to {abs(self.roll_angle_step)}deg"
        )
        set_jog_step(self.roll_stage, abs(self.roll_angle_step), 9.98)
        log.info(
            f"Setting pitch jog step size to {abs(self.pitch_angle_step)}deg"
        )
        set_jog_step(self.pitch_stage, abs(self.pitch_angle_step), 9.98)

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
        prev_meas = self.picoammeter.get_current()
        jog_dir = 1
        peak_meas = -np.inf
        while True:
            # Move one jog step
            move_jog(self.roll_stage, jog_dir)

            # Take new current measurement
            sleep(self.delay*1e-3)
            new_meas = self.picoammeter.get_current()
            # If new meas < old meas, switch directions
            if new_meas < prev_meas:
                log.info("Reversing direction")
                roll_dir = roll_dir % 2 + 1

            peak_meas = np.max(peak_meas, new_meas)
            self.emit(
                "results",
                {
                    "Roll Angle": self.roll_stage.pos - self.roll_offset,
                    "Pitch Angle": self.pitch_stage.pos - self.pitch_offset,
                    "Detector Current": new_meas,
                    "Peak Current": peak_meas
                },
            )

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
