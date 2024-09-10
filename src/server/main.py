import argparse
import atexit
import io
import logging
import os
import shlex
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import wave
import shutil
from collections import namedtuple
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path

import xdg_base_dirs
import ffmpeg
import openai
import pyaudio
import soundfile as sf
import yaml
from config import (abort_signal_file, audio_path, config, error_icon,
                    instance_lock_path, lock_path, pause_icon,
                    pause_signal_file, processing_icon, program_start_time,
                    project_path, record_icon, running_signal_file,
                    stop_signal_file, transcription_file)
from data_structures import ServerState, ThreadInfo, ThreadState
from desktop_notifier import DesktopNotifier, Urgency
from paste import paste_text
from popup import (Dzen2Popup, MacOSAlertPopup, TerminalNotifierPopup,
                   TkinterPopup, NoPopup)
from rich import print
from rich.logging import RichHandler
from text_processing import process_transcription

network_command_parser = argparse.ArgumentParser(exit_on_error=False, add_help=False, prog="",
    description=f'The default config can be picewise overwritten by a config_local.yaml '
    f'file placed in the project directory: {project_path}.')
network_command_parser.add_argument('--start', action='store_true', 
    help='Start the recording.')
network_command_parser.add_argument('--stop', action='store_true', 
    help='Stop the recording and transcribe it.')
network_command_parser.add_argument('--toggle-recording', action='store_true', 
    help='Start the recording if it is not running, if a recording is running, stop it and transcribe it.')
network_command_parser.add_argument('--toggle-pause', action='store_true', 
    help='Pause/Unpause the recording.')
network_command_parser.add_argument('--abort', action='store_true', 
    help="Stop the recording and don't transcribe it")
network_command_parser.add_argument('--clear-notifications', action='store_true', 
    help='Clear all notifications')
network_command_parser.add_argument('--no-postprocessing', action='store_true', 
    help="Do not process special commands. E.g. don't translate 'new line' to an actual newline.")
network_command_parser.add_argument('--start-lowercase', action='store_true', 
    help="The first character will be lowercase (useful for inserting text somewhere.)")
network_command_parser.add_argument('--copy-last', action='store_true', 
    help="Copy the last transcription to the clipboard.")
network_command_parser.add_argument('--list-transcriptions', action='store_true', 
    help="List all past transcriptions.")
network_command_parser.add_argument('--transcribe-last', action='store_true', 
    help="Transcribe the last recording.")
network_command_parser.add_argument('--transcribe-file', type=Path, 
    help="Transcribe a file. By default look for the transcribed files in the project directory. "
    "If the argument contains one or more slashes, it is interpreted as an path argument relative "
    "to the current working directory. E.g. `-t 2023_06_11-12_53_28.mp3` will look in the recorded "
    "files in the audio directory. `-t ./podcast.mp3` will look for a file 'podcast.mp3' in the current "
    "working directory, and transcribe that. `-t /home/user/recordings/2023_06_11-12_53_28.mp3` will look "
    "for a file '2023_06_11-12_53_28.mp3' in the directory '/home/user/memo.mp3' or '~/memo.mp3' will look "
    "for a file 'memo.mp3' in the home directory, and transcribe that.")
network_command_parser.add_argument('--list-recordings', action='store_true', 
    help="List the paths of recorded audio.")
network_command_parser.add_argument('--only-record', action='store_true', 
    help="Only record, don't transcribe.")
network_command_parser.add_argument('--clipboard', action='store_true', 
    help="Don't paste, only copy to clipboard.")
network_command_parser.add_argument('--std-out', action='store_true', 
    help="Don't paste, only output to stdout.")
network_command_parser.add_argument('--no-insertion', action='store_true', 
    help="Transcribe but don't paste or copy to clipboard")
network_command_parser.add_argument('--config', action='store_true', 
    help="Edit the config file.")
network_command_parser.add_argument('--voice-announcements', action='store_true', 
    help="Speak outloud a notification for when recording starts and ends, and similar events such as pausing.")
