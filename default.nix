{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell 
{
  packages = [
    (pkgs.python3.withPackages (python-pkgs: [
      python-pkgs.pandas
      python-pkgs.requests
      
    ]))
  ];
}
