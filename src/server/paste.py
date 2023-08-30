import logging
import subprocess
import sys
import threading
import time
from pynput.keyboard import Key, Controller

import pyperclip

from data_structures import ThreadState
from config import config

def _X_get_clipboard():
    result = subprocess.run(["xclip", "-selection", "clipboard", "-out"], 
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    # The following handles the case when the clipboard is empty
    if result.returncode == 1 and result.stderr == "Error: target STRING not available":
        return ""
    else:
        return result.stdout

def _X_paste_text(text):
    clipboard_contents = _X_get_clipboard()
    #subprocess.run(['xdotool', 'type', text])
    program = subprocess.check_output(["ps -e | grep $(xdotool getwindowpid $(xdotool getwindowfocus)) | grep -v grep | awk '{print $4}'"], shell=True).decode().strip()
    subprocess.run(['xclip', '-selection', 'primary'], input=text.encode(), check=True)
    logging.info(f'program is: {program}')
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

def _pyperclip_paste_text(text):
    orig_clipboard = pyperclip.paste()
    pyperclip.copy(text)
    keyboard = Controller()
    with keyboard.pressed(Key.cmd if sys.platform == "darwin" else Key.ctrl):
        keyboard.press('v')
    time.sleep(config['paste_wait'])
    if orig_clipboard:
        pyperclip.copy(orig_clipboard)

def paste_text(args, text, server_state):
    """Paste the text into the current window, at the current cursor position.
    This function selects the appropriate method for the current platform, and
    Application."""
    if args.no_insertion:
        return
    for i in server_state.thread_infos:
        logging.debug(f'In paste function server state thread info: {i.thread}')
        logging.debug(f'In paste function current thread: {threading.current_thread()}')
        if i.thread_state == ThreadState.ABORTION_REQUESTED and threading.current_thread() is i.thread:
            logging.info(f'Processing abortion request, in paste function of thread {i}')
            i.thread_state = ThreadState.ABORTION_PROCESSED
            return
    if args.clipboard:
        pyperclip.copy(text)
    elif sys.platform == 'linux':
        _X_paste_text(text)
    else:
        _pyperclip_paste_text(text)
                