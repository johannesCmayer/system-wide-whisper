# system-wide-whisper
Use whisper anywhere on your system to enter text. Requires the [whisper-asr-webservice](https://github.com/ahmetoner/whisper-asr-webservice), or an OpenAI API key.

I am using [skhd](https://github.com/koekeishiya/skhd) for the keyboard shortcuts. Though you can use anything that can execute a program with a keyboard shortcut.

## Using main_wrapper
It is reccomended to use the `main_wrapper` script to run the program. I am using file IPC, and therefore having a short startup time reduces input lag significantly (I know, using sockets would just be better. Maybe I will switch to that eventually). The script only runs python if necessary.

This requires that you put the python path option in the `config_local.yaml` file (see help). E.g. we would add the line
`python_path: /opt/homebrew/Caskroom/miniconda/base/envs/system-wide-whisper/bin/python`

To use `main_wrapper` we also need to have `yq` (the portable command-line YAML processor) available in the path.

### Non-python requirements for Linux
- xdotool
- xclip

```
usage: main.py [-h] [--start] [--stop] [--toggle-recording] [--toggle-pause]
               [--abort] [--clear-notifications] [--no-postprocessing]
               [--start-lowercase] [--copy-last] [--list-transcriptions]
               [--transcribe-last] [--transcribe-file TRANSCRIBE_FILE]
               [--list-recordings] [--only-record] [--clipboard] [--config]
               [--voice-announcements]

The default config can be picewise overwritten by a config_local.yaml file
placed in /Users/johannes/projects/system-wide-whisper.

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
  --transcribe-file TRANSCRIBE_FILE
                        Transcribe a file. By default look for the transcribed
                        files in the project directory. If the argument
                        contains one or more slashes, it is interpreted as an
                        path argument relative to the current working
                        directory. E.g. `-t 2023_06_11-12_53_28.mp3` will look
                        in the recorded files in the audio directory. `-t
                        ./podcast.mp3` will look for a file 'podcast.mp3' in
                        the current working directory, and transcribe that.
                        `-t /home/user/recordings/2023_06_11-12_53_28.mp3`
                        will look for a file '2023_06_11-12_53_28.mp3' in the
                        directory '/home/user/memo.mp3' or '~/memo.mp3' will
                        look for a file 'memo.mp3' in the home directory, and
                        transcribe that.
  --list-recordings     List the paths of recorded audio.
  --only-record         Only record, don't transcribe.
  --clipboard           Don't paste, only copy to clipboard.
  --config              Edit the config file.
  --voice-announcements
                        Speak outloud a notification for when recording starts
                        and ends, and similar events such as pausing.
```