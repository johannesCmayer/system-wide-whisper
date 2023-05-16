import os
import tempfile
import subprocess
from pathlib import Path
import argparse
import time
import sys
import re
import atexit

import openai
import yaml
from desktop_notifier import DesktopNotifier, Urgency
import pyperclip
from pynput.keyboard import Key, Controller
import asyncio
import soundfile as sf
import pyaudio
import wave
import multiprocessing
from datetime import datetime

instance_id = datetime.now().strftime("%Y%m%d%H%M%S")
project_path = Path(os.path.dirname(__file__)).absolute()

logs_dir = project_path / 'logs'
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
audio_path.mkdir(exist_ok=True)
ipc_dir.mkdir(exist_ok=True)

config = yaml.load((project_path / 'config.yaml').open(), yaml.FullLoader)

parser = argparse.ArgumentParser()
parser.add_argument('--start', action='store_true', help='Start the recording.')
parser.add_argument('--stop', action='store_true', help='Stop the recording and transcribe it.')
parser.add_argument('--toggle-recording', action='store_true', help='Start the recording if it is not running, if a recording is running, stop it and transcribe it.')
parser.add_argument('--toggle-pause', action='store_true', help='Pause/Unpause the recording.')
parser.add_argument('--abort', action='store_true', help="Stop the recording and don't transcribe it")
parser.add_argument('--clear-notifications', action='store_true', help='Clear all notifications')
parser.add_argument('--no-postprocessing', action='store_true', help="Do not process special commands. E.g. don't translate 'new line' to an actual newline.")
parser.add_argument('--start-lowercase', action='store_true', help="The first character will be lowercase (useful for inserting text somewhere.)")
parser.add_argument('--copy-last', action='store_true', help="Copy the last transcription to the clipboard.")
parser.add_argument('--list-transcriptions', action='store_true', help="List all past transcriptions.")
parser.add_argument('--transcribe-last', action='store_true', help="Transcribe the last recording.")
parser.add_argument('--only-record', action='store_true', help="Only record, don't transcribe.")
parser.add_argument('--clipboard', action='store_true', help="Don't paste, only copy to clipboard.")
parser.add_argument('--config', action='store_true', help="Edit the config file.")
args = parser.parse_args()

notifier = DesktopNotifier()
shutdown_program = False

def f_print(s, end='\n'):
    print(s, end=end)
    with open(logs_dir / 'debug.log', 'a') as f:
        f.write(s + end)

def setup_api_key():
    if 'OPENAI_API_KEY' in os.environ:
        openai_api_key = os.environ["OPENAI_API_KEY"]
    else:
        api_key_placeholder = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
        api_key_path = (project_path / 'api_keys.yaml')
        if not api_key_path.exists():
            with api_key_path.open('w') as f:
                yaml.dump({'openai': api_key_placeholder, 'assembly_ai': api_key_placeholder}, f)
        openai_api_key = yaml.safe_load(open(project_path / 'api_keys.yaml'))['openai']
        if openai_api_key == api_key_placeholder:
            f_print("Please put your OpenAI API key in the 'api_keys.yaml' file, located at {api_key_path}")
            exit(1)
    openai.api_key = openai_api_key

setup_api_key()

def paste_text(text):
    if args.clipboard:
        pyperclip.copy(text)
        return
    orig_clipboard = pyperclip.paste()
    pyperclip.copy(text)
    keyboard = Controller()
    with keyboard.pressed(Key.cmd if sys.platform == "darwin" else Key.ctrl):
        keyboard.press('v')
    time.sleep(0.1)
    if orig_clipboard:
        pyperclip.copy(orig_clipboard)
                
