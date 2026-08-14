"""Pure command selection for the Lite3 cmd_vel bridge."""

CODE_FWD = 320
CODE_YAW = 321
CODE_LAT = 325
MOTION_EPSILON = 0.005
STOP_MOTION_COMMAND = (CODE_FWD, 0.0)


def select_motion_command(vx: float, vy: float, az: float):
    """Return one active Lite3 command; zero input returns the initial stop fallback."""

    if abs(az) > MOTION_EPSILON:
        return CODE_YAW, float(-az)
    if abs(vx) > MOTION_EPSILON:
        return CODE_FWD, float(vx)
    if abs(vy) > MOTION_EPSILON:
        return CODE_LAT, float(vy)
    return STOP_MOTION_COMMAND
