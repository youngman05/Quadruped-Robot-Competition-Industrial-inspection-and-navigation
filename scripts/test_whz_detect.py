#!/usr/bin/env python3
"""Direct whz detection — reads relay files, zero DDS."""
import sys, json, time, cv2, numpy as np
from pathlib import Path
from collections import Counter

_WS = Path(__file__).resolve().parents[1]
_SRC = _WS / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from whz.letter_detector import LetterDetector
from whz.gauge_detector import detect_gauge
from whz.audio_player import AudioPlayer
from whz.paths import default_audio_dir, default_template_dir

RELAY = Path.home() / 'workspaces' / 'isaac_ros-dev' / 'camera_frames'
COLOR_JPG = RELAY / 'latest_color.jpg'
DEPTH_RAW = RELAY / 'latest_depth.raw'
DEPTH_META = RELAY / 'latest_depth_meta.txt'
TEMPLATE_DIR = default_template_dir()
AUDIO_DIR = default_audio_dir()

print(f'JPEG: {COLOR_JPG}  exists={COLOR_JPG.exists()}')
print(f'Depth: {DEPTH_RAW}  exists={DEPTH_RAW.exists()}')

letter_det = LetterDetector(TEMPLATE_DIR, min_score=0.38)
audio_player = AudioPlayer(AUDIO_DIR)

# Read 3 frames
frames = []
for i in range(3):
    if not COLOR_JPG.exists():
        print(f'Frame {i}: JPEG missing')
        sys.exit(1)
    color = cv2.imread(str(COLOR_JPG), cv2.IMREAD_COLOR)
    if color is None:
        print(f'Frame {i}: cv2.imread failed')
        sys.exit(1)

    depth = None
    if DEPTH_RAW.exists():
        try:
            raw = DEPTH_RAW.read_bytes()
            w, h = 640, 360
            if DEPTH_META.exists():
                parts = DEPTH_META.read_text().strip().split()
                if len(parts) >= 2:
                    w, h = int(parts[0]), int(parts[1])
            if len(raw) == w * h * 2:
                depth = np.frombuffer(raw, dtype=np.uint16).reshape(h, w).astype(np.float32) * 0.001
        except Exception:
            pass
    frames.append((color, depth))
    if i < 2:
        time.sleep(0.3)

print(f'Read {len(frames)} frames')

# Detect each frame
results = []
for i, (color, depth) in enumerate(frames):
    letter = letter_det.detect(color)
    gauge = detect_gauge(color, depth)
    if letter and gauge:
        above = False
        if letter.bbox:
            ly = (letter.bbox[1] + letter.bbox[3]) / 2.0
            above = ly < gauge.center_y
        results.append({
            'ok': True, 'frame': i,
            'area': letter.area, 'score': round(letter.score, 4),
            'state': gauge.state_key, 'level': gauge.level,
            'status': gauge.status, 'color': gauge.color,
            'above': above,
        })
        print(f'  Frame{i}: {letter.area} score={letter.score:.3f}  '
              f'{gauge.state_key}/{gauge.color}  above={above}')
    else:
        status = f'letter={"OK" if letter else "FAIL"}({letter.area if letter else "?"})'
        stat2 = f'gauge={"OK" if gauge else "FAIL"}'
        print(f'  Frame{i}: {status}  {stat2}')

if not results:
    print('NO DETECTIONS — is the camera pointed at a cabinet face?')
    sys.exit(1)

# Majority vote
votes = Counter((r['area'], r['state']) for r in results)
(area, state), count = votes.most_common(1)[0]
best = max(
    [r for r in results if r['area'] == area and r['state'] == state],
    key=lambda r: r.get('score', 0),
)

print(f'\n===== RESULT =====')
print(f'  Area: {area}')
print(f'  State: {best["state"]} ({best["status"]})')
print(f'  Color: {best["color"]}')
print(f'  Vote: {count}/{len(results)}')
print(f'  Letter above gauge: {best["above"]}')

# Play audio
try:
    audio_player.play(audio_player.audio_path_for(area, state))
    print('  Audio: played')
except Exception as e:
    print(f'  Audio: failed ({e})')
print('===== DONE =====')
