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
from stage.ctrl_msg import MGMSG_MOT_MOVE_STOP, MGMSG_MOT_MOVE_VELOCITY
from stage.motor_ctrl import MotorCtrl
from stage.motor_ini.core import find_stages

from agilent import E364A
from keithley import Keithley6487
from procedures import move_jog, move_stage_to, set_jog_step, level_axes, convert_unsigned

from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


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
    Sweep angle over specified range and measure photocurrent at each increment.

    This procedure utilizes the "constant velocity" move mode of the motor controllers
    rather than the fixed step move mode. In this mode, the idea is to read the current
    and angular position as fast as possible while the DUT rotates at a constant
    velocity. While this will result in noisy measurement, the goal is that we will be
    reading fast enough to smooth out the data in post-processing (e.g. either using
    spline fitting or nearest-neighbor smoothing). 
    
    Hopefully the continuous velocity movement combined with oversampling and smoothing
    should reduce test time compared to the fixed step size method, while still getting
    sufficiently accurate results.
    """

    test_name = Parameter("Test Name")

    roll_angle_start = FloatParameter(
        "Roll Start Angle",
        minimum=-45,
        maximum=45,
        units="deg",
        default=0,
    )
    roll_angle_stop = FloatParameter(
        "Roll Stop Angle",
        minimum=-45,
        maximum=45,
        units="deg",
        default=20,
    )
    roll_angle_vel = FloatParameter(
        "Roll Angle Velocity ",
        units="deg/sec",
        default=10,
    )
    pitch_angle_start = FloatParameter(
        "Pitch Start Angle",
        minimum=-45,
        maximum=45,
        units="deg",
        default=5,
    )
    pitch_angle_stop = FloatParameter(
        "Pitch Stop Angle",
        minimum=-45,
        maximum=45,
        units="deg",
        default=-5,
    )
    pitch_angle_vel = FloatParameter(
        "Pitch Angle Velocity ",
        units="deg/sec",
        default=1,
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
        adapter = VISAAdapter("GPIB0::22::INSTR", visa_library="@py")
        self.picoammeter = Keithley6487(adapter)
        self.picoammeter.write("*RST")
        self.picoammeter.configure(nplc=0.1, n_avg=1)
        self.picoammeter.set_bias_voltage(self.bias_voltage)
        # self.picoammeter.write("ARM:SOUR IMM")  # Continuous triggering
        # self.picoammeter.write("ARM:COUN 1")
        # self.picoammeter.write("TRIG:SOUR IMM")
        # self.picoammeter.write("TRIG:COUN INF")
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

    def execute(self):
        log.info("Executing procedure.")

        log.info("Beginning measurement")

        args = [
            ["roll", self.roll_stage, self.roll_angle_start+self.roll_offset, self.roll_angle_stop+self.roll_offset, self.roll_angle_vel],
            ["pitch", self.pitch_stage, self.pitch_angle_start+self.pitch_offset, self.pitch_angle_stop+self.pitch_offset, self.pitch_angle_vel]
        ]

        with ThreadPoolExecutor(max_workers=4) as executor:
            threads = {executor.submit(self.oscillate_stage, *arg[1:]): arg[0] for arg in args}
            threads[executor.submit(self.current_measurement)] = "current_meas"
            for stage_name in as_completed(threads):
                print(stage_name)

        log.info("Procedure completed.")
    
    def current_measurement(self):
        meas_interval = 0.01
        while True:
            curr = self.picoammeter.get_current()
            self.emit(
                "results",
                {
                    "Roll Angle": self.roll_stage.pos - self.roll_offset,
                    "Pitch Angle": self.pitch_stage.pos - self.pitch_offset,
                    "Detector Current": curr,
                },
            )
            if self.should_stop():
                log.info("Caught stop flag during procedure.")
                break
            # sleep(meas_interval)

    def oscillate_stage(self, stage: MotorCtrl, min_angle, max_angle, velocity, interval=0.1):
        # TODO: The logic of this method needs to be more robust against all cases
        # e.g. right now this function cannot handle the case when 0 in [min_angle, max_angle]
        # as it will get confused about the angular wrapping

        # Set stage to starting position
        move_stage_to(stage, min_angle, blocking=True)

        # Set the maximum move velocity
        stage.set_max_vel(velocity)
        direction = 2

        # min_angle = convert_unsigned(min_angle)
        # max_angle = convert_unsigned(max_angle)

        # Start the velocity movement
        stage._port.send_message(MGMSG_MOT_MOVE_VELOCITY(chan_ident=stage._chan_ident, direction=direction))
        while True:
            pos = stage.pos
            if direction == 2 and pos > max_angle:
                direction = direction%2 + 1
                stage._port.send_message(MGMSG_MOT_MOVE_VELOCITY(chan_ident=stage._chan_ident, direction=direction))
            elif direction == 1 and pos < min_angle:
                direction = direction%2 + 1
                stage._port.send_message(MGMSG_MOT_MOVE_VELOCITY(chan_ident=stage._chan_ident, direction=direction))
            
            if self.should_stop():
                log.info("Caught stop flag during procedure.")
                stage._port.send_message(MGMSG_MOT_MOVE_STOP(chan_ident=stage._chan_ident, stop_mode=2))
                break
            
            sleep(interval)

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


if __name__ == "__main__":
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def oscillate_stage(stage: MotorCtrl, min_angle, max_angle, velocity, interval=0.1):
        # TODO: The logic of this method needs to be more robust against all cases
        # e.g. right now this function cannot handle the case when 0 in [min_angle, max_angle]
        # as it will get confused about the angular wrapping

        # Set stage to starting position
        move_stage_to(stage, min_angle, blocking=True)

        # Set the maximum move velocity
        stage.set_max_vel(velocity)
        direction = 2

        # min_angle = convert_unsigned(min_angle)
        # max_angle = convert_unsigned(max_angle)

        # Start the velocity movement
        stage._port.send_message(MGMSG_MOT_MOVE_VELOCITY(chan_ident=stage._chan_ident, direction=direction))
        try:
            print(min_angle, max_angle)
            while True:
                pos = stage.pos
                print(pos)
                if direction == 2 and pos > max_angle:
                    print("Reverse")
                    direction = direction%2 + 1
                    stage._port.send_message(MGMSG_MOT_MOVE_VELOCITY(chan_ident=stage._chan_ident, direction=direction))
                elif direction == 1 and pos < min_angle:
                    print("Reverse")
                    direction = direction%2 + 1
                    stage._port.send_message(MGMSG_MOT_MOVE_VELOCITY(chan_ident=stage._chan_ident, direction=direction))
                
                sleep(interval)
        except:
            stage._port.send_message(MGMSG_MOT_MOVE_STOP(chan_ident=stage._chan_ident, stop_mode=2))

    roll_stage.set_max_vel(25)
    pitch_stage.set_max_vel(25)
    level_axes()

    roll_offset = 45
    pitch_offset = -32.7

    args = [
        ["roll", roll_stage, -20+roll_offset, 0+roll_offset, 10],
        ["pitch", pitch_stage, -5+pitch_offset, 5+pitch_offset, 1]
    ]

    oscillate_stage(pitch_stage, -5+pitch_offset, 5+pitch_offset, 10)

    # adapter = VISAAdapter("GPIB0::22::INSTR", visa_library="@py")
    # picoammeter = Keithley6487(adapter)
    # picoammeter.configure(nplc=0.1, n_avg=1)
    # picoammeter.write("ARM:SOUR IMM")  # Continuous triggering
    # picoammeter.write("ARM:COUN 1")
    # picoammeter.write("TRIG:SOUR IMM")
    # picoammeter.write("TRIG:COUN INF")

    # while True:
    #     roll_pos = roll_stage.pos - roll_offset
    #     pitch_pos = pitch_stage.pos - pitch_offset
    #     curr = picoammeter.get_current()
    #     print(roll_pos, pitch_pos, curr)
    #     sleep(0.1)

    # with ThreadPoolExecutor(max_workers=4) as executor:
    #     threads = {executor.submit(oscillate_stage, *arg[1:]): arg[0] for arg in args}
    #     for stage_name in as_completed(threads):
    #         print(stage_name)

    # sleep(120)
