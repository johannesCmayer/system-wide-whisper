{
  description = "A Nix-flake-based Python development environment";

  # We need 23.11 to get a 0.28 open-ai python API package.
  inputs.nixpkgs.url = "nixpkgs/nixos-23.11";

  outputs = { self, nixpkgs }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forEachSupportedSystem = f: nixpkgs.lib.genAttrs supportedSystems (system: f {
        pkgs = import nixpkgs { inherit system; };
      });
    in
    {
      devShells = forEachSupportedSystem ({ pkgs }: {
        default = pkgs.mkShell {
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
              python-pkgs.xdg-base-dirs
            ]))
            pkgs.dzen2
            pkgs.xdotool
          ];
        };
      });
    };
}
