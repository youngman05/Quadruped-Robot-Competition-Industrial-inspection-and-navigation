"""Deploy whz package to Jetson via paramiko."""
import paramiko
import base64
import os

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('100.126.48.49', username='superwfx666', password='superwfx', timeout=10)

BASE = r'c:\Users\tom\Desktop\quadruped-robot-competition-main\whz'
REMOTE = '/home/superwfx666/quadruped-robot-competition/src/whz'

# Create dirs
dirs = set()
for root, _, files in os.walk(BASE):
    if '__pycache__' in root:
        continue
    rel = os.path.relpath(root, BASE)
    if rel == '.':
        continue
    dirs.add(REMOTE + '/' + rel.replace('\\', '/'))
for d in sorted(dirs):
    c.exec_command(f'mkdir -p {d}')

# Copy files
count = 0
for root, _, files in os.walk(BASE):
    if '__pycache__' in root:
        continue
    for f in files:
        local = os.path.join(root, f)
        rel = os.path.relpath(local, BASE).replace('\\', '/')
        remote = f'{REMOTE}/{rel}'
        ext = os.path.splitext(f)[1].lower()
        try:
            if ext in ('.png', '.mp3'):
                with open(local, 'rb') as fh:
                    data = base64.b64encode(fh.read()).decode()
            else:
                with open(local, 'r', encoding='utf-8', errors='replace') as fh:
                    data = base64.b64encode(fh.read().encode('utf-8')).decode()
            c.exec_command(f'echo {data} | base64 -d > {remote}')
            count += 1
            if count % 5 == 0:
                print(f'  {count} files...')
        except Exception as e:
            print(f'  FAIL {rel}: {e}')

c.exec_command(f'chmod +x {REMOTE}/whz/*.py 2>/dev/null')
print(f'Deployed {count} files')
c.close()
