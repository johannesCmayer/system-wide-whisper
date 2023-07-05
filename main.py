import os
import tempfile
import subprocess
from pathlib import Path
import argparse
import time
import sys
import re
import atexit
import wave
from datetime import datetime, timedelta
import traceback

import openai
import yaml
from desktop_notifier import DesktopNotifier, Urgency
import pyperclip
from pynput.keyboard import Key, Controller
import asyncio
import soundfile as sf
import pyaudio

from popup import TkinterPopup, MacOSAlertPopup, TerminalNotifierPopup

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
if not config_local_path.exists(): 
    config_local_path.touch()
config.update(yaml.load(config_local_path.open(), yaml.FullLoader))

parser = argparse.ArgumentParser(description=f'The default config can be picewise overwritten by a config_local.yaml file placed in {project_path}.')
parser.add_argument('--start', action='store_true', 
    help='Start the recording.')
parser.add_argument('--stop', action='store_true', 
    help='Stop the recording and transcribe it.')
parser.add_argument('--toggle-recording', action='store_true', 
    help='Start the recording if it is not running, if a recording is running, stop it and transcribe it.')
parser.add_argument('--toggle-pause', action='store_true', 
    help='Pause/Unpause the recording.')
parser.add_argument('--abort', action='store_true', 
    help="Stop the recording and don't transcribe it")
parser.add_argument('--clear-notifications', action='store_true', 
    help='Clear all notifications')
parser.add_argument('--no-postprocessing', action='store_true', 
    help="Do not process special commands. E.g. don't translate 'new line' to an actual newline.")
parser.add_argument('--start-lowercase', action='store_true', 
    help="The first character will be lowercase (useful for inserting text somewhere.)")
parser.add_argument('--copy-last', action='store_true', 
    help="Copy the last transcription to the clipboard.")
parser.add_argument('--list-transcriptions', action='store_true', 
    help="List all past transcriptions.")
parser.add_argument('--transcribe-last', action='store_true', 
    help="Transcribe the last recording.")
parser.add_argument('--transcribe-file', type=str, 
    help="Transcribe a file. By default look for the transcribed files in the project directory. "
    "If the argument contains one or more slashes, it is interpreted as an path argument relative "
    "to the current working directory. E.g. `-t 2023_06_11-12_53_28.mp3` will look in the recorded "
    "files in the audio directory. `-t ./podcast.mp3` will look for a file 'podcast.mp3' in the current "
    "working directory, and transcribe that. `-t /home/user/recordings/2023_06_11-12_53_28.mp3` will look "
    "for a file '2023_06_11-12_53_28.mp3' in the directory '/home/user/memo.mp3' or '~/memo.mp3' will look "
    "for a file 'memo.mp3' in the home directory, and transcribe that.")
parser.add_argument('--list-recordings', action='store_true', 
    help="List the paths of recorded audio.")
parser.add_argument('--only-record', action='store_true', 
    help="Only record, don't transcribe.")
parser.add_argument('--clipboard', action='store_true', 
    help="Don't paste, only copy to clipboard.")
parser.add_argument('--config', action='store_true', 
    help="Edit the config file.")
parser.add_argument('--voice-announcements', action='store_true', 
    help="Speak outloud a notification for when recording starts and ends, and similar events such as pausing.")
args = parser.parse_args()

if config['notifier_system'] == 'desktop-notifier':
    notifier = DesktopNotifier()
shutdown_program = False

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
    subprocess.run(['xclip', '-selection', 'primary'], input=text.encode())
    print('program is: ' + program)
    if program.lower() == 'emacs':
        subprocess.run(['xclip', '-selection', 'clipboard'], input=(text+" ").encode())
        subprocess.check_output(['xdotool', 'key', '--clearmodifiers', 'P'])
    elif program.lower() == 'discord':
        subprocess.run(['xclip', '-selection', 'clipboard'], input=(text+" ").encode())
        subprocess.check_output(['xdotool', 'key', '--clearmodifiers', 'ctrl+V'])
        time.sleep(1)
    else:
        subprocess.run(['xclip', '-selection', 'clipboard'], input=text.encode())
        subprocess.check_output(['xdotool', 'key', '--clearmodifiers', 'ctrl+V'])
        time.sleep(0.25)
    subprocess.run(['xclip', '-selection', 'clipboard'], input=clipboard_contents.encode())

