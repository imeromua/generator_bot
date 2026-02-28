"""
Build version utility for cache busting.
Returns short git commit hash (7 chars) as version string.
Falls back to Unix timestamp if git is unavailable.
"""
import subprocess
import os
import time


def get_build_version():
    """Get build version from git commit hash or timestamp fallback."""
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short=7', 'HEAD'],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL,
            timeout=2
        ).decode('utf-8').strip()
        return f"v{commit}"
    except Exception:
        # Fallback if git unavailable or timeout
        return f"v{int(time.time())}"


BUILD_VERSION = get_build_version()

if __name__ == '__main__':
    print(f"Build version: {BUILD_VERSION}")
