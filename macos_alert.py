import subprocess

class Popup(object):
    def __init__(self, title, description):
        self.title = title
        self.message = description

    def display(self):
        self.p = subprocess.Popen(['osascript', '-e', 'display alert "{}" message "{}"'.format(self.title, self.message)])

    def close(self):
        self.p.kill()