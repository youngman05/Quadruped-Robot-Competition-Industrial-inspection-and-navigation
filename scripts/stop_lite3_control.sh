#!/usr/bin/env bash
set -u

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PID_FILE=/tmp/lite3_control.pid

python3 - <<'PY'
import socket
import struct
import time

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
address = ("192.168.1.120", 43893)
for _ in range(12):
    for code in (320, 325, 321):
        sock.sendto(struct.pack("<3id", code, 8, 1, 0.0), address)
    time.sleep(0.025)
sock.close()
PY

if [[ -f "$PID_FILE" ]]; then
  pid=$(cat "$PID_FILE")
  kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.1
  done
  kill -KILL "$pid" 2>/dev/null || true
  rm -f "$PID_FILE"
fi

pkill -TERM -f '[j]etson2motion' 2>/dev/null || true
pkill -TERM -f '[j]etson2app' 2>/dev/null || true
pkill -TERM -f '[s]ensor_checker' 2>/dev/null || true
pkill -TERM -f '[c]md_vel_bridge' 2>/dev/null || true
echo "Lite3 control stopped; all velocity axes cleared"
