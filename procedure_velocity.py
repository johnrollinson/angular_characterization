import logging

from agilent import E364A
from keithley import Keithley6487
import numpy as np
from typing import List
from time import sleep
from pymeasure.adapters import VISAAdapter
from pymeasure.experiment import Procedure
from pymeasure.experiment import (
    BooleanParameter,
    IntegerParameter,
    FloatParameter,
    Parameter,
)
from stage.motor_ctrl import MotorCtrl
from stage.motor_ini.core import find_stages
from stage.ctrl_msg import MGMSG_MOT_MOVE_JOG, MGMSG_MOT_SET_JOGPARAMS

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)
log.addHandler(logging.StreamHandler())


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


class VelocityAngleSweep(Procedure):
    """
    Sweep angle over specified range and measure photocurrent at each increment
    """

    test_name = Parameter("Test Name")

    sweep_roll = BooleanParameter("Sweep Roll Axis", default=True)
    roll_angle_start = FloatParameter(
        "Roll Start Angle",
        minimum=-45,
        maximum=45,
        units="deg",
        default=0,
        group_by="sweep_roll",
    )
    roll_angle_stop = FloatParameter(
        "Roll Stop Angle",
        minimum=-45,
        maximum=45,
        units="deg",
        default=20,
        group_by="sweep_roll",
    )
    roll_angle_vel = FloatParameter(
        "Roll Angle Velocity ",
        units="deg/sec",
        default=0.1,
        group_by="sweep_roll",
    )

    sweep_pitch = BooleanParameter("Sweep Pitch Axis", default=True)
    pitch_angle_start = FloatParameter(
        "Pitch Start Angle",
        minimum=-45,
        maximum=45,
        units="deg",
        default=2.5,
        group_by="sweep_pitch",
    )
    pitch_angle_stop = FloatParameter(
        "Pitch Stop Angle",
        minimum=-45,
        maximum=45,
        units="deg",
        default=-2.5,
        group_by="sweep_pitch",
    )
    pitch_angle_step = FloatParameter(
        "Pitch Angle Step", units="deg", default=0.1, group_by="sweep_pitch"
    )

    delay = FloatParameter("Trigger Delay", units="ms", default=10)
    bias_voltage = FloatParameter(
        "Detector Bias Voltage", minimum=-3, maximum=3, units="V", default=0
    )
    laser_current = FloatParameter(
        "Optical Source Current", units="mA", maximum=200
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
        # Set up continuous triggering
        self.picoammeter.write("ARM:SOUR IMM")
        self.picoammeter.write("ARM:COUN 1")
        self.picoammeter.write("TRIG:SOUR IMM")
        self.picoammeter.write("TRIG:COUN INF")
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

        # Set the roll and pitch jog step size
        log.info(
            f"Setting roll jog step size to {abs(self.pitch_angle_stop - self.roll_angle_start)}deg"
        )
        set_jog_step(
            self.pitch_stage,
            abs(self.pitch_angle_stop - self.roll_angle_start),
            self.roll_angle_vel,
        )
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

        # Level the two stage axes
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
        if self.sweep_roll:
            # Move roll axis to the starting angle
            log.info(
                "Moving roll axis to starting angle: {}.".format(
                    self.roll_angle_start
                )
            )
            move_stage_to(
                self.roll_stage,
                self.roll_angle_start + self.roll_offset,
                blocking=True,
            )
            check = 0
            while not np.isclose(
                self.roll_stage.pos,
                self.roll_angle_start + self.roll_offset,
                atol=0.01,
            ):
                check += 1
                sleep(1)
                if check >= 20:
                    log.warning(
                        "Moving roll to start position timed out (20s), stage move may not have succeeded."
                    )
                    break
            n_steps_roll = 1
            roll_dir = 1 if self.roll_angle_stop < self.roll_angle_start else 2
        else:
            n_steps_roll = 1

        if self.sweep_pitch:
            # Move pitch axis to the starting angle
            log.info(
                "Moving pitch axis to starting angle: {}.".format(
                    self.pitch_angle_start
                )
            )
            move_stage_to(
                self.pitch_stage,
                self.pitch_angle_start + self.pitch_offset,
                blocking=True,
            )
            check = 0
            while not np.isclose(
                self.pitch_stage.pos,
                self.pitch_angle_start + self.pitch_offset,
                atol=0.01,
            ):
                check += 1
                sleep(1)
                if check >= 20:
                    log.warning(
                        "Moving pitch to start position timed out (20s), stage move may not have succeeded."
                    )
                    break
            n_steps_pitch = int(
                np.abs(self.pitch_angle_stop - self.pitch_angle_start)
                / np.abs(self.pitch_angle_step)
                + 1
            )
            pitch_dir = (
                1 if self.pitch_angle_stop < self.pitch_angle_start else 2
            )
        else:
            n_steps_pitch = 1

        iterations = n_steps_pitch * n_steps_roll
        k = 0

        log.info("Beginning measurement")
        for i in range(n_steps_pitch):
            # Set the constant velocity
            # self.roll_stage.set_jog(self.roll_angle_vel, self.roll_angle_vel+0.01, 25)

            # Initiate constant velocity position sweep
            move_jog(self.roll_stage, roll_dir)

            # Initiate constant readings trigger
            self.picoammeter.write("INIT")

            # Monitor position until we get to the final position
            check = 0
            while not np.isclose(
                self.roll_stage.pos,
                self.roll_angle_stop + self.roll_offset,
                atol=0.01,
            ):
                check += 1
                sleep(0.1)
                if check >= 300:
                    log.warning(
                        "Moving roll to start position timed out (30s), stage move may not have succeeded."
                    )
                    break

            # Stop the triggering
            self.picoammeter.write("ABOR")

            # Read the buffer
            n_samples = int(self.picoammeter.buffer_size)
            log.info(f"Buffer size: {n_samples}")
            trace_data = self.picoammeter.ask(":TRAC:DATA?").replace("A", "")
            trace_data = np.fromstring(trace_data, sep=",").reshape(
                (n_samples, 4)
            )
            roll_angles = np.linspace(
                self.roll_angle_start, self.roll_angle_stop, n_samples
            )
            log.debug(trace_data)
            [
                self.emit(
                    "results",
                    {
                        "Roll Angle": roll_angles[i],
                        "Pitch Angle": self.pitch_stage.pos - self.pitch_offset,
                        "Detector Current": trace_data[i, 0],
                    },
                )
                for i in range(n_samples)
            ]

            # Set max move velocity and move back to start
            self.roll_stage.set_vel_params(24.99, 25, 25)
            log.info(
                "Moving roll axis to starting angle: {}.".format(
                    self.roll_angle_start
                )
            )
            move_stage_to(
                self.roll_stage,
                self.roll_angle_start + self.roll_offset,
                blocking=True,
            )
            check = 0
            while not np.isclose(
                self.roll_stage.pos,
                self.roll_angle_start + self.roll_offset,
                atol=0.01,
            ):
                check += 1
                sleep(1)
                if check >= 20:
                    log.warning(
                        "Moving roll to start position timed out (20s), stage move may not have succeeded."
                    )
                    break

            # Step pitch
            move_jog(self.pitch_stage, pitch_dir)

            if self.should_stop():
                log.info("Caught stop flag during procedure.")
                break

        log.info("Procedure completed.")

    def shutdown(self):
        # TODO: After procedure completes, return both axes to 0deg
        log.info("Executing procedure shutdown.")
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
        log.info("Procedure shutdown completed.")
