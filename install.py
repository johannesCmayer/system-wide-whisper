import os
import sys
import getpass
import shutil
import subprocess
from pathlib import Path

print("This script is broken right now")
exit(0)

project_dir = Path(__file__).parent 

service_file_name = f'{project_dir.name}.service'
service_file_tmp = project_dir / service_file_name

def is_root():
    return os.geteuid() == 0

def root_install():
    raise Exception("Not Implemented")
    service_file_dir = None #Path('~/.config/systemd/user').expanduser()
    service_file_target = service_file_dir / service_file_name
    if not service_file_tmp.exists():
        raise Exception("No generated service file found. Are you running with sudo? Then don't.")
    print(f"Writing {service_file_target}")
    with service_file_tmp.open('r') as f1:
        with service_file_target.open('w') as f2:
            f2.write(f1.read())
    service_file_tmp.unlink()

def non_root_install():
    service_file_dir = Path('~/.config/systemd/user').expanduser()
    service_file_target = service_file_dir / service_file_name
    if not service_file_tmp.exists():
        raise Exception("No generated service file found.")
    with service_file_tmp.open('r') as f1:
        with service_file_target.open('w') as f2:
            f2.write(f1.read())
    service_file_tmp.unlink()

def restart_as_root():
    subprocess.run(['sudo', sys.executable] + sys.argv, check=True)

def generate_service_file():
    python_main = project_dir / 'src' / 'server' / 'main.py'
    python_exe = shutil.which('python')

    if not python_main.exists():
        raise Exception(f"Python server file not found at {python_main}")
    if not python_exe:
        raise Exception(f"Python exe not found")

    service_file_contents = f"""[Unit]
    Description=A server to run in the background for processing transcription requests.
    After=network.target

    [Service]
    ExecStart={python_exe} {python_main}
    User={getpass.getuser()}
    Group={getpass.getuser()}
    Restart=on-failure

    [Install]
    WantedBy=multi-user.target"""

    print(service_file_contents)
    print()
    print("Please confirm this is correct. Values are selected based on the current environment. You may need to activate the correct virtual python environment in order to get the correct python path selected.")
    print()
    if input("Continue y/N: ") not in ['y', 'Y']:
        exit(0)

    with (project_dir / service_file_tmp).open('w') as f:
        f.write(service_file_contents)

if __name__ == '__main__':
    generate_service_file()
    non_root_install()

