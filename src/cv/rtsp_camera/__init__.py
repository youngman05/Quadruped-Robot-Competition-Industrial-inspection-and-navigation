"""Lite3 RTSP front-camera interface.

Main entry point:
    from cv.rtsp_camera import RTSPCamera

    cam = RTSPCamera()
    frame = cam.read()      # (720, 1280, 3) BGR numpy array
    cam.close()
"""

from .camera import RTSPCamera

__all__ = ["RTSPCamera"]
