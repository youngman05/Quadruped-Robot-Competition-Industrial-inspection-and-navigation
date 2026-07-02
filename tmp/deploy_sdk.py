"""Deploy Lite3 SDK to Jetson and build."""
import paramiko, os

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('100.126.48.49', port=22, username='superwfx666', password='superwfx', timeout=10)

base = r'C:\Users\tom\Desktop\quadruped-robot-competition-main\Lite3_ROS-ros2-foxy'
remote_base = '/home/superwfx666/quadruped-robot-competition/Lite3_ROS-ros2-foxy'

sftp = client.open_sftp()
count = 0
for root, dirs, files in os.walk(base):
    # Skip pycache
    dirs[:] = [d for d in dirs if '__pycache__' not in d]
    for fname in files:
        local_path = os.path.join(root, fname)
        rel_path = os.path.relpath(local_path, base).replace('\\', '/')
        remote_path = remote_base + '/' + rel_path
        remote_dir = os.path.dirname(remote_path).replace('\\', '/')
        try:
            client.exec_command(f'mkdir -p {remote_dir}')
            with open(local_path, 'rb') as f:
                sftp.putfo(f, remote_path)
            count += 1
        except Exception as e:
            print(f'  FAIL {rel_path}: {e}')

sftp.close()
print(f'Deployed {count} files')

# Build
stdin, stdout, stderr = client.exec_command(
    'cd ~/quadruped-robot-competition/Lite3_ROS-ros2-foxy && '
    'source /opt/ros/foxy/setup.bash && '
    'colcon build 2>&1 | tail -15',
    timeout=120
)
print('Build:')
print(stdout.read().decode().strip())
client.close()
