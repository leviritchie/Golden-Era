> [!WARNING]
> This mod is confirmed not working as of Olden Era Patch 5.

# Golden Era: A mod for Heroes of Might and Magic: Olden Era

The goal of this mod is to integrate HD-2D factions modeled after Heroes of Might and Magic 3 factions. The installer will ask you for a Heroes of Might and Magic 3 install directory, either HoMM3 Complete from GOG (recommended) or HoMM3: HD from Steam.

This is an experimental early-access mod. Stronghold is still the most complete reference faction, and newer faction ports are included at different maturity levels while balance, mechanics, UI, and asset coverage continue to evolve.

## Features

- Adds multiple HoMM3-inspired custom faction ports to Olden Era.
- Adds custom creature lineups, alternate creature upgrades, town screens, buildings, heroes, portraits, map sprites, unit animations, and music where available.
- Adds faction mechanics such as War Cries and other custom-faction rules as they are ported.
- Bundles the BepInEx IL2CPP loader and a release-derived Core.zip overlay with installer-created backups.

## Current Faction Status

The current public package includes the expanded custom-faction framework and assets for several factions. Stronghold remains the most complete reference implementation. Tower and Fortress have substantial release integration. Cove and Dungeon are basic-enabled but still have unfinished mechanics and hardening work. Castle, Rampart, Necropolis, Inferno, and Conflux should be treated as experimental or incomplete until their source-backed asset, mechanics, and validation work is finished.

## Installation

1. Make sure both Olden Era and Heroes of Might and Magic 3 are installed on your computer
2. Download and extract the current zip release from the Releases section.
3. Run `GoldenEraModInstaller.exe`, which will ask you for the location of both Olden Era and HoMM3 installations.
4. Wait for the installer to finish - it can take a few minutes
5. Launch Olden Era from either its folder or directly from Steam. First launch will take several minutes, but future launches will be quicker.
6. (Optional) Copy your entire Olden Era game folder somewhere safe if you're worried about updates breaking the mod.

## Screenshots

![Stronghold adventure map](screenshots/adventure%20map.png)

![Stronghold town screen](screenshots/town.png)

![Stronghold battle](screenshots/battle.gif)

## FAQ

### Will new updates to Olden Era break this mod?
Absolutely yes, especially in early access. Olden Era has a very small download size, so I would recommend keeping this mod installed to a separate copy of your steam game folder to prevent updates from breaking it. There is a chance some updates will be so minor that nothing will break, but even in these situations you will need to reinstall the mod due to how it modifies the game's Core.zip.

### How do I submit bug reports, balance feedback, and suggestions?
Use the Issues tab in github and choose the relevant form: Bug report, Balance issue, or Suggestion. This repo is the only place feedback will be monitored.

### Why not make a discord server or subreddit for feedback?
Because I don't want to moderate one.

### Does this support multiplayer?
Multiplayer is entirely untested at this time.

### How do I donate to contribute to this project?
I likely will never accept donations. I have a great job and the goal of this side project was, in large part, to enrich my knowledge of AI coding tools as someone who is software-adjacent and has project management experience, but who is not a senior developer or computer science expert.

### Is this AI slop?
There are no AI-generated visuals or audio in this game. IDEs with coding LLM support were heavily used when building the mod, and that was, in some sense, the real purpose of me building this mod. See the "About Me" section for more details.

### My antivirus says this is malware
It's not, you can inspect the source to prove it. You may have to click a "Run Anyway" button or something similar.

## About Me
I am a Senior Data Scientist with a long-time passion for video games. I have been working with and training language models since well before ChatGPT became popular, and for the sake of my career and knowledge, I was overdue on learning the ins and outs of various coding tools that have recently become available. This project began as an experiment to see what Cursor was capable of, and the scope of the project expanded as I explored other tools (Claude Code, Codex, Cline with Deepseek v4 Pro). Eventually, I decided to polish this up and open it to feedback, so I could learn a bit more about handling github issues and messy technical projects like this one.

## Credits

Special thanks to Aphra for creating the Tears of Ashan VCMI mod and for granting permission to use that mod's sprite recolors. Thanks to the dedicated HoMM3 modding community for decades of documentation on how to pull apart that game and put it back together.
