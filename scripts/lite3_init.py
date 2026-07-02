#!/usr/bin/env python3
"""
Lite3 init — send heartbeat + stand + nav mode via UDP.
No GUI, just runs the essential commands once.

Usage: python3 scripts/lite3_init.py [--dog-ip 192.168.2.1]
"""
import struct, socket, time, argparse

CMD_HEARTBEAT = 0x21040001
CMD_STAND_UP  = 0x21010202   # 起立/趴下
CMD_NAV_MODE  = 0x21010C03   # 导航模式(自主)
CMD_STOP      = 0x21010C0E   # 软急停
CMD_MANUAL    = 0x21010C02   # 手动模式

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

    # 1. Heartbeat
    print('[1/3] Heartbeat...')
    for _ in range(10):
        send(sock, addr, CMD_HEARTBEAT)
        time.sleep(0.1)
    print('  Done')

    # 2. Stand up
    print('[2/3] Stand up...')
    send(sock, addr, CMD_STAND_UP)
    time.sleep(3)
    print('  Done')

    # 3. Switch to navigation mode
    print('[3/3] Navigation mode...')
    send(sock, addr, CMD_NAV_MODE)
    time.sleep(1)
    print('  Done')

    print(f'Dog ready for /cmd_vel. Stop: python3 scripts/lite3_init.py --stop')
    sock.close()

if __name__ == '__main__':
    main()
