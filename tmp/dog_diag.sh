#!/bin/bash
echo "========================================"
echo "  Dog Connectivity Diagnostic"
echo "========================================"

DOG_IP="192.168.1.120"
DOG_PORT=43893

# 1. Ping test
echo ""
echo "[1] Ping test to $DOG_IP"
ping -c 2 -W 2 $DOG_IP && echo "   PING OK" || echo "   PING FAILED"

# 2. Check if local UDP port is available
echo ""
echo "[2] Network interfaces"
ip addr show | grep "inet " | grep -v 127.0.0.1

# 3. Send direct heartbeat + auto mode + motion test
echo ""
echo "[3] Direct UDP init + motion test"
python3 -u << 'PYEOF'
import socket, struct, time

DOG = ("192.168.1.120", 43893)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send_simple(code, p1=0, p2=0):
    sock.sendto(struct.pack("<3i", code, p1, p2), DOG)

def send_complex(code, data):
    sock.sendto(struct.pack("<3id", code, 8, 1, float(data)), DOG)

# ---- Init sequence ----
print("   Sending heartbeats...")
for i in range(5):
    send_simple(0x21040001)  # HEARTBEAT
    time.sleep(0.1)
print("   OK")

print("   Sending auto mode (0x21010C03)...")
send_simple(0x21010C03)      # AUTO MODE - KEY!
time.sleep(0.5)
print("   OK")

print("   Sending motion mode (0x21010D06)...")
send_simple(0x21010D06)      # MOTION MODE
time.sleep(0.3)
print("   OK")

# ---- Try to move ----
print("   Sending forward 0.3 m/s...")
for i in range(10):
    send_simple(0x21040001)  # heartbeat
    send_complex(320, 0.3)   # CODE_FWD = 320, velocity = 0.3
    time.sleep(0.1)

print("   Sending stop...")
for i in range(5):
    send_simple(0x21040001)
    send_complex(320, 0.0)
    time.sleep(0.1)

print("   DONE - check if dog moved")
sock.close()
PYEOF

echo ""
echo "[4] Check lite3_init process"
ps aux | grep lite3_init | grep -v grep || echo "   NOT RUNNING"

echo ""
echo "[5] Check odom"
cat /tmp/odom_latest.json 2>/dev/null || echo "   NO ODOM FILE"

echo ""
echo "========================================"
echo "  If dog didn't move after step [3],"
echo "  the UDP link to the dog is broken."
echo "  Check: 1) Dog is powered ON"
echo "        2) Dog is standing (not lying)"
echo "        3) Dog IP is $DOG_IP"
echo "========================================"
