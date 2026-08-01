> [!IMPORTANT]
> This release is built for the Olden Era Steam build from June 4th. The installer will walk you through downloading an extra copy of that build from steam to make this as painless as possible.
> The installer does not patch your Steam install in place. It copies your clean Steam game folder to a separate Golden Era folder and installs the mod into that copy only.

# Golden Era: A mod for Heroes of Might and Magic: Olden Era

The goal of this mod is to integrate HD-2D factions modeled after Heroes of Might and Magic 3 factions. The installer uses your Steam Olden Era folder as a clean source, creates a separate modded copy, and asks for a Heroes of Might and Magic 3 install directory, either HoMM3 Complete from GOG (recommended) or HoMM3: HD from Steam.

This is an experimental early-access mod. Stronghold is still the most complete reference faction, and newer faction ports are included at different maturity levels while balance, mechanics, UI, and asset coverage continue to evolve.

## Features

- Adds multiple HoMM3-inspired custom faction ports to Olden Era.
- Adds custom creature lineups, alternate creature upgrades, town screens, buildings, heroes, portraits, map sprites, unit animations, and music where available.
- Adds faction mechanics such as War Cries and other custom-faction rules as they are ported.
- Bundles the BepInEx IL2CPP loader, Golden Era plugin payload, release-derived Core.zip overlay, campaign StreamingAssets, dialog-portrait Unity resources, and Factory city metadata pin in one self-extracting installer EXE.
- Installs into a separate Golden Era game copy so launching Olden Era from Steam still runs the vanilla game.
- Updates existing Golden Era copies in place when the target folder still has its installer-created clean `Core.zip` baseline.

## Current Faction Status

The current public package includes the expanded custom-faction framework and assets for Castle, Rampart, Tower, Inferno, Necropolis, Dungeon, Stronghold, Fortress, Conflux, and Cove. Stronghold remains the most complete reference implementation. I need your balance suggestions, since I spent the last month making this mod instead of playing Olden Era, so I don't know how to balance it.

## Major Known Bugs

- The back arrow doesn't work in town menus. You have to click the relevant button, such as build tree, again.
- Buildings in town are not clickable yet.
- 
## Installation

1. Make sure both Olden Era and Heroes of Might and Magic 3 are installed on your computer.
2. Download the current `GoldenEraModInstaller-*.exe` release asset and the matching `.sha256` file if you want to verify the download.
3. Run the installer. It will ask for your clean Steam Olden Era folder, a separate modded copy folder, and your HoMM3 installation.

## Modding Guide

The `modding_guide/` folder contains [mod_helper.md](modding_guide/mod_helper.md), a practical Olden Era modding reference, and a snapshot of [GameSymbols.cs](modding_guide/GameSymbols.cs), the central symbol registry used by the Golden Era plugin. These files are intended as reference material for modders working against the Steam IL2CPP build, not as a supported public API.

## Screenshots

![Quick play setup](screenshots/quickplay.gif)

![Town buildings](screenshots/buildings.gif)

![Recruitment screen](screenshots/recruitment.gif)

## FAQ

### Will new updates to Olden Era break this mod?
No, the mod installs into a separate game folder that does not get automatic steam updates.

### Can I still play vanilla Olden Era through Steam?
Yes. Steam should keep launching your untouched vanilla install. Use `Launch Golden Era.cmd` from the separate target folder when you want to play the mod.

### How do I submit bug reports, balance feedback, and suggestions?
Use the Issues tab in github and choose the relevant form: Bug report, Balance issue, or Suggestion. This repo is the only place feedback will be monitored.

### Why not make a discord server or subreddit for feedback?
Because I don't want to moderate one.

### Does this support multiplayer?
Multiplayer is entirely untested at this time.

### Does this include the damage histogram mod?
No. The damage histogram is now a separate mod/project and is not included in the Golden Era installer.

### How do I donate to contribute to this project?
I do not need money to make this mod. However, if you would like to contribute to my marriage, you may donate to my kofi to make my wife less upset about my cloud compute spending: https://ko-fi.com/levi9753

### Is this AI slop?
RIFE 60fps animations are technically AI, but much more similar to DLSS/FSR than what you probably think of as Generative AI. Otherwise, there are no AI-generated visuals or audio in the standard release of this game. The upscaled portrait release uses AI to increase the detail and resolution of original HoMM3 portraits, though the original art is still being used as ground truth. IDEs with coding LLM support were heavily used when building the mod, and that was, in some sense, the real purpose of me building this mod. See the "About Me" section for more details.

### My antivirus says this is malware
It's not, you can inspect the source to prove it. The installer is a large self-extracting EXE because it contains the mod payload, so you may have to click a "Run Anyway" button or something similar.

## About Me
I am a Senior Data Scientist with a long-time passion for video games. I have been working with and training language models since well before ChatGPT became popular, and for the sake of my career and knowledge, I was overdue on learning the ins and outs of various coding tools that have recently become available. This project began as an experiment to see what Cursor was capable of, and the scope of the project expanded as I explored other tools (Claude Code, Codex, Cline with Deepseek v4 Pro). Eventually, I decided to polish this up and open it to feedback, so I could learn a bit more about handling github issues and messy technical projects like this one.

## Credits

Special thanks to Aphra for creating the Tears of Ashan VCMI mod and for granting permission to use that mod's sprite recolors. Thanks to the dedicated HoMM3 modding community for decades of documentation on how to pull apart that game and put it back together.
