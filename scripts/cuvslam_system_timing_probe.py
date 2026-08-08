#!/usr/bin/env python3
"""Sample Jetson scheduling, IRQ, UDP queue, and tegrastats signals."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Dict, List, Optional, Sequence


DEFAULT_THREAD_PATTERN = (
    r"realsense|visual_slam|component_container|ros_realsense_frame_probe|"
    r"fastdds|fastrtps|dds"
)


def matching_lines(text: str, pattern: str) -> List[str]:
    expression = re.compile(pattern, re.IGNORECASE)
    return [line for line in text.splitlines() if expression.search(line)]


def parse_udp_snmp(text: str) -> Dict[str, int]:
    lines = [line.split() for line in text.splitlines() if line.startswith("Udp:")]
    if len(lines) < 2:
        return {}
    headers = lines[-2][1:]
    values = lines[-1][1:]
    if len(headers) != len(values):
        return {}
    return {name: int(value) for name, value in zip(headers, values)}


def parse_udp_socket_queues(text: str) -> Dict[str, object]:
    rows = []
    total_tx_bytes = 0
    total_rx_bytes = 0
    total_drops = 0
    for line in text.splitlines()[1:]:
        columns = line.split()
        if len(columns) < 13 or ":" not in columns[4]:
            continue
        queue = columns[4].split(":", 1)
        try:
            tx_bytes = int(queue[0], 16)
            rx_bytes = int(queue[1], 16)
            drops = int(columns[-1])
        except ValueError:
            continue
        total_tx_bytes += tx_bytes
        total_rx_bytes += rx_bytes
        total_drops += drops
        if tx_bytes or rx_bytes or drops:
            rows.append(
                {
                    "local_address": columns[1],
                    "remote_address": columns[2],
                    "tx_bytes": tx_bytes,
                    "rx_bytes": rx_bytes,
                    "drops": drops,
                }
            )
    return {
        "socket_count": max(0, len(text.splitlines()) - 1),
        "total_tx_bytes": total_tx_bytes,
        "total_rx_bytes": total_rx_bytes,
        "total_drops": total_drops,
        "nonzero_queues_or_drops": rows,
    }


def run_command(command: Sequence[str], timeout_s: float = 5.0) -> Dict[str, object]:
    try:
        result = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return {
            "command": list(command),
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"command": list(command), "error": str(error)}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="ascii", errors="replace")
    except OSError as error:
        return f"READ_ERROR: {error}"


def collect_sample(container_name: str, thread_pattern: str) -> Dict[str, object]:
    interrupts = read_text(Path("/proc/interrupts"))
    udp = read_text(Path("/proc/net/udp"))
    udp6 = read_text(Path("/proc/net/udp6"))
    thread_result = run_command(
        ["ps", "-eLo", "pid,tid,psr,pcpu,stat,comm,args", "--no-headers"]
    )
    ss_result = run_command(["ss", "-u", "-a", "-n", "-m", "-p"])
    docker_command = ["docker", "stats", "--no-stream", "--format", "{{json .}}"]
    if container_name:
        docker_command.append(container_name)
    docker_result = run_command(docker_command)
    return {
        "wall_time_ns": time.time_ns(),
        "monotonic_ns": time.monotonic_ns(),
        "loadavg": read_text(Path("/proc/loadavg")).strip(),
        "cpu_pressure": read_text(Path("/proc/pressure/cpu")).strip(),
        "softnet_stat": read_text(Path("/proc/net/softnet_stat")).splitlines(),
        "udp_snmp": parse_udp_snmp(read_text(Path("/proc/net/snmp"))),
        "udp4_queues": parse_udp_socket_queues(udp),
        "udp6_queues": parse_udp_socket_queues(udp6),
        "xhci_irq_lines": matching_lines(interrupts, r"xhci|xusb|usb"),
        "threads": matching_lines(str(thread_result.get("stdout", "")), thread_pattern),
        "thread_probe_error": thread_result.get("error")
        or thread_result.get("stderr", ""),
        "ss_udp": ss_result,
        "docker_stats": docker_result,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--container-name", default="")
    parser.add_argument("--thread-pattern", default=DEFAULT_THREAD_PATTERN)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.duration <= 0.0 or args.interval <= 0.0:
        raise SystemExit("--duration and --interval must be > 0")
    re.compile(args.thread_pattern)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    tegrastats_process: Optional[subprocess.Popen] = None
    tegrastats_handle = None
    tegrastats_path = shutil.which("tegrastats")
    if tegrastats_path:
        tegrastats_handle = (args.output_dir / "tegrastats.log").open(
            "w", encoding="utf-8"
        )
        tegrastats_process = subprocess.Popen(
            [tegrastats_path, "--interval", str(round(args.interval * 1000.0))],
            stdout=tegrastats_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
    else:
        (args.output_dir / "tegrastats_unavailable.txt").write_text(
            "tegrastats was not found on PATH\n", encoding="utf-8"
        )

    sample_count = 0
    output_path = args.output_dir / "system_samples.jsonl"
    try:
        with output_path.open("w", encoding="utf-8") as output:
            started = time.monotonic()
            next_sample = started
            while time.monotonic() - started < args.duration:
                sample = collect_sample(args.container_name, args.thread_pattern)
                output.write(json.dumps(sample, sort_keys=True) + "\n")
                output.flush()
                sample_count += 1
                next_sample += args.interval
                delay = next_sample - time.monotonic()
                if delay > 0.0:
                    time.sleep(delay)
    finally:
        if tegrastats_process is not None:
            tegrastats_process.terminate()
            try:
                tegrastats_process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                tegrastats_process.kill()
                tegrastats_process.wait(timeout=5.0)
        if tegrastats_handle is not None:
            tegrastats_handle.close()

    summary = {
        "duration_s": args.duration,
        "interval_s": args.interval,
        "sample_count": sample_count,
        "container_name": args.container_name,
        "thread_pattern": args.thread_pattern,
        "tegrastats_available": bool(tegrastats_path),
    }
    (args.output_dir / "system_probe_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