network_command_parser.add_argument('--shutdown', action='store_true', 
    help="Shutdown the server. Note that this might cause the server to restart, if it is setup as a service "
    "and the service is configured to restart automatically.")
network_command_parser.add_argument('--status', action='store_true', 
    help="Show the status of the server.")
network_command_parser.add_argument('--test-error', action='store_true', 
    help="Raise an error in the network argument branching section for testing purposes.")
network_command_parser.add_argument('--working-dir', type=Path, required=True,
    help='The working directory to use for file operations. This would normally be set automatically be the client.')
network_command_parser.add_argument('--notifier-system', type=str, required=False,
    help='The notification system to use. Setting this overwrites the config file value.')

cli_parser = argparse.ArgumentParser(
    description='This is the CLI for the system-wide-whisper server. The client CLI is separate, '
                'and can be viewed with --help-client with the server prgram, or from the client.')
cli_parser.add_argument('--debug-log', action='store_true', help='Set logging to debug.')
cli_parser.add_argument('--use-debug-port', action='store_true', 
                        help='Run the server in a terminal instead of as a service, '
                        'in a way that also allows to run the service in the background. '
                        'This works by using a different port. Use debug-client to connect '
                        'to this instance.')
cli_parser.add_argument('--help-client', action='store_true', 
                        help='Show the help message for the client.')
cli_args = cli_parser.parse_args()

logging.basicConfig(
    level=logging.DEBUG if cli_args.debug_log else logging.INFO, 
    format="%(message)s", datefmt="[%X]", handlers=[RichHandler(rich_tracebacks=True)])

if cli_args.help_client:
    network_command_parser.print_help()
    exit()

# Setup the pyaudio recording stream
p = pyaudio.PyAudio()
chunk = 1024*4  # Record in chunks of 1024 samples
sample_format = pyaudio.paInt16  # 16 bits per sample
channels = 1
fs = 44100  # Record at 44100 samples per second
stream = p.open(format=sample_format,
                channels=channels,
                rate=fs,
                frames_per_buffer=chunk, 
                input=True,
                start=False)


config_home = xdg_base_dirs.xdg_config_home() / 'system-wide-whisper'

@atexit.register
def pyaudio_cleanup():
    stream.stop_stream()
    stream.close()
    p.terminate()

def setup_api_key():
    if 'OPENAI_API_KEY' in os.environ:
        openai_api_key = os.environ["OPENAI_API_KEY"]
    else:
        api_key_path = config_home / 'api_key.txt'
        if api_key_path.exists():
            openai_api_key = api_key_path.read_text().strip()
        else:
            logging.info(f"Please put your OpenAI API key in the 'api_keys.yaml' file, located at {api_key_path}")
            exit(1)
    openai.api_key = openai_api_key

# Somehow this does not work if not called here (if called in the main function this breaks)
setup_api_key()

def openai_transcibe(mp3_path):
    out = openai.Audio.transcribe(config['model'], open(mp3_path, "rb"), language=config['input_language'])
    return out.text # type: ignore

def push_notification(title, message, icon, network_args):
    """Push a persistent notification to the user, which stays until it is programmatically cleared.
    @return: a notification object with which can be cleared with clear_notification"""
    notifier_system = network_args.notifier_system if network_args.notifier_system else config['notifier_system']
    if notifier_system == 'terminal-notifier':
        n = TerminalNotifierPopup(title=title, description=message, icon=icon)
        n.display()
        return n
    elif notifier_system == 'tkinter':
        return TkinterPopup("Recording for Whisper", "Recording for Whisper", 100, 100, 100, 100, icon)
    elif notifier_system == 'dzen2popup':
        n = Dzen2Popup(title=title, description=message)
        n.display()
        return n
    elif notifier_system == 'macos-alert':
        x = MacOSAlertPopup(title=title, description=message)
        x.display()
        return x
    elif notifier_system == 'no-popup':
        return NoPopup()
    else:
        raise Exception('Notifier system not supported')

