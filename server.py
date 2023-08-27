import io
import shlex
import socket
import threading
import time
import os
import tempfile
import subprocess
from pathlib import Path
import argparse
import sys
import re
import atexit
from typing import List, Tuple
import wave
from datetime import datetime, timedelta
import traceback

import openai
import yaml
from contextlib import redirect_stderr, redirect_stdout
from desktop_notifier import DesktopNotifier, Urgency
import pyperclip
from pynput.keyboard import Key, Controller
import asyncio
import soundfile as sf
import pyaudio
import ffmpeg

from popup import TkinterPopup, MacOSAlertPopup, TerminalNotifierPopup

program_start_time = time.time()

instance_id = datetime.now().strftime("%Y%m%d%H%M%S")
project_path = Path(os.path.dirname(__file__)).absolute()

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

cli_parser = argparse.ArgumentParser(
    description='This is the CLI for the system-wide-whisper server. The client CLI is separate, '
                'and can be viewed with --help-client with the server prgram, or from the client.')
cli_parser.add_argument('--debug-mode', action='store_true', 
                        help='Run the server in a terminal instead of as a service, '
                        'in a way that also allows to run the service in the background. '
                        'This works by using a different port. Use debug-client to connect '
                        'to this instance.')
cli_parser.add_argument('--help-client', action='store_true', 
                        help='Show the help message for the client.')
cli_args = cli_parser.parse_args()

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

@atexit.register
def pyaudio_cleanup():
    stream.stop_stream()
    stream.close()
    p.terminate()

def f_print(s, end='\n'):
    print(s, end=end)
    with debug_log_path.open('a') as f:
        f.write(s + end)

def setup_api_key():
    if 'OPENAI_API_KEY' in os.environ:
        openai_api_key = os.environ["OPENAI_API_KEY"]
    else:
        api_key_placeholder = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
        api_key_path = (project_path / 'api_keys.yaml')
        if not api_key_path.exists():
            with api_key_path.open('w') as f:
                yaml.dump({'openai': api_key_placeholder}, f)
        openai_api_key = yaml.safe_load(open(project_path / 'api_keys.yaml'))['openai']
        if openai_api_key == api_key_placeholder:
            f_print("Please put your OpenAI API key in the 'api_keys.yaml' file, located at {api_key_path}")
            exit(1)
    openai.api_key = openai_api_key

# Somehow this does not work if not called here (if called in the main function this breaks)
setup_api_key()

