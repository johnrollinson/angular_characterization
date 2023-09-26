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
    log.info(f"Found motor stages: {stages}")
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


def move_jog(stage: MotorCtrl, direction, jog_delay=20):
    """Send a jog move message to the motor controller."""
    stage._port.send_message(
        MGMSG_MOT_MOVE_JOG(chan_ident=stage._chan_ident, direction=direction)
    )
    # sleep(jog_delay * 1e-3)


def set_jog_step(stage: MotorCtrl, step, velocity):
    """Set the distance for a jog move."""
    stage._port.send_message(
        MGMSG_MOT_SET_JOGPARAMS(
            chan_ident=stage._chan_ident,
            jog_mode=2,
            jog_step_size=int(step * stage._EncCnt),
            jog_min_velocity=int(
                (velocity) * (stage._EncCnt * stage._T * 65536)
            ),
            jog_acceleration=int(
                9.96 * (stage._EncCnt * (stage._T**2) * 65536)
            ),
            jog_max_velocity=int(
                (velocity + 0.01) * (stage._EncCnt * stage._T * 65536)
            ),
            jog_stop_mode=2,
        )
    )


def move_stage_to(stage: MotorCtrl, targ_pos: float, blocking:bool=False, num_retries:int=3):
    """Move the motor stage to the specified position (in deg).

    The set_pos() function from the stage control module does not behave as expected,
    so this is a simple wrapper function which reads the current position and moves
    to the desired position using the move_by() function.
    """
    log.info(f"Moving {stage.stage_model} to {targ_pos}")

    for _ in range(num_retries):
        # Compute the amount to move
        init_pos = convert_signed(stage.pos)
        offset = targ_pos - init_pos

        log.debug(f"Initial position: {init_pos}")
        log.debug(f"Moving stage by: {offset}")
        stage.move_by(offset, blocking=blocking)

        check = 0
        while not np.isclose(stage.pos, targ_pos, atol=0.01):
            check += 1
            sleep(1)
            if check >= 20:
                log.warning(
                    "Stage move timed out (20s), stages may not have levelled successfully."
                )
                break
        
        log.debug(f"Final position: {stage.pos}")
        if np.isclose(stage.pos, targ_pos, atol=0.01):
            return
        log.warning(f"Final position {stage.pos} not equal to target pos {targ_pos}, retrying stage move")
    raise RuntimeError(f"Could not move stage after {num_retries} retries, aborting.")

def level_axes():
    """Set the both axes to the horizontal measurement for initialization."""
    roll_offset = 45
    pitch_offset = -32.7
    
    # Move both axes to the home position
    log.info("Homing the roll and pitch axes")
    roll_stage.set_home_dir(2)
    pitch_stage.set_home_dir(1)
    roll_stage.move_home(blocking=True)
    pitch_stage.move_home(blocking=True)
    
    check = 0
    while not roll_stage.status_homed or not roll_stage.status_homed:
        check += 1
        sleep(1)
        if check >= 20:
            log.warning(
                "Homing timed out (20s), stages may not have homed successfully."
            )
            break
            
    log.info("Levelling the roll and pitch stages")
    move_stage_to(roll_stage, roll_offset, blocking=True)
    move_stage_to(pitch_stage, pitch_offset, blocking=True)


def convert_signed(pos):
    """Translate `pos` from unsigned [0, 360] range to signed [-180, 180] range."""
    if pos >= 0.0:
        return pos - (pos // 180) * 360
    return pos
    

class DummyProcedure(Procedure):
    """
    A dummy procedure for testing purposes
    """

    param1 = FloatParameter("p1")
    param2 = IntegerParameter("p2")

    DATA_COLUMNS = ["param1", "param2"]

    def startup(self):
        print("This is the startup function for the dummy procedure.")

    def execute(self):
        print("This is the execution function for the dummy procedure.")


class AngleSweep(Procedure):
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

    roll_angle_step = FloatParameter(
        "Roll Angle Step", units="deg", default=0.1, group_by="sweep_roll"
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

        # Calibrate the stage positions
        self.roll_stage.set_vel_params(24.99, 25, 25)
        self.pitch_stage.set_vel_params(24.99, 25, 25)
        level_axes()
        
        # Set jog step size
        log.info(
            f"Setting roll jog step size to {abs(self.roll_angle_step)}deg"
        )
        set_jog_step(self.roll_stage, abs(self.roll_angle_step), 9.98)
        log.info(
            f"Setting pitch jog step size to {abs(self.pitch_angle_step)}deg"
        )
        set_jog_step(self.pitch_stage, abs(self.pitch_angle_step), 9.98)

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
            n_steps_roll = int(
                np.abs(self.roll_angle_stop - self.roll_angle_start)
                / np.abs(self.roll_angle_step)
                + 1
            )
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
            if self.sweep_pitch and i != 0:
                move_jog(self.pitch_stage, pitch_dir)
            for j in range(n_steps_roll):
                if self.sweep_roll and j != 0:
                    move_jog(self.roll_stage, roll_dir)
                curr = self.picoammeter.get_current()
                self.emit(
                    "results",
                    {
                        "Roll Angle": self.roll_stage.pos - self.roll_offset,
                        "Pitch Angle": self.pitch_stage.pos - self.pitch_offset,
                        "Detector Current": curr,
                    },
                )
                self.emit("progress", 100 * k / iterations)
                k += 1
                if self.should_stop():
                    log.info("Caught stop flag during procedure.")
                    break

            # if we are sweeping both stages, we need to reset the roll position
            if self.sweep_roll and self.sweep_pitch:
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


if __name__ == "__main__":
    level_axes()
