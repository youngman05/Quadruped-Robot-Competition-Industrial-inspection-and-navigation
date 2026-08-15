#!/usr/bin/env python3
# coding: utf-8

"""幻尔/LOBOT 老款总线舵机协议。

BusLinker 只负责 USB 转半双工总线，真正发给舵机的是 55 55 协议帧。
"""

import time


CMD_MOVE_TIME_WRITE = 1
CMD_ID_READ = 14
CMD_POS_READ = 28


def checksum(packet_without_sum):
    """计算校验和。

    校验范围不包含两个 0x55 帧头，只包含 ID、长度、命令和参数。
    """

    return (~sum(packet_without_sum[2:])) & 0xFF


def make_packet(servo_id, cmd, params=()):
    """组装一条完整协议包。"""

    packet = bytearray([0x55, 0x55, int(servo_id) & 0xFF, 3 + len(params), int(cmd) & 0xFF])
    packet.extend(int(p) & 0xFF for p in params)
    packet.append(checksum(packet))
    return bytes(packet)


def read_response(ser, timeout=0.08):
    """读取一个完整返回包，超时返回 None。"""

    deadline = time.time() + timeout
    buf = bytearray()
    while time.time() < deadline:
        waiting = ser.in_waiting
        if waiting:
            buf.extend(ser.read(waiting))
            while len(buf) >= 2 and buf[:2] != b"\x55\x55":
                del buf[0]
            if len(buf) >= 4:
                total = 3 + buf[3]
                if len(buf) >= total:
                    packet = bytes(buf[:total])
                    expected = checksum(packet[:-1])
                    if packet[-1] != expected:
                        raise RuntimeError(
                            "校验和错误：收到 0x%02X，期望 0x%02X，包=%s"
                            % (packet[-1], expected, packet.hex(" "))
                        )
                    return packet
        time.sleep(0.001)
    return None


def transact(ser, servo_id, cmd, params=(), timeout=0.08):
    """发送命令并等待返回。"""

    ser.reset_input_buffer()
    ser.write(make_packet(servo_id, cmd, params))
    ser.flush()
    return read_response(ser, timeout=timeout)


def read_id(ser, servo_id):
    """读取指定 ID 舵机的 ID 返回。"""

    return transact(ser, servo_id, CMD_ID_READ)


def read_position(ser, servo_id):
    """读取当前舵机位置，单位是 pulse。"""

    packet = transact(ser, servo_id, CMD_POS_READ)
    if not packet:
        return None
    if len(packet) < 7:
        raise RuntimeError("位置返回包过短：%s" % packet.hex(" "))
    raw = packet[5] | (packet[6] << 8)
    if raw & 0x8000:
        raw -= 0x10000
    return raw


def move_to_position(ser, servo_id, pos, duration_ms):
    """让一个舵机转到指定 pulse。"""

    pos = max(0, min(1000, int(pos)))
    duration_ms = max(0, min(30000, int(duration_ms)))
    params = (
        pos & 0xFF,
        (pos >> 8) & 0xFF,
        duration_ms & 0xFF,
        (duration_ms >> 8) & 0xFF,
    )
    ser.write(make_packet(servo_id, CMD_MOVE_TIME_WRITE, params))
    ser.flush()


def scan_ids(ser, start=1, end=6, retries=3, verbose=False):
    """逐个扫描 ID，避免总线多舵机同时回复造成冲突。"""

    found = []
    seen = set()
    for servo_id in range(int(start), int(end) + 1):
        for attempt in range(1, int(retries) + 1):
            packet = read_id(ser, servo_id)
            if packet and len(packet) >= 6:
                reported = packet[5]
                if reported not in seen:
                    found.append(reported)
                    seen.add(reported)
                if verbose:
                    print("ID %d 有响应，第 %d 次，返回包：%s" % (reported, attempt, packet.hex(" ")))
                break
            time.sleep(0.02)
    return sorted(found)