def X_get_clipboard():
    result = subprocess.run(["xclip", "-selection", "clipboard", "-out"], 
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    # The following handles the case when the clipboard is empty
    if result.returncode == 1 and result.stderr == "Error: target STRING not available":
        return ""
    else:
        return result.stdout

def X_paste_text(text):
    clipboard_contents = X_get_clipboard()
    #subprocess.run(['xdotool', 'type', text])
    program = subprocess.check_output(["ps -e | grep $(xdotool getwindowpid $(xdotool getwindowfocus)) | grep -v grep | awk '{print $4}'"], shell=True).decode().strip()
    subprocess.run(['xclip', '-selection', 'primary'], input=text.encode(), check=True)
    print('program is: ' + program)
    if program.lower() == 'emacs':
        subprocess.run(['xclip', '-selection', 'clipboard'], input=(text+" ").encode(), check=True)
        subprocess.check_output(['xdotool', 'key', '--clearmodifiers', 'P'])
    elif program.lower() == 'discord':
        subprocess.run(['xclip', '-selection', 'clipboard'], input=(text+" ").encode(), check=True)
        subprocess.run(['xdotool', 'key', '--clearmodifiers', 'ctrl+V'], check=True)
        time.sleep(1)
    else:
        subprocess.run(['xclip', '-selection', 'clipboard'], input=text.encode(), check=True)
        subprocess.run(['xdotool', 'key', '--clearmodifiers', 'ctrl+V'], check=True)
        time.sleep(0.25)
    subprocess.run(['xclip', '-selection', 'clipboard'], input=clipboard_contents.encode(), check=True)

def pyperclip_paste_text(text):
    orig_clipboard = pyperclip.paste()
    pyperclip.copy(text)
    keyboard = Controller()
    with keyboard.pressed(Key.cmd if sys.platform == "darwin" else Key.ctrl):
        keyboard.press('v')
    time.sleep(config['paste_wait'])
    if orig_clipboard:
        pyperclip.copy(orig_clipboard)

def paste_text(args, text):
    """Paste the text into the current window, at the current cursor position.
    This function selects the appropriate method for the current platform, and
    Application."""
    if args.no_insertion:
        return
    if args.clipboard:
        pyperclip.copy(text)
    elif sys.platform == 'linux':
        X_paste_text(text)
    else:
        pyperclip_paste_text(text)
                
def text_substitution(s):
    """Perform text substitutions on the string s, e.g. transcibing things like 'new line' to '\n'."""
    format_commands = [
        (['new', 'line'], '\n'),
        (['new', 'paragraph'], '\n\n'),
        # this is a common mistranslation of new paragraph
        (['you', 'paragraph'], '\n\n'),
        (['new', 'horizontal', 'line'], '\n\n---\n\n'),
        (['new', 'to', 'do'], ' #TODO '),
        (['new', 'to-do'], ' #TODO '),
    ]

    direct_substitutions : List[Tuple[str, str]] = [
        ('name ?ear',   'IA'),
        ('name ?ia',    'IA'),
        ('name ?jack',  'JACK'),
        ('name ?g',     'JI'),
        ('name ?Karel', 'Kaarel'),
    ]

    symbols = [
        (['symbol', 'open', 'parentheses'], ' ('),
        (['symbol', 'close', 'parentheses'], ') '),
        (['symbol', 'open', 'parenthesis'], ' ('),
        (['symbol', 'close', 'parenthesis'], ') '),
        (['symbol', 'open', 'bracket'], ' ['),
        (['symbol', 'close', 'bracket'], '] '),
        (['symbol', 'open', 'curly', 'brace'], ' {'),
        (['symbol', 'close', 'curly', 'brace'], '} '),
        (['symbol', 'full', 'stop'], '. '),
        (['symbol', 'period'], '. '),
        (['symbol', 'exclamation', 'mark'], '! '),
        (['symbol', 'comma'], ', '),
        (['symbol', 'semicolon'], '; '),
        (['symbol', 'Question', 'mark'], '? '),
        (['symbol', 'hyphen'], '-'),
        (['symbol', 'dash'], '-'),
        (['symbol', 'under', 'score'], '_'),
        (['symbol', 'back', 'slash'], '\\\\'),
        (['symbol', 'dollar', 'sign'], '$'),
        (['symbol', 'percent', 'sign'], '%'),
        (['symbol', 'ampersand'], '&'),
        (['symbol', 'asterisk'], '*'),
        (['symbol', 'at', 'sign'], '@'),
        (['symbol', 'caret'], '^'),
        (['symbol', 'tilde'], '~'),
        (['symbol', 'pipe'], '|'),
        (['symbol', 'forward', 'slash'], '/'),
        (['symbol', 'colon'], ': '),
        (['symbol', 'double', 'quote'], '"'),
        (['symbol', 'single', 'quote'], "'"),
        (['symbol', 'less', 'than', 'sign'], '<'),
        (['symbol', 'greater', 'than', 'sign'], '>'),
        (['symbol', 'plus', 'sign'], '+'),
        (['symbol', 'equals', 'sign'], '='),
        (['symbol', 'hash', 'sign'], '#'),
    ]

    format_commands.extend(symbols)

    commands_help = "\n".join([' '.join(c) + ": '" + re.sub('\n', '⏎', t) + "'" for c,t in format_commands])
    if s.lower().strip().replace(' ', '').replace(',', '').replace('.', '') == ''.join(['command', 'print', 'help']):
        f_print('print help')
        return commands_help

    commands_1 = []
    for p,r in format_commands:
        commands_1.append((''.join(p), r))
        commands_1.append((' '.join(p), r))
    commands_2 = []
    for p,r in commands_1:
        commands_2.append((f'{p}. ', r))
        commands_2.append((f'{p}, ', r)) 
        commands_2.append((f'{p}.', r))
        commands_2.append((f'{p},', r))
        commands_2.append((p, r))
    commands_3 = []
    for p,r in commands_2:
        commands_3.append((f' {p}', r))
        commands_3.append((f'{p}', r))

    for p,r in direct_substitutions:
        s = re.sub(p, r, s, flags=re.IGNORECASE)

    # Commands to insert headings
    for i,e in enumerate(['one', 'two', 'three', 'four', 'five', 'six']):
        format_commands.append((['new', 'heading', e], f'\n\n'+ ("#" * (i)) + ' '))
        format_commands.append((['new', 'heading', str(i)], f'\n\n'+ ("#" * (i)) + ' '))

    # Insert bullet points, stripping punctuation and capitalizing the first letter
    s = re.sub('[,.!?]? ?new[,.!?]? ?bullet[,.!?]? ?([a-z])?', lambda p: f'\n- {p.group(1).upper() if p.group(1) else ""}', s, flags=re.IGNORECASE)
    # Trim trailing punctuation. This is needed for the last line.
    s = re.sub('^(\s*- .*)[,.!?]+ *$', lambda p: f"{p.group(1)}", s, flags=re.MULTILINE)

    for p,r in commands_3:
        s = re.sub(p, r, s, flags=re.IGNORECASE)

    return s

def process_transcription(args, text):
    text = text.strip()
    text = text.replace('\n', ' ')
    if not args.no_postprocessing:
        text = text_substitution(text)
    if args.start_lowercase:
        if len(text) >= 2:
            text = text[0].lower() + text[1:]
        elif len(text) == 1:
            text = text[0].lower()
    text = re.sub("\\'", "'", text)
    text = re.sub("thank you\. ?$", "", text, flags=re.IGNORECASE)
    text = re.sub(". \)", ".\)", text)
    text = re.sub("[,.!?]:", ":", text)
    # Add a space after the text such that the cursor is at the correct 
    # position to again insert the next piece of transcribed text. 
    text.rstrip()
    text += ' '
    return text

def openai_transcibe(mp3_path):
    out = openai.Audio.transcribe(config['model'], open(mp3_path, "rb"), language=config['input_language'])
    return out.text # type: ignore

async def push_notification(title, message, icon):
    """Push a persistent notification to the user, which stays until it is programmatically cleared.
    @return: a notification object with which can be cleared with clear_notification"""
    if config['notifier_system'] == 'terminal-notifier':
        n = TerminalNotifierPopup(title=title, description=message, icon=icon)
        n.display()
        return n
    elif config['notifier_system'] == 'tkinter':
        return TkinterPopup("Recording for Whisper", "Recording for Whisper", 100, 100, 100, 100, icon)
    elif config['notifier_system'] == 'desktop-notifier':
        notifier = DesktopNotifier()
        return (notifier, await notifier.send(title=title, urgency=Urgency.Critical, message=message, attachment=icon))
    elif config['notifier_system'] == 'macos-alert':
        x = MacOSAlertPopup(title=title, description=message)
        x.display()
        return x
    else:
        raise Exception('Notifier system not supported')

async def clear_notification(notification):
    """Clear a notification that was pushed with push_notification"""
    if config['notifier_system'] == 'desktop-notifier':
        notifier, notification = notification
        await notifier.clear(notification)
    else:
        notification.clear()

async def record() -> str:
    """Record audio and save it to an mp3 file.
    @return: path to the mp3 file"""
    stop_signal_file.unlink(missing_ok=True)
    pause_signal_file.unlink(missing_ok=True)
    abort_signal_file.unlink(missing_ok=True)

    global stream
    global fs
    # The OS is sometimes closing the stream, maybe when it is active to long, so we need
    # to reopen it if it is not active.
    try:
        active = stream.is_active()
        if not active:
            stream = p.open(format=sample_format,
                            channels=channels,
                            rate=fs,
                            frames_per_buffer=chunk, 
                            input=True,
                            start=False)
    except OSError:
        stream = p.open(format=sample_format,
                        channels=channels,
                        rate=fs,
                        frames_per_buffer=chunk, 
                        input=True,
                        start=False)

    f_print('Recording')
    n1 = await push_notification("Recording for Whisper", "Recording for Whisper", record_icon)

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
                    n1 = await push_notification("Recording for Whisper", "Recording for Whisper", record_icon)
                if n_pause:
                    await clear_notification(n_pause)
                    n_pause = None
            else:
                if not n_pause:
                    await clear_notification(n1)
                    n1 = None
                    n_pause = await push_notification("Paused Recording", "Paused Recording", pause_icon)
    stream.stop_stream()

    if n_pause:
        await clear_notification(n_pause)
    if n1:
        await clear_notification(n1)

    stop_signal_file.unlink(missing_ok=True)

    f_print('Finished recording')

    # Save the recorded data as a WAV file
    mp3_path = f"{audio_path}/{datetime.now().strftime('%Y_%m_%d-%H_%M_%S')}.mp3"
    with tempfile.TemporaryDirectory() as tmp_dir:
        wav_path = f"{tmp_dir}/temp.wav"
        f_print('saving wav')
        wf = wave.open(wav_path, 'wb')
        wf.setnchannels(channels)
        wf.setsampwidth(p.get_sample_size(sample_format))
        wf.setframerate(fs)
        wf.writeframes(b''.join(frames))
        wf.close()

        # Convert WAV to mp3
        f_print('saving mp3')
        data, fs = sf.read(wav_path) 
        sf.write(mp3_path, data, fs)

    print(mp3_path)

    if abort_signal_file.exists():
        abort_signal_file.unlink()
        running_signal_file.unlink()
        exit(0)

    return mp3_path

async def transcribe(args, mp3_path):
    n2 = await push_notification("Processing", "Processing", icon=processing_icon)
    out = openai_transcibe(mp3_path)
    out = process_transcription(args, out)
    f_print("transcription:", out)

    with transcription_file.open('a') as f:
        f.write('\n')
        f.write(f'>>> {mp3_path} >>>\n')
        f.write(out)

    await clear_notification(n2)
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

async def asr_pipeline(args):
    mp3_path = await record()
    text = await transcribe(args, mp3_path)
    aquire_lock()
    paste_text(args, text)
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

def asr_pipeline_wrapper(args):
    return asyncio.run(asr_pipeline(args))

def transcribe_wrapper(args, mp3_path, delete_file=False):
    text = asyncio.run(transcribe(args, mp3_path))
    paste_text(args, text)
    if delete_file:
        mp3_path.unlink()

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
    print(input_file, output_file)
    stream = ffmpeg.input(input_file)
    stream = ffmpeg.output(stream, output_file)
    stream = ffmpeg.overwrite_output(stream)
    ffmpeg.run(stream)
    return Path(output_file)

def generate_mp3s(input_file: Path, output_dir: Path) -> Path:
    input_file, output_dir = str(input_file), str(output_dir) # type: ignore
    print(input_file, output_dir)
    subprocess.run(['ffmpeg', '-i', input_file, '-f', 'segment', '-segment_time', '3', f'{output_dir}/out%03d.mp3'])
    return Path(output_dir)

def argument_branching(network_args, server_state, conn):
    """Handle the network arguments and execute the appropriate functionality. """
    if network_args.abort:
        print('abort')
        speak(network_args, 'abort')
        abort_signal_file.touch()
        server_state['recording_started'] = False
    elif network_args.toggle_recording:
        print('toggle recording')
        if server_state['recording_started']:
            stop_signal_file.touch()
            running_signal_file.unlink(missing_ok=True)
            speak(network_args, 'Stop')
            server_state['recording_started'] = False
        else:
            thread = threading.Thread(
                target=asr_pipeline_wrapper, args=(network_args,))
            server_state['threads'].append(thread)
            thread.start()
            running_signal_file.touch()
            server_state['recording_started'] = True
    elif network_args.toggle_pause:
        if pause_signal_file.exists():
            pause_signal_file.unlink()
            speak(network_args, 'Unpause')
        else:
            pause_signal_file.touch()
            speak(network_args, 'Pause')
    elif network_args.shutdown:
        sys.exit(0)
    elif network_args.list_transcriptions:
        with transcription_file.open() as f:
            lines = f.readlines()
        for line in lines:
            print(line, end='')
        conn.sendall(''.join(lines).encode())
    elif network_args.transcribe_last:
        transcription_target = sorted(audio_path.glob('*.mp3'))[-1]
        thread = threading.Thread(
            target=transcribe_wrapper, args=(network_args, transcription_target))
        server_state['threads'].append(thread)
        thread.start()
    elif network_args.list_recordings:
        msg = ''
        for p in sorted(audio_path.glob('*.mp3')):
            duration = timedelta(seconds=int(sf.info(p).duration))
            msg += f"{p}; {duration}\n"
        print(msg)
        conn.sendall(msg.encode())
    elif network_args.status:
        msg = (f"Sever is running\n"
            f"Uptime: {time.time() - program_start_time}s\n"
            f"Active Threads: {threading.active_count()}\n")
        print(msg)
        conn.sendall(msg.encode())
    elif network_args.transcribe_file:
        transcription_target = resolve_file(network_args, network_args.transcribe_file)
        print(f"transcription_target: {transcription_target=}")
        if transcription_target.suffix == '.mp3':
            thread = threading.Thread(
                target=transcribe_wrapper, args=(network_args, transcription_target.name))
        else:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
            transcription_target = generate_mp3(transcription_target, Path(tmp.name))
            thread = threading.Thread(
                target=transcribe_wrapper, args=(network_args, transcription_target), kwargs={'delete_file': True})
        server_state['threads'].append(thread)
        thread.start()
    elif network_args.test_error:
        raise Exception('Test Error')
    else:
        send_help(conn)

def connection_processor(conn, server_state):
    with conn:
        server_state['threads'] = [t for t in server_state['threads'] if t.is_alive()]
        msg = conn.recv(1024)
        msg = msg.decode('utf-8').strip()
        print(f'Got message: {msg}')

        network_args = shlex.split(msg)

        if '-h' in network_args or '--help' in network_args:
            send_help(conn)
            return

        def propagate_messages(f):
            out = f.getvalue()
            print(out)
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
            print(e)
            conn.sendall(e.encode())

        trim_audio_files()

def connection_acceptor():
    """The main server loop that listens for network_args and then passes the commands to the argument branching function. """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        port = config['debug_port'] if cli_args.debug_mode else config['port']
        s.bind((config['IP'], port))
        s.listen(5)
        server_state = {'recording_started': False, 'threads': []}
        while True:
            print('Waiting for connection')
            conn, addr = s.accept()
            print(f'Got connection from {addr}')
            t = threading.Thread(target=connection_processor, args=[conn, server_state])
            t.start()
    finally:
        s.close()

@atexit.register
def cleanup():
    instance_lock_path.unlink(missing_ok=True)

if __name__ == '__main__':
    try:
        connection_acceptor()
    except Exception as e:
        traceback.print_exc(file=debug_log_path.open('a'))
        raise e