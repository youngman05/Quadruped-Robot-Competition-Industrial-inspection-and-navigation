#!/usr/bin/env python3
"""Plot competition trajectory from cmd_vel log + odom file."""
import json, math, sys, os
sys.path.insert(0, os.path.dirname(__file__) + '/../..')

# Read cmd_vel
cmd_vel_file = os.path.expanduser('~/competition_logs/cmd_vel_direct.csv')
data = []
with open(cmd_vel_file) as f:
    for line in f:
        line = line.strip()
        # Skip corrupted lines
        if '\x00' in line or not line:
            continue
        parts = line.split(',')
        if len(parts) != 3:
            continue
        try:
            t, vx, az = float(parts[0]), float(parts[1]), float(parts[2])
            data.append((t, vx, az))
        except ValueError:
            continue

# Only use data from this run (last 60s)
if len(data) > 600:
    data = data[-600:]

t0 = data[0][0]
ts = [d[0]-t0 for d in data]
vx = [d[1] for d in data]
az = [d[2] for d in data]

# Dead-reckoning path from cmd_vel
x_dr, y_dr = [0.0], [0.0]
yaw = 0.0
for i in range(1, len(data)):
    dt = ts[i] - ts[i-1]
    if dt <= 0: dt = 0.1
    yaw += az[i] * dt
    x_dr.append(x_dr[-1] + vx[i] * dt * math.cos(yaw))
    y_dr.append(y_dr[-1] + vx[i] * dt * math.sin(yaw))

# Try to read odom file (cuVSLAM)
odom_x, odom_y = [], []
try:
    odom_file = '/tmp/odom_latest.json'
    import time
    # Can't read historical odom, just note this
    print(f"Dead reckoning: start=(0,0) end=({x_dr[-1]:.2f},{y_dr[-1]:.2f})")
    print(f"VX range: {min(vx):.2f}-{max(vx):.2f}  AZ range: {min(az):.2f}-{max(az):.2f}")
except:
    pass

# Plot
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

fig, axes = plt.subplots(1, 3, figsize=(18, 5))

# cmd_vel
ax = axes[0]
ax.plot(ts, vx, 'b-', lw=0.5, label='vx')
ax.plot(ts, az, 'r-', lw=0.5, label='az')
ax.set_xlabel('time (s)'); ax.legend(); ax.grid(alpha=0.3)
ax.set_title('cmd_vel')

# Path (dead reckoning)
ax = axes[1]
ax.plot(y_dr, x_dr, 'b-', lw=0.6)
ax.scatter(y_dr[0], x_dr[0], c='green', s=60, label='Start')
ax.scatter(y_dr[-1], x_dr[-1], c='red', s=60, label='End')
ax.set_xlabel('Y (m)'); ax.set_ylabel('X (m)')
ax.legend(); ax.grid(alpha=0.3); ax.axis('equal')
ax.set_title('Dead Reckoning Path')

# Speed profile
ax = axes[2]
speed = [math.hypot(vx[i], 0.0) for i in range(len(vx))]
ax.plot(ts, speed, 'g-', lw=0.5)
ax.set_xlabel('time (s)'); ax.set_ylabel('speed (m/s)')
ax.grid(alpha=0.3); ax.set_title('Speed Profile')

out = 'navi/test/output/competition_path.png'
fig.tight_layout()
fig.savefig(out, dpi=150)
print(f'Saved: {out}')
