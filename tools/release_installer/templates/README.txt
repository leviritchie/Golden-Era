Golden Era Mod installer

This installer targets the Steam release build of Heroes of Might and Magic Olden Era.
It installs the bundled BepInEx IL2CPP loader, the Golden Era plugin payload, and the release-derived Core.zip overlay with a backup.
Install and repair also validate that a local HoMM3 Complete or HoMM3 HD installation exists.

Stronghold is the most complete reference faction. Newer included factions are experimental and may have unfinished mechanics, balance, UI, or asset coverage.

Install:
  Double-click GoldenEraModInstaller.exe

Command-line install:
  powershell -ExecutionPolicy Bypass -File install.ps1
  powershell -ExecutionPolicy Bypass -File install.ps1 -Homm3Root "C:\Path\To\HoMM3"

Repair after a Steam update:
  powershell -ExecutionPolicy Bypass -File install.ps1 -Repair

Uninstall:
  powershell -ExecutionPolicy Bypass -File uninstall.ps1

Credits:
  Special thanks to Aphra for creating the Tears of Ashan mod for VCMI and for granting permission to use that mod's sprite recolors.
