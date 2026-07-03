#!/usr/bin/env python3
"""
Lite3 init — heartbeat + stand + auto mode + motion mode via UDP.

Usage:
  python3 scripts/lite3_init.py                      # full init
  python3 scripts/lite3_init.py --no-stand           # skip stand toggle
  python3 scripts/lite3_init.py --dog-ip 192.168.1.120
"""
import struct, socket, time, argparse, signal, sys

CMD_HEARTBEAT = 0x21040001
CMD_STAND_UP  = 0x21010202    # toggle: stand ↔ lie down
CMD_AUTO_MODE = 0x21010C03    # 自动模式 (accepts SDK velocity cmds)
CMD_MOTION    = 0x21010D06    # 移动模式
CMD_STOP      = 0x21010C0E

def send(server, addr, code, p1=0, p2=0):
    payload = struct.pack('<3i', code, p1, p2)
    server.sendto(payload, addr)

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dog-ip', default='192.168.1.120')
    p.add_argument('--dog-port', type=int, default=43893)
    p.add_argument('--no-stand', action='store_true',
                   help='Skip stand toggle (dog already standing)')
    p.add_argument('--heartbeat-only', action='store_true',
                   help='Only send heartbeat (dog fully init elsewhere)')
    args = p.parse_args()

    addr = (args.dog_ip, args.dog_port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def cleanup(sig=None, frame=None):
        send(sock, addr, CMD_STOP)
        sock.close()
        sys.exit(0)
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    print(f'Dog at {args.dog_ip}:{args.dog_port}')

    if args.heartbeat_only:
        print('Heartbeat only mode')
        try:
            while True:
                send(sock, addr, CMD_HEARTBEAT)
                time.sleep(0.5)
        except KeyboardInterrupt:
            cleanup()

    # 1. Heartbeat burst
    for _ in range(10):
        send(sock, addr, CMD_HEARTBEAT)
        time.sleep(0.1)

    # 2. Stand up (skip if dog already standing)
    if not args.no_stand:
        print('Sending: stand up')
        send(sock, addr, CMD_STAND_UP)
        time.sleep(3)
    else:
        print('Skip stand (--no-stand)')

    # 3. Auto mode — ESSENTIAL for SDK velocity commands
    print('Sending: auto mode (0x21010C03)')
    send(sock, addr, CMD_AUTO_MODE)
    time.sleep(1)

    # 4. Motion mode
    print('Sending: motion mode (0x21010D06)')
    send(sock, addr, CMD_MOTION)
    time.sleep(0.5)

    # 5. Continuous heartbeat
    print('Dog ready. Heartbeat active — Ctrl+C to stop.')
    try:
        while True:
            send(sock, addr, CMD_HEARTBEAT)
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()

if __name__ == '__main__':
    main()
