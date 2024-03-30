let
  pkgs = import <nixpkgs> {};
in pkgs.mkShell {
  packages = [
    (pkgs.python3.withPackages (python-pkgs: [
      python-pkgs.tqdm
      python-pkgs.pyyaml
      python-pkgs.openai
      python-pkgs.ffmpeg-python
      python-pkgs.pyaudio
      python-pkgs.soundfile
      python-pkgs.desktop-notifier
      python-pkgs.pynput
      python-pkgs.pyperclip
      python-pkgs.tkinter
      python-pkgs.pillow
      python-pkgs.rich
    ]))
    pkgs.dzen2
    pkgs.xdotool
  ];
}