def clear_notification(notification):
    """Clear a notification that was pushed with push_notification"""
    logging.debug(f"Clearing notification: {notification}")
    notification.clear()

def record(network_args) -> str:
    """Record audio and save it to an mp3 file.
    @return: path to the mp3 file"""
    stop_signal_file.unlink(missing_ok=True)
    pause_signal_file.unlink(missing_ok=True)
    abort_signal_file.unlink(missing_ok=True)

    global stream
    global fs
    global p
    # The OS is sometimes closing the stream, maybe when it is active to long, so we need
    # to reopen it if it is not active.
    try:
        active = stream.is_active()
        if not active:
            stream.stop_stream()
            stream.close()
            stream = p.open(format=sample_format,
                            channels=channels,
                            rate=fs,
                            frames_per_buffer=chunk, 
                            input=True,
                            start=False)
    except OSError:
        stream.stop_stream()
        stream.close()
        p.terminate()
        p = pyaudio.PyAudio()
        stream = p.open(format=sample_format,
                        channels=channels,
                        rate=fs,
                        frames_per_buffer=chunk, 
                        input=True,
                        start=False)

    logging.debug('Recording')
    n1 = push_notification("Recording for Whisper", "Recording for Whisper", record_icon, network_args)

    # Record audio
    frames = []  # Initialize array to store frames
    n_pause = None
    global speak_proc
    stream.start_stream()
    while not (abort_signal_file.exists() or stop_signal_file.exists()):
        data = stream.read(chunk)
        if speak_proc is None or speak_proc.poll() is not None:
            if not pause_signal_file.exists():
                frames.append(data)
                if n1 is None:
                    n1 = push_notification("Recording for Whisper", "Recording for Whisper", record_icon, network_args)
                if n_pause:
                    clear_notification(n_pause)
                    n_pause = None
            else:
                if not n_pause:
                    clear_notification(n1)
                    n1 = None
                    n_pause = push_notification("Paused Recording", "Paused Recording", pause_icon, network_args)
    stream.stop_stream()

    if n_pause:
        clear_notification(n_pause)
    if n1:
        clear_notification(n1)

    stop_signal_file.unlink(missing_ok=True)

    logging.debug('Completed Audio Capture')

    # Save the recorded data as a WAV file
    mp3_path = f"{audio_path}/{datetime.now().strftime('%Y_%m_%d-%H_%M_%S')}.mp3"
    with tempfile.TemporaryDirectory() as tmp_dir:
        wav_path = f"{tmp_dir}/temp.wav"
        logging.debug('saving wav')
        wf = wave.open(wav_path, 'wb')
        wf.setnchannels(channels)
        wf.setsampwidth(p.get_sample_size(sample_format))
        wf.setframerate(fs)
        wf.writeframes(b''.join(frames))
        wf.close()

        # Convert WAV to mp3
        logging.debug('saving mp3')
        data, fs = sf.read(wav_path) 
        sf.write(mp3_path, data, fs)

    logging.info(f"Finished Recording {Path(mp3_path).name}")

    if abort_signal_file.exists():
        abort_signal_file.unlink(missing_ok=True)
        running_signal_file.unlink(missing_ok=True)
        exit(0)

    return mp3_path

def transcribe(network_args, mp3_path):
    n2 = push_notification("Processing", "Processing", processing_icon, network_args)
    out = openai_transcibe(mp3_path)
    out = process_transcription(network_args, out)
    logging.info(f"transcription:")
    print(out)

    with transcription_file.open('a') as f:
        f.write('\n')
        f.write(f'>>> {mp3_path} >>>\n')
        f.write(out)

    clear_notification(n2)
    return out

def aquire_lock():
    locks = list(lock_path.iterdir())
    instance_lock_path.touch()

    while len(locks) > 0:
        current_locks = list(lock_path.iterdir())
        for l in locks:
            if l not in current_locks:
                locks.remove(l)
        time.sleep(0.1)

