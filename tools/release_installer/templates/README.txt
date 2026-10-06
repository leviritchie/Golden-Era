Golden Era Mod legacy unpacked installer files

The supported public package is now GoldenEraModInstaller-<version>-<portraits>.exe
plus the payload part files (golden_era_release_payload-<version>.zip.part01, ...)
attached to the same GitHub Release. These scripts are retained only as
maintainer references for the old unpacked package shape.

This installer targets the Steam release build of Heroes of Might and Magic Olden Era.
The current EXE installer creates a separate modded game copy, then installs the bundled BepInEx IL2CPP loader, the Golden Era plugin payload, and the release-derived Core.zip overlay into that copy.
Install and repair also validate that a local HoMM3 Complete or HoMM3 HD installation exists.

Stronghold is the most complete reference faction. Newer included factions are experimental and may have unfinished mechanics, balance, UI, or asset coverage.

Install:
  Double-click GoldenEraModInstaller-<version>-<portraits>.exe. It uses the payload part
  files if they are in the same folder, otherwise it downloads them from the Release.

Credits:
  Special thanks to Aphra for creating the Tears of Ashan mod for VCMI and for granting permission to use that mod's sprite recolors.
