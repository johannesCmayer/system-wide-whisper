# system-wide-whisper
Use whisper anywhere on your system to enter text. Requires the [whisper-asr-webservice](https://github.com/ahmetoner/whisper-asr-webservice), or an OpenAI API key.

I am using [skhd](https://github.com/koekeishiya/skhd) for the keyboard shortcuts. Though you can use anything that can execute a program with a keyboard shortcut.

## Non-python requirements for Linux
- xdotool
- xclip

Pasting only works if you are using X (on Linux).

```
usage: system-wide-whisper [-h] [--start] [--stop] [--toggle-recording]
                           [--toggle-pause] [--abort] [--clear-notifications]
                           [--no-postprocessing] [--start-lowercase]
                           [--copy-last] [--list-transcriptions]
                           [--transcribe-last]

options:
  -h, --help            show this help message and exit
  --start               Start the recording.
  --stop                Stop the recording and transcribe it.
  --toggle-recording    Start the recording if it is not running, if a
                        recording is running, stop it and transcribe it.
  --toggle-pause        Pause/Unpause the recording.
  --abort               Stop the recording and don't transcribe it
  --clear-notifications
                        Clear all notifications
  --no-postprocessing   Do not process special commands. E.g. don't translate
                        'new line' to an actual newline.
  --start-lowercase     The first character will be lowercase (useful for
                        inserting text somewhere.)
  --copy-last           Copy the last transcription to the clipboard.
  --list-transcriptions
                        List all past transcriptions.
  --transcribe-last     Transcribe the last recording.
  ```