def asr_pipeline(network_args, server_state):
    mp3_path = record(network_args)
    text = transcribe(network_args, mp3_path)
    if network_args.std_out:
        return(text)
    else:
        aquire_lock()
        paste_text(network_args, text, server_state)
        instance_lock_path.unlink(missing_ok=True)

def trim_audio_files():
    audio_paths = sorted(audio_path.glob('*.mp3'))
    records_to_keep = config['number_of_recordings_to_keep']
    if len(audio_paths) > records_to_keep:
        for p in audio_paths[:-records_to_keep]:
            p.unlink()

speak_proc = None
def speak(args, text):
    if args.voice_announcements:
        global speak_proc
        speak_proc = subprocess.Popen(['gsay', text])

def transcribe_wrapper(network_args, server_state, mp3_path, delete_file=False):
    text = transcribe(network_args, mp3_path)
    if delete_file:
        mp3_path.unlink()
    if network_network_args.std_out:
        return(text)
    else:
        paste_text(network_args, text, server_state)

def send_help(conn: socket.socket):
    help = network_command_parser.format_help()
    conn.sendall(help.encode())

def resolve_file(network_args, file_path):
    file_path = Path(file_path)
    if file_path.is_absolute():
        return file_path
    file_path = (network_args.working_dir / file_path).resolve()
    if file_path.exists():
        return file_path
    else:
        return audio_path / network_args.transcribe_file
    
def generate_mp3(input_file: Path, output_file: Path) -> Path:
    input_file, output_file = str(input_file), str(output_file) # type: ignore
    logging.info(f"{input_file} -> {output_file}")
    stream = ffmpeg.input(input_file)
    stream = ffmpeg.output(stream, output_file)
    stream = ffmpeg.overwrite_output(stream)
    ffmpeg.run(stream)
    return Path(output_file)

