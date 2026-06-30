"""Execute a command on the Jetson via SSH and print the result."""
import sys
import paramiko

HOST = '100.126.48.49'
USER = 'superwfx666'
PASS = 'superwfx'

cmd = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else 'hostname; echo DONE'

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    c.connect(HOST, username=USER, password=PASS, timeout=15,
              look_for_keys=False, allow_agent=False)
    _, stdout, stderr = c.exec_command(cmd, timeout=30)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out:
        print(out, end='')
    if err:
        print(f'STDERR: {err}', file=sys.stderr)
except Exception as e:
    print(f'SSH ERROR: {e}', file=sys.stderr)
    sys.exit(1)
finally:
    c.close()
