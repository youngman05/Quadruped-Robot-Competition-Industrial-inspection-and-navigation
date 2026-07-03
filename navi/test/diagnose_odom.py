#!/usr/bin/env python3
"""Diagnostic: dump raw RobotState UDP packets to find correct offsets."""
import socket, struct, time

PORT = 43897
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    sock.bind(("0.0.0.0", PORT))
except OSError as e:
    print(f"Bind error: {e}")
    # Try to receive anyway
sock.settimeout(1.0)

print(f"Listening on UDP :{PORT} for RobotState packets...")
print("Walk the dog forward ~1m, then come back.\n")

samples = []
for i in range(10):
    try:
        data, addr = sock.recvfrom(512)
    except socket.timeout:
        print("Timeout — is the dog on?")
        break

    code = struct.unpack_from('<i', data, 0)[0]
    if code != 2305:
        continue

    print(f"\n--- Packet {i+1} ({len(data)} bytes) ---")

    # Dump raw hex of first 140 bytes (enough to cover RobotState header + key fields)
    hexdump = ' '.join(f'{b:02x}' for b in data[:140])
    print(f"Raw[0:140]: {hexdump}")

    # Try parsing int32 at every 4-byte offset
    print("\nInt32 at each 4B offset (first 10 values):")
    for off in range(0, min(40, len(data) - 4), 4):
        v = struct.unpack_from('<i', data, off)[0]
        print(f"  [{off:3d}] = {v:12d}")

    # Try parsing double at likely pos_world offsets
    print("\nDouble at potential pos_world offsets:")
    for off in [84, 88, 92, 96, 100, 104, 108, 112]:
        if off + 8 <= len(data):
            v = struct.unpack_from('<d', data, off)[0]
            print(f"  [{off:3d}] = {v:12.4f}")

    # Try parsing double at likely rpy offsets
    print("\nDouble at potential rpy[2] (yaw) offsets:")
    for off in [28, 32, 36, 40, 44, 48, 52, 56]:
        if off + 8 <= len(data):
            v = struct.unpack_from('<d', data, off)[0]
            print(f"  [{off:3d}] = {v:12.4f}")

    # Also try: read as raw doubles from offset 12 (start of RobotState data)
    print("\nAll doubles from offset 12 (RobotState data start):")
    for j, off in enumerate(range(12, min(140, len(data) - 8), 8)):
        v = struct.unpack_from('<d', data, off)[0]
        print(f"  [{off:3d}] d{j:2d} = {v:12.4f}")

    samples.append(data)
    if len(samples) >= 5:
        break

print("\n--- Analysis ---")
if len(samples) >= 2:
    print("Comparing 2 packets to find which fields change (dog walked between):")
    d1, d2 = samples[0], samples[-1]
    print("\nInt32 diffs:")
    for off in range(0, min(40, len(d1) - 4, len(d2) - 4), 4):
        v1 = struct.unpack_from('<i', d1, off)[0]
        v2 = struct.unpack_from('<i', d2, off)[0]
        if v1 != v2:
            print(f"  [{off:3d}] {v1:10d} -> {v2:10d}  Δ={v2-v1:+d}")

    print("\nDouble diffs (offsets 12-200):")
    for off in range(12, min(200, len(d1) - 8, len(d2) - 8), 8):
        v1 = struct.unpack_from('<d', d1, off)[0]
        v2 = struct.unpack_from('<d', d2, off)[0]
        if abs(v1 - v2) > 0.001:
            print(f"  [{off:3d}] {v1:10.4f} -> {v2:10.4f}  Δ={v2-v1:+.4f}")

sock.close()