def pyperclip_paste_text(text):
    orig_clipboard = pyperclip.paste()
    pyperclip.copy(text)
    keyboard = Controller()
    with keyboard.pressed(Key.cmd if sys.platform == "darwin" else Key.ctrl):
        keyboard.press('v')
    time.sleep(config['paste_wait'])
    if orig_clipboard:
        pyperclip.copy(orig_clipboard)

def paste_text(text):
    if args.clipboard:
        pyperclip.copy(text)
    elif sys.platform == 'linux':
        X_paste_text(text)
    else:
        pyperclip_paste_text(text)
                
def character_substitution(s):
    commands = [
        (['new', 'line'], '\n'),
        (['new', 'paragraph'], '\n\n'),
        # this is a common mistranslation of new paragraph
        (['you', 'paragraph'], '\n\n'),
        (['new', 'horizontal', 'line'], '\n\n---\n\n'),
        (['new', 'to', 'do'], ' #TODO '),
        (['new', 'to-do'], ' #TODO ')
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

    commands.extend(symbols)

    for i,e in enumerate(['one', 'two', 'three', 'four', 'five', 'six']):
        commands.append((['new', 'heading', e], f'\n\n'+ ("#" * (i)) + ' '))
        commands.append((['new', 'heading', str(i)], f'\n\n'+ ("#" * (i)) + ' '))

    commands_help = "\n".join([' '.join(c) + ": '" + re.sub('\n', '⏎', t) + "'" for c,t in commands])
    if s.lower().strip().replace(' ', '').replace(',', '').replace('.', '') == ''.join(['command', 'print', 'help']):
        f_print('print help')
        return commands_help

    commands_1 = []
    for p,r in commands:
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

    # Insert bullet points, stripping punctuation and capitalizing the first letter
    s = re.sub('[,.!?]? ?new[,.!?]? ?bullet[,.!?]? ?([a-z])?', lambda p: f'\n- {p.group(1).upper() if p.group(1) else ""}', s, flags=re.IGNORECASE)
    # Trim trailing punctuation. This is needed for the last line.
    s = re.sub('^(\s*- .*)[,.!?]+ *$', lambda p: f"{p.group(1)}", s, flags=re.MULTILINE)

    for p,r in commands_3:
        s = re.sub(p, r, s, flags=re.IGNORECASE)
    return s

def openai_transcibe(mp3_path):
        out = openai.Audio.transcribe(config['model'], open(mp3_path, "rb"), language=config['input_language'])
        return out.text

def process_transcription(text):
    text = text.strip()
    text = text.replace('\n', ' ')
    if not args.no_postprocessing:
        text = character_substitution(text)
    if args.start_lowercase:
        if len(text) >= 2:
            text = text[0].lower() + text[1:]
        elif len(text) == 1:
            text = text[0].lower()
    text = re.sub("\\'", "'", text)
    text += ' '
    text = re.sub("[Tt]hank [Yy]ou\. ?$", "", text)
    text = re.sub(". \)", ".\)", text)
    text = re.sub("[,.!?]:", ":", text)
    return text

async def push_notification(title, message, icon):
    if config['notifier_system'] == 'terminal-notifier':
        n = TerminalNotifierPopup(title=title, description=message, icon=icon)
        n.display()
        return n
    elif config['notifier_system'] == 'tkinter':
        return TkinterPopup("Recording for Whisper", "Recording for Whisper", 100, 100, 100, 100, icon)
    elif config['notifier_system'] == 'desktop-notifier':
        return await notifier.send(title="Recording for Whisper", urgency=Urgency.Critical, message="", attachment=record_icon)
    elif config['notifier_system'] == 'macos-alert':
        x = MacOSAlertPopup(title=title, description=message)
        x.display()
        return x
    else:
        raise Exception('Notifier system not supported')

async def clear_notification(notification):
    if config['notifier_system'] == 'desktop-notifier':
        await notifier.clear(notification)
    else:
        notification.clear()

async def record():
    stop_signal_file.unlink(missing_ok=True)
    pause_signal_file.unlink(missing_ok=True)
    abort_signal_file.unlink(missing_ok=True)
    p = pyaudio.PyAudio()

    f_print('Recording')
    n1 = await push_notification("Recording for Whisper", "Recording for Whisper", record_icon)
    chunk = 1024  # Record in chunks of 1024 samples
    sample_format = pyaudio.paInt16  # 16 bits per sample
    channels = 1
    fs = 44100  # Record at 44100 samples per second
    stream = p.open(format=sample_format,
                    channels=channels,
                    rate=fs,
                    frames_per_buffer=chunk, 
                    input=True)

    # Record audio
    frames = []  # Initialize array to store frames
    n_pause = None
    global speak_proc
    while not (abort_signal_file.exists() or stop_signal_file.exists() or shutdown_program):
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

    if n_pause:
        await clear_notification(n_pause)
    if n1:
        await clear_notification(n1)

    stop_signal_file.unlink(missing_ok=True)

    # Stop and close the stream 
    stream.stop_stream()
    stream.close()
    p.terminate()

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

async def transcribe(mp3_path):
    n2 = await push_notification("Processing", "Processing", icon=processing_icon)
    out = openai_transcibe(mp3_path)
    out = process_transcription(out)
    f_print("transcription:", out)

    with transcription_file.open('a') as f:
        f.write('\n')
        f.write('====================================\n')
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

async def asr_pipeline():
    mp3_path = await record()
    text = await transcribe(mp3_path)
    aquire_lock()
    paste_text(text)

def trim_audio_files():
    audio_paths = sorted(audio_path.glob('*.mp3'))
    records_to_keep = config['number_of_recordings_to_keep']
    if len(audio_paths) > records_to_keep:
        for p in audio_paths[:-records_to_keep]:
            p.unlink()

# LOL this doesn't actually work at all because I'm killing this process off that spawns this big command right now. 
# basically seems that there is no error actually happening of picking up the speak commands in the transcriptions so far 
# TODO: I should probably remove this at some point. 
speak_proc = None
def speak(text):
    if args.voice_announcements:
        global speak_proc
        speak_proc = subprocess.Popen(['gsay', text])

async def argument_branching():
    if args.abort:
        speak('abort')
        abort_signal_file.touch()
    elif args.only_record:
        mp3_path = await record()
    elif args.config:
        os.system(f'vi {project_path/"config.yaml"}')
    elif args.copy_last:
        with transcription_file.open() as f:
            lines = f.readlines()
        last = lines[-1]
        pyperclip.copy(last)
        print('copied to clipboard:', last)
    elif args.list_transcriptions:
        with transcription_file.open() as f:
            lines = f.readlines()
        for line in lines:
            print(line, end='')
    elif args.clear_notifications:
        if config['notifier_system'] == 'desktop-notifier':
            await notifier.clear_all()
    elif args.start:
        running_signal_file.touch()
        await asr_pipeline()
    elif args.stop:
        stop_signal_file.touch()
        running_signal_file.unlink()
    elif args.toggle_recording:
        if not running_signal_file.exists():
            speak('Record')
            running_signal_file.touch()
            await asr_pipeline()
        else:
            speak('Stop')
            stop_signal_file.touch()
            running_signal_file.unlink()
    elif args.toggle_pause:
        if pause_signal_file.exists():
            pause_signal_file.unlink()
            speak('Unpause')
        else:
            pause_signal_file.touch()
            speak('Pause')
    elif args.transcribe_last:
        mp3_path = sorted(audio_path.glob('*.mp3'))[-1]
        text = await transcribe(mp3_path)
        paste_text(text)
    elif args.transcribe_file:
        if '/' in args.transcribe_file:
            mp3_path = args.transcribe_file
        else:
            mp3_path = audio_path / args.transcribe_file
        if mp3_path.exists():
            text = await transcribe(mp3_path)
            paste_text(text)
        else:
            f_print(f'File {mp3_path} does not exist.')
    elif args.list_recordings:
        for p in sorted(audio_path.glob('*.mp3')):
            duration = timedelta(seconds=int(sf.info(p).duration))
            print(f"{p}; {duration}")
    trim_audio_files()

async def async_wrapper():
    try:
        await argument_branching()
    except Exception as e:
        if config['notifier_system'] == 'desktop-notifier':
            await notifier.clear_all()
        await push_notification("Error", str(e), icon=error_icon)
        f_print(str(e))
        raise e

def cleanup():
    instance_lock_path.unlink(missing_ok=True)

if __name__ == '__main__':
    atexit.register(cleanup)
    try:
        asyncio.run(async_wrapper())
    except Exception as e:
        traceback.print_exc(file=debug_log_path.open('a'))
        raise e