def post_process(s):
    command_prefixes = ['x', 'command']
    commands = [
        (['new', 'line'], '\n'),
        (['new', 'paragraph'], '\n\n'),
        (['open', 'parentheses'], ' ('),
        (['close', 'parentheses'], ') '),
        (['open', 'parenthesis'], ' ('),
        (['close', 'parenthesis'], ') '),
        (['open', 'bracket'], ' ['),
        (['close', 'bracket'], '] '),
        (['open', 'curly', 'brace'], ' {'),
        (['close', 'curly', 'brace'], '} '),
        (['full', 'stop'], '. '),
        (['period'], '. '),
        (['exclamation', 'mark'], '! '),
        (['comma'], ', '),
        (['semicolon'], '; '),
        (['Question', 'mark'], '? '),
        (['hyphen'], '-'),
        (['dash'], '-'),
        (['under', 'score'], '_'),
        (['new', 'bullet'], '\n- '),
        (['new', 'bullet', 'point'], '\n- '),
        (['new', 'numbered', 'bullet'], '\n1. '),
        (['new', 'numbered', 'bullet', 'point'], '\n1. '),
        (['back', 'slash'], '\\\\'),
        (['dollar', 'sign'], '$'),
        (['percent', 'sign'], '%'),
        (['ampersand'], '&'),
        (['asterisk'], '*'),
        (['at', 'sign'], '@'),
        (['caret'], '^'),
        (['tilde'], '~'),
        (['pipe'], '|'),
        (['forward', 'slash'], '/'),
        (['colon'], ': '),
        (['double', 'quote'], '"'),
        (['single', 'quote'], "'"),
        (['less', 'than', 'sign'], '<'),
        (['greater', 'than', 'sign'], '>'),
        (['plus', 'sign'], '+'),
        (['equals', 'sign'], '='),
        (['hash', 'sign'], '#'),
        (['new', 'horizontal', 'line'], '\n\n---\n\n'),
        (['new', 'to', 'do'], ' #TODO '),
        (['new', 'to-do'], ' #TODO '),
    ]

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
        for prefix in command_prefixes:
            commands_3.append((f'{prefix}. {p}', r))
            commands_3.append((f'{prefix}, {p}', r))
            commands_3.append((f'{prefix} {p}', r))
            commands_3.append((f'{prefix}{p}', r))
            commands_3.append((f'{p}', r))
    commands_4 = []
    for p,r in commands_3:
        commands_4.append((f' {p}', r))
        commands_4.append((f'{p}', r))

    for p,r in commands_4:
        s = re.sub(p, r, s, flags=re.IGNORECASE)
    return s

def openai_transcibe(mp3_path, queue):
        out = openai.Audio.transcribe(config['model'], open(mp3_path, "rb"), language=config['input_language'])
        queue['r'] = out.text

