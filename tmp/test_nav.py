import sys
sys.path.insert(0, 'src')
from navigation.navigator import Navigator, WAYPOINTS
print(f'Navigator imported OK ({len(WAYPOINTS)} waypoints)')
print(f'Has shutdown: {hasattr(Navigator, "shutdown")}')
print(f'Waypoints: {list(WAYPOINTS.keys())[:5]}...')
print('ALL CHECKS PASSED')
