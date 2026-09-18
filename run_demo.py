"""Start the local demo after running setup.ps1."""
import os
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
env_file = ROOT / '.env'
if env_file.exists():
    for line in env_file.read_text(encoding='utf-8-sig').splitlines():
        if line.strip() and not line.lstrip().startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip())
python = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
node = shutil.which('node.exe' if os.name == 'nt' else 'node')
next_bin = ROOT / 'frontend' / 'node_modules' / 'next' / 'dist' / 'bin' / 'next'
if not python.exists() or not node or not next_bin.exists():
    sys.exit('Run setup.ps1 first (Python 3.11+ and Node 20.9+ required).')
processes = []
child_env = os.environ.copy()
child_env.pop('PYTHONPATH', None)
try:
    processes.append(subprocess.Popen([str(python), '-m', 'uvicorn', 'backend.app:app', '--host', '127.0.0.1', '--port', '8000'], cwd=ROOT, env=child_env))
    processes.append(subprocess.Popen([node, str(next_bin), 'dev', '--hostname', '127.0.0.1'], cwd=ROOT / 'frontend', env=child_env))
    print('\nOpen http://localhost:3000 — company key: configured COMPANY_KEY or demo-company\n', flush=True)
    while all(p.poll() is None for p in processes):
        time.sleep(1)
finally:
    for process in processes:
        if process.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
            else:
                process.terminate()

