import logging
import time
import tkinter as tk
import uuid
import subprocess
from PIL import Image, ImageTk

class MacOSAlertPopup:
    def __init__(self, title, description):
        self.title = title
        self.message = description

    def display(self):
        self.p = subprocess.Popen(['osascript', '-e', 'display alert "{}" message "{}"'.format(self.title, self.message)])

    def clear(self):
        self.p.kill()

class Dzen2Popup:
    def __init__(self, title, description):
        self.title = title
        self.message = description
        self.proc = None

    def display(self):
        if 'processing' in self.title.lower():
            color = 'green'
        elif 'error' in self.title.lower():
            color = 'pink'
        elif 'pause' in self.title.lower():
            color = 'yellow'
        elif 'record' in self.title.lower():
            color = 'red'
        else:
            color = 'white'
        logging.debug(f'opening dzen as {color}')
        self.proc = subprocess.Popen(['dzen2', '-p', '-bg', color, '-fg', 'black', '-y', '23'],
                                     stdout=subprocess.PIPE, stdin=subprocess.PIPE)

    def clear(self):
        if self.proc:
            self.proc.kill()


class TerminalNotifierPopup:
    def __init__(self, title, description, icon):
        self.title = title
        self.message = description
        self.icon = icon
        self.terminal_notifier = '/opt/homebrew/bin/terminal-notifier'
        self.id = str(uuid.uuid1())

    def display(self):
        subprocess.Popen([self.terminal_notifier, '-title', self.title, '-message', self.message, '-group', self.id, '-contentImage', self.icon, '-appIcon', self.icon])

    def clear(self):
        subprocess.Popen([self.terminal_notifier, '-remove', self.id])


class TkinterPopup:
    y_offset = 0
    def __init__(self, title, message, x, y, width=200, height=100, image_path=None):
        self.height = height
        self.root = tk.Tk()
        self.root.withdraw()
        self.popup = tk.Toplevel()
        self.popup.title(title)
        #y += PopupWindow.y_offset
        self.popup.geometry(f'+{x}+{y}')
        self.popup.overrideredirect(True)

        if image_path:
            img = Image.open(image_path)
            img.thumbnail((width - 20, height - 20))  # Resize for a proper fit
            self.image = ImageTk.PhotoImage(img)
            image_label = tk.Label(self.popup, image=self.image)
            image_label.pack()

        label = tk.Label(self.popup, text=message, padx=10, pady=10)
        label.pack()
        self.popup.lift()
        self.popup.attributes('-topmost', True)
        self.popup.update()
        TkinterPopup.y_offset += self.height

    def clear(self):
        TkinterPopup.y_offset -= self.height
        self.popup.update()
        self.popup.destroy()
        self.popup.update()
        self.root.destroy()
        self.popup.update()

    @classmethod
    def kill(cls):
        pass

def test_tkinter():    
    test = TkinterPopup('Title', 'Message', 100, 100, 300, 200)
    time.sleep(2)
    test.clear()
    print('killed')
    time.sleep(2)

def test_terminal_notifier():
    test = TerminalNotifierPopup('Title', 'Message', '/Users/johannes/projects/system-wide-whisper/icons/error_icon.png')

if __name__ == '__main__':
    test_terminal_notifier()