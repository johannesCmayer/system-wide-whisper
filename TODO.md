- Make the abort command actually work robustly
    - Set an abort timestamp that every thread can then check.
- Split long files based on silence

- Save server state in a better object (maybe named tuple?)
- Understand thread printing and error handeling in python
- Get better error logging for threads
    - Idea: save the errors from threads and append them to a log. This log should be cleared on startup. This log can be viewed with status
    - Log if the server crashed, and disply this in status
- Fix the bug where pausing breaks the server without crashing, and no error message
- enable ability to interupt processing
    - potentially do this when transcribing last automatically in order to speed up manually the transcription in the case where it just takes really long for some reason.
- migrate all old functionality to server model
- remove all cruft
- setup "universal remote" shortcuts for server
- Remove file IPC
- Either use only async or make desktop notifier use a thread wrapper
- Fix notifications sometimes not getting dismissed
- Refactor global variables
- Improve the locking and queuing mechanisms for making sure that a transcription is only pasted after the previous transcription has been pasted.

Backlog
- fix the record only option, it is currently kind of broken.

SoT
- register the pyaudio cleanup function using a construction with a decorator