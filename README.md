# ShootersPool Translator

[![GitHub Release](https://img.shields.io/github/v/release/AdamJ-3141/ShootersPool-Translator?style=flat-square&color=007acc)](https://github.com/AdamJ-3141/ShootersPool-Translator/releases)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-007acc.svg?style=flat-square)](https://choosealicense.com/licenses/gpl-3.0/)
[![Python Application](https://img.shields.io/badge/Python-3.14-007acc?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)

A lightweight, always-on-top transparent overlay for ShootersPool Online that extracts in-game chat and provides real-time AI translation using the Groq API.

## Features
* Extracts chat logs directly from game memory without injecting DLLs.
* Provides on-demand AI translation to 11 different languages using the Groq API.
* Reverse-translates your typed replies into other players' native languages.
* Features a transparent, draggable, always-on-top UI that blends into the game.

## Setup Instructions

1. Download the latest `.exe` from the Releases tab.
2. Get your free API key from [console.groq.com/keys](https://console.groq.com/keys).
3. Open the Translator, select your preferred language, and paste your API key.

![Screenshot of the Setup Window in English](images/WelcomeWindow_en.png)

![Screenshot of the Setup Window in Spanish](images/WelcomeWindow_es.png)

4. Open ShootersPool and ensure the game is set to **Windowed Mode** in the graphics settings.
5. Click **Start** in the Translator - it will automatically resize the game to act as a borderless full-screen window.
6. Click any chat message on the overlay to translate it, or use the bottom bar to type a reply and copy it to your clipboard.

![Screenshot of the Overlay in Game](images/translate_window_en_es.png)


## ⚠️ Important Antivirus Warning
This tool uses `pymem` to read the memory of the ShootersPool process to extract chat logs in real time. Because it accesses another program's memory - a technique commonly used by debuggers and game cheats - **Windows Defender and other antivirus software will likely flag the compiled `.exe` as a malicious file or virus**. 

This is a strict false positive. The source code is entirely open for you to verify, and you are welcome to run the program directly via Python instead of using the compiled executable.