def generate_mp3s(input_file: Path, output_dir: Path) -> Path:
    input_file, output_dir = str(input_file), str(output_dir) # type: ignore
    logging.info(input_file, output_dir)
    proc = subprocess.Popen(['ffmpeg', '-i', input_file, '-f', 'segment', '-segment_time', str(60*20), f'{output_dir}/out%03d.mp3'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    while proc.poll() is None:
        if abort_signal_file.exists():
            abort_signal_file.unlink()
            proc.terminate()
            raise Exception('Aborted')
        time.sleep(1)
    return Path(output_dir)

def argument_branching(network_args, server_state: ServerState, conn):
    """Handle the network arguments and execute the appropriate functionality."""
    if network_args.abort:
        logging.debug('Received abort command.')
        speak(network_args, 'abort')
        abort_signal_file.touch()
        server_state.recording_started = False
        for s in server_state.thread_infos:
            s.thread_state = ThreadState.ABORTION_REQUESTED
        logging.debug("Set all thread states to ABORTION_REQUESTED.")
    elif network_args.toggle_recording:
        logging.info('Received toggle recording command.')
        if server_state.recording_started:
            logging.debug("toggle: Stopping recording.")
            stop_signal_file.touch()
            running_signal_file.unlink(missing_ok=True)
            speak(network_args, 'Stop')
            server_state.recording_started = False
        else:
            logging.debug("toggle: Starting recording.")
            running_signal_file.touch()
            server_state.recording_started = True
            text = asr_pipeline(network_args, server_state)
            if text:
                conn.sendall(text.encode())
    elif network_args.toggle_pause:
        logging.info('Received pause recording command.')
        if pause_signal_file.exists():
            pause_signal_file.unlink()
            speak(network_args, 'Unpause')
        else:
            pause_signal_file.touch()
            speak(network_args, 'Pause')
    elif network_args.shutdown:
        logging.info('Received shutdown command.')
        sys.exit(0)
    elif network_args.list_transcriptions:
        logging.info('Received list transcriptions command.')
        with transcription_file.open() as f:
            lines = f.readlines()
        for line in lines:
            logging.info(f"{line}\n" )
        conn.sendall(''.join(lines).encode())
    elif network_args.transcribe_last:
        logging.info('Received transcribe last command.')
        transcription_target = sorted(audio_path.glob('*.mp3'))[-1]
        text = transcribe_wrapper(network_args, server_state, transcription_target)
        if text:
            conn.sendall(text.encode())
    elif network_args.list_recordings:
        logging.info('Received list recordings command.')
        msg = ''
        for p in sorted(audio_path.glob('*.mp3')):
            duration = timedelta(seconds=int(sf.info(p).duration))
            msg += f"{p}; {duration}\n"
        logging.info(msg)
        conn.sendall(msg.encode())
    elif network_args.status:
        logging.info('Received network status command.')
        msg = (f"Sever is running\n"
            f"Uptime: {time.time() - program_start_time}s\n"
            f"Active Threads: {threading.active_count()}\n")
        logging.info(msg)
        conn.sendall(msg.encode())
    elif network_args.transcribe_file:
        logging.info('Received transcribe file command.')
        transcription_target = resolve_file(network_args, network_args.transcribe_file)
        logging.info(f"transcription_target: {transcription_target=}")
        text = ""
        with tempfile.TemporaryDirectory() as dir:
            dir = Path(dir)
            generate_mp3s(transcription_target, dir)
            for f in sorted(dir.iterdir()):
                if abort_signal_file.exists():
                    break
                transcribe(network_args, f)
        if text:
            conn.sendall(text.encode())

    elif network_args.test_error:
        logging.info('Received test error command.')
        raise Exception('Test Error')
    else:
        logging.info('Invalid command. Sending help.')
        send_help(conn)

def connection_processor(conn, server_state):
    with conn:
        msg = conn.recv(1024)
        msg = msg.decode('utf-8').strip()
        logging.debug(f'Got message: {msg}')

        network_args = shlex.split(msg)

        if '-h' in network_args or '--help' in network_args:
            send_help(conn)
            return

        def propagate_messages(f):
            out = f.getvalue()
            logging.info(out)
            conn.sendall(out.encode())

        f = io.StringIO()
        with redirect_stdout(f):
            with redirect_stderr(f):
                try:
                    network_args = network_command_parser.parse_args(network_args)
                except SystemExit as e:
                    propagate_messages(f)
                    return
                except argparse.ArgumentError as e:
                    propagate_messages(f)
                    return
        try:
            argument_branching(network_args, server_state, conn)
        except Exception as e:
            e = '\n'.join(traceback.format_exception(e))
            logging.info(e)
            conn.sendall(e.encode())

        trim_audio_files()

def connection_acceptor():
    """The main server loop for accepting connections and dispatching a thread for each of them"""
    server_state = ServerState(False, [])
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        port = config['debug_port'] if cli_args.use_debug_port else config['port']
        s.bind((config['IP'], port))
        s.listen(5)
        logging.info("Server Ready")
        while True:
            logging.debug('Waiting for connection')
            conn, addr = s.accept()
            server_state.thread_infos = [t for t in server_state.thread_infos if t.thread.is_alive()]
            logging.debug(f'Processing connection from {addr}')
            t = threading.Thread(target=connection_processor, args=[conn, server_state])
            thread_info = ThreadInfo(t, ThreadState.RUNNING)
            server_state.thread_infos.append(thread_info)
            t.start()
    except KeyboardInterrupt as e:
        logging.debug('closing socket')
        s.close()
    finally:
        logging.debug('closing socket')
        s.close()

@atexit.register
def cleanup():
    instance_lock_path.unlink(missing_ok=True)

if __name__ == '__main__':
    # Cleanup any potential remaining locks.
    for file in lock_path.glob('*'):
        file.unlink()

    try:
        connection_acceptor()
    except Exception as e:
        logging.exception(e)
        raise e
