"""
Dog motion control API.

Usage:
    from motion import MotionController

    mc = MotionController()
    mc.initialize()

    # Low-level (for Navigator pure pursuit):
    mc.set_velocity(0.3, 0.0)    # 0.3 m/s forward

    # High-level (for task_manager):
    mc.turn_to(180)               # turn to 180 deg
    mc.move_forward(3.0)          # walk 3m (PID)

    # Pose:
    x, y, yaw = mc.pose

    mc.shutdown()
"""

from .motion_controller import MotionController, OdomFreezeError

__all__ = ["MotionController", "OdomFreezeError"]
