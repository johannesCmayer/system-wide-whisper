from datetime import datetime
import os
from pathlib import Path
import time

import yaml

project_path = Path(__file__).parent.parent.parent.absolute()

program_start_time = time.time()

instance_id = datetime.now().strftime("%Y%m%d%H%M%S")

logs_dir = project_path / 'logs'
debug_log_path = logs_dir / 'debug.log'
transcription_file = logs_dir / "whisper_transcriptions.txt"
audio_path = project_path / "audio"

# IPC
ipc_dir = project_path / 'IPC'
stop_signal_file = ipc_dir / 'stop'
pause_signal_file = ipc_dir / 'pause'
running_signal_file = ipc_dir / 'running'
abort_signal_file = ipc_dir / 'abort'

# Icons
icon_dir = project_path / 'icons'
record_icon = icon_dir / 'record_icon.png'
pause_icon = icon_dir / 'pause_icon.png'
processing_icon = icon_dir / 'processing_icon.png'
error_icon = icon_dir / 'error_icon.png'

lock_path = project_path / 'locks'
instance_lock_path = lock_path / instance_id

logs_dir.mkdir(exist_ok=True)
lock_path.mkdir(exist_ok=True)
audio_path.mkdir(exist_ok=True)
ipc_dir.mkdir(exist_ok=True)

config = yaml.load((project_path / 'config.yaml').open(), yaml.FullLoader)

# Load the local config to overwrite defaults if it exists
config_local_path = project_path / 'config_local.yaml'
if config_local_path.exists(): 
    config.update(yaml.load(config_local_path.open(), yaml.FullLoader))
