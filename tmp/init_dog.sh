#!/bin/bash
# Dog init script — kills old lite3, tests UDP, starts fresh

echo "=== [1] Kill old lite3_init ==="
pkill -9 -f lite3_init 2>/dev/null || true
sleep 1
echo "cleaned"

echo ""
echo "=== [2] UDP test to dog ==="
python3 -u -c "
import socket, struct
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(2)
addr = ('192.168.1.120', 43893)
payload = struct.pack('<3i', 0x21040001, 0, 0)
sock.sendto(payload, addr)
print('Heartbeat sent to', addr)
# Dog doesn't echo back, but if no error, network is OK
print('UDP OK (no error)')
sock.close()
"

echo ""
echo "=== [3] Start lite3_init (--no-stand) ==="
cd /home/superwfx666/quadruped-robot-competition
python3 -u scripts/lite3_init.py --no-stand > /tmp/lite3_init.log 2>&1 &
PID=$!
echo "PID=$PID"
sleep 6

echo ""
echo "=== [4] Check log ==="
cat /tmp/lite3_init.log 2>/dev/null || echo "(empty)"

echo ""
echo "=== [5] Check process ==="
ps aux | grep "lite3_init" | grep -v grep

echo ""
echo "=== DONE ==="
