from enum import Enum
from typing import List


class ThreadState(Enum):
    RUNNING = 0
    ABORTION_REQUESTED = 1
    ABORTION_PROCESSED = 2

class ThreadInfo:
    def __init__(self, thread, thread_state):
        self.thread = thread
        self.thread_state = thread_state

    def __str__(self):
        return f'{self.thread} ({self.thread_state})'

class ServerState:
    def __init__(self, recording_started: bool, thread_infos: List[ThreadInfo]):
        self.recording_started = recording_started
        self.thread_infos = thread_infos

    def __str__(self):
        return f'{self.recording_started} {self.thread_infos}'
