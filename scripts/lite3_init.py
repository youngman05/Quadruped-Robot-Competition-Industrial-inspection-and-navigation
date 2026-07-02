#!/usr/bin/env python3
"""
Lite3 init — heartbeat + stand + nav mode + continuous heartbeat via UDP.

Usage: python3 scripts/lite3_init.py [--dog-ip 192.168.1.120]
"""
import struct, socket, time, argparse

CMD_HEARTBEAT = 0x21040001
CMD_STAND_UP  = 0x21010202
CMD_NAV_MODE  = 0x21010C03
CMD_STOP      = 0x21010C0E

def send(server, addr, code, p1=0, p2=0):
    payload = struct.pack('<3i', code, p1, p2)
    server.sendto(payload, addr)

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dog-ip', default='192.168.1.120')
    p.add_argument('--dog-port', type=int, default=43893)
    args = p.parse_args()

    addr = (args.dog_ip, args.dog_port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print(f'Connecting to dog at {args.dog_ip}:{args.dog_port}...')

    # 1. Heartbeat burst
    for _ in range(10):
        send(sock, addr, CMD_HEARTBEAT)
        time.sleep(0.1)

    # 2. Stand up
    print('Sending: stand up')
    send(sock, addr, CMD_STAND_UP)
    time.sleep(3)

    # 3. Navigation mode
    print('Sending: navigation mode')
    send(sock, addr, CMD_NAV_MODE)
    time.sleep(1)

    # 4. Continuous heartbeat (dog stays active)
    print('Dog ready. Heartbeat active — Ctrl+C to stop.')
    try:
        while True:
            send(sock, addr, CMD_HEARTBEAT)
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        send(sock, addr, CMD_STOP)
        sock.close()
        print('Stopped.')

if __name__ == '__main__':
    main()
