#!/usr/bin/env python3
"""Simple SSH terminal to Jetson — type commands, see output."""
import paramiko, sys

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('100.126.48.49', port=22, username='superwfx666', password='superwfx', timeout=10)

print("Jetson Terminal — type commands, 'exit' to quit")
print("="*50)

channel = client.invoke_shell()
output = b""

while True:
    if channel.recv_ready():
        data = channel.recv(4096)
        output += data
        sys.stdout.write(data.decode('utf-8', errors='replace'))
        sys.stdout.flush()

    if channel.recv_stderr_ready():
        data = channel.recv_stderr(4096)
        sys.stderr.write(data.decode('utf-8', errors='replace'))
        sys.stderr.flush()

    try:
        import select
        r, w, e = select.select([sys.stdin], [], [], 0.1)
        if r:
            cmd = sys.stdin.readline()
            if not cmd or cmd.strip() == 'exit':
                break
            channel.send(cmd)
    except:
        pass

channel.close()
client.close()
print("\nDisconnected.")