def transcribe(mp3_path):
    setup_api_key()
    manager = multiprocessing.Manager()
    qeu = manager.dict()
    p1 = None
    if config['use_local_server']:
        p1 = subprocess.Popen(["curl", "-X", 'POST', f"{config['local_server_url']}/asr?task=transcribe&output=txt", '-H', 'accept: application/json', '-H', 'Content-Type: multipart/form-data', '-F', f'audio_file=@{mp3_path};type=audio/mpeg'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        local_start_time = time.time()
    p2 = multiprocessing.Process(target=openai_transcibe, args=(mp3_path, qeu,))
    p2.start()
    openAI_start_time = time.time()
    while True:
        if config['use_local_server'] and p1 and p1.poll() is not None:
            out, err = p1.communicate()
            if re.search("Could not resolve host", err.decode('utf-8')):
                p1 = None
                continue
            f_print('local server done first')
            p2.kill()
            out = out.decode('utf-8')
            local_end_time = time.time() - local_start_time
            with open(logs_dir / 'transciption_time.csv', 'a') as f:
                f.write(f'local;;; {local_end_time};;; {out}\n')
            return out
        if p2 and not p2.is_alive():
            f_print('openAI server done first')
            if p1:
                p1.kill()
            openAI_end_time = time.time() - openAI_start_time
            out = qeu['r']
            with open(logs_dir / 'transciption_time.csv', 'a') as f:
                f.write(f'OpenAI;;; {openAI_end_time};;; {out}\n')
            return out
        if p1 is None and p2 is None:
            raise Exception('All servers failed!')
        time.sleep(0.025)

def process_transcription(text):
    text = text.strip()
    text = text.replace('\n', ' ')
    if not args.no_postprocessing:
        text = post_process(text)
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

async def record():
    stop_signal_file.unlink(missing_ok=True)
    pause_signal_file.unlink(missing_ok=True)
    abort_signal_file.unlink(missing_ok=True)
    p = pyaudio.PyAudio()  # Create an interface to PortAudio

    f_print('Recording')
    n1 = await notifier.send(title="Recording for Whisper", urgency=Urgency.Critical, message="", attachment=record_icon)

    chunk = 1024  # Record in chunks of 1024 samples
    sample_format = pyaudio.paInt16  # 16 bits per sample
    channels = 1
    fs = 44100  # Record at 44100 samples per second
    stream = p.open(format=sample_format,
                    channels=channels,
                    rate=fs,
                    frames_per_buffer=chunk, 
                    input=True)

    frames = []  # Initialize array to store frames

    # Store data in chunks for 3 seconds
    n_pause = None
    while True:
        if abort_signal_file.exists():
            f_print('aborting')
            stream.stop_stream()
            stream.close()
            p.terminate()
            if n_pause:
                await notifier.clear(n_pause)
                n_pause = None
            await notifier.clear(n1)
            abort_signal_file.unlink()
            running_signal_file.unlink()
            exit(0)
        data = stream.read(chunk)
        if not pause_signal_file.exists():
            frames.append(data)
            if n_pause:
                await notifier.clear(n_pause)
                n_pause = None
        else:
            if not n_pause:
                n_pause = await notifier.send(title="Paused Recording", urgency=Urgency.Critical, message="", attachment=pause_icon)
        if shutdown_program or stop_signal_file.exists():
            stop_signal_file.unlink(missing_ok=True)
            break
    if n_pause:
        await notifier.clear(n_pause)

    # Stop and close the stream 
    stream.stop_stream()
    stream.close()
    p.terminate()

    f_print('Finished recording')

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

        f_print('saving mp3')
        data, fs = sf.read(wav_path) 
        sf.write(mp3_path, data, fs)

    await notifier.clear(n1)
    print(mp3_path)
    return mp3_path

async def transcribe_2(mp3_path):
    n2 = await notifier.send(title="Processing", urgency=Urgency.Critical, message="", attachment=processing_icon)
    out = transcribe(mp3_path)
    out = process_transcription(out)
    f_print("transcription:", out)

    with transcription_file.open('a') as f:
        f.write('\n')
        f.write('====================================\n')
        f.write(out)

    await notifier.clear(n2)
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
    text = await transcribe_2(mp3_path)
    aquire_lock()
    paste_text(text)

def trim_audio_files():
    audio_paths = sorted(audio_path.glob('*.mp3'))
    if len(audio_paths) > 10:
        for p in audio_paths[:-10]:
            p.unlink()

async def argument_branching():
    if args.abort:
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
        await notifier.clear_all()
    elif args.start:
        running_signal_file.touch()
        await asr_pipeline()
    elif args.stop:
        stop_signal_file.touch()
        running_signal_file.unlink()
    elif args.toggle_recording:
        if not running_signal_file.exists():
            running_signal_file.touch()
            await asr_pipeline()
        else:
            stop_signal_file.touch()
            running_signal_file.unlink()
    elif args.toggle_pause:
        if pause_signal_file.exists():
            pause_signal_file.unlink()
        else:
            pause_signal_file.touch()
    elif args.transcribe_last:
        mp3_path = sorted(audio_path.glob('*.mp3'))[-1]
        text = await transcribe_2(mp3_path)
        paste_text(text)
    trim_audio_files()

async def async_wrapper():
    try:
        await argument_branching()
    except Exception as e:
        await notifier.clear_all()
        await notifier.send(title="Error", urgency=Urgency.Critical, message=str(e), attachment=error_icon)
        f_print(str(e))
        raise e

def cleanup():
    instance_lock_path.unlink(missing_ok=True)

if __name__ == '__main__':
    atexit.register(cleanup)
    try:
        asyncio.run(async_wrapper())
    except Exception as e:
        raise e