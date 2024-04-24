import logging
import subprocess
import sys
import threading
import time
from pynput.keyboard import Key, Controller

import pyperclip

from data_structures import ThreadState
from config import config

terminal_names = ['alacritty', 'gnome-terminal', 'xterm', 'konsole', 'kitty', 'terminator', 'guake', 'tilix', 'terminology', 'cool-retro-term', 'tilda', 'terminix', 'terminator', 'xfce4-terminal', 'mate-terminal', 'lxterminal', 'sakura', 'eterm', 'rxvt', 'urxvt', 'st', 'qterminal', 'lilyterm', 'terminator', 'terminator-gtk3', 'terminator-gtk2', 'terminator-gnome', 'terminator-xfce', 'terminator-k']

def _X_get_clipboard():
    result = subprocess.run(["xclip", "-selection", "clipboard", "-out"], 
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    # The following handles the case when the clipboard is empty
    if result.returncode == 1 and result.stderr == "Error: target STRING not available":
        return ""
    else:
        return result.stdout

def _X_get_window_name():
    return subprocess.check_output([r"""xprop -id $(xdotool getwindowfocus) | sed -n 's/WM_CLASS.*= "\([^"]*\).*/\1/p'"""], shell=True).decode().strip()

def _X_paste_text(text):
    logging.debug(f'Using X paste')
    clipboard_contents = _X_get_clipboard()
    #subprocess.run(['xdotool', 'type', text])
    program = _X_get_window_name()
    subprocess.run(['xclip', '-selection', 'primary'], input=text.encode(), check=True)
    logging.debug(f'program is: {program}')
    if program.lower() in ['emacs']:
        # Use Shift+Insert
        logging.debug(f'X paste: Detected Emacs')
        subprocess.run(['xclip', '-selection', 'clipboard'], input=(text).encode(), check=True)
        subprocess.check_output(['xdotool', 'key', '--clearmodifiers', 'Shift+Insert'])
    elif program.lower() in [*terminal_names, 'obsidian', 'code']:
        # Use Shift+Ctrl+v
        logging.debug(f'X paste: obsidian or VScode')
        subprocess.run(['xclip', '-selection', 'clipboard'], input=(text).encode(), check=True)
        subprocess.run(['xdotool', 'key', '--clearmodifiers', 'Shift+Ctrl+V'], check=True)
        time.sleep(1)
    else:
        # Use Ctrl+v
        subprocess.run(['xclip', '-selection', 'clipboard'], input=text.encode(), check=True)
        subprocess.run(['xdotool', 'key', '--clearmodifiers', 'Ctrl+v'], check=True)
        time.sleep(0.25)
    subprocess.run(['xclip', '-selection', 'clipboard'], input=clipboard_contents.encode(), check=True)

def _pyperclip_paste_text(text):
    logging.debug(f'Using Pyperclip')
    orig_clipboard = pyperclip.paste()
    pyperclip.copy(text)
    keyboard = Controller()
    with keyboard.pressed(Key.cmd if sys.platform == "darwin" else Key.ctrl):
        keyboard.press('v')
    time.sleep(config['paste_wait'])
    if orig_clipboard:
        pyperclip.copy(orig_clipboard)

def paste_text(args, text, server_state):
    """
    Paste text at cursor.
    
    Paste text into the currently selected window, at the current cursor position.
    This function selects the appropriate method for the current platform, and Application.
    """
    logging.debug(f'Pasting Text')
    if args.no_insertion:
        return
    for i in server_state.thread_infos:
        logging.debug(f'In paste function server state thread info: {i.thread}')
        logging.debug(f'In paste function current thread: {threading.current_thread()}')
        if i.thread_state == ThreadState.ABORTION_REQUESTED and threading.current_thread() is i.thread:
            logging.debug(f'Processing abortion request, in paste function of thread {i}')
            i.thread_state = ThreadState.ABORTION_PROCESSED
            return
    if args.clipboard:
        pyperclip.copy(text)
    elif sys.platform == 'linux':
        _X_paste_text(text)
    else:
        _pyperclip_paste_text(text)
