# AVoc: Local Realtime Voice Changer for Desktop

A speech-to-speech converter that uses AI models locally to convert microphone audio to a different voice in near-realtime.

Suitable for gaming and streaming.

# Quick Start

Drag your voice model files into the window.

![screenshot](doc/screenshot.png)

# Features

- [X] Import of the voice models provided by the user
- [X] Switching between voices
- [X] Pitch adjustments
- [X] Hotkeys and popup notifications for the ease of use in the background
- [X] Pass Through

# Platforms

All desktops.

Linux is the priority.

# Goal

Make voice changing more developer-friendly by creating
  - a voice conversion library
  - a simple voice changer desktop application
  - a command-line voice changer program

Open Source and Free for modification.

# Installation

## For Arch-based Linux Distributions - from AUR

No cloning of this repo needed.

```
yay -S avoc
```

or for Manjaro

```
pamac build avoc
```

Launch from the menu or by running:

```sh
gio launch /usr/share/applications/AVoc.desktop
```

## For other Linuxes

Requires `pyenv`, `update-desktop-database` and some build tools to be installed.

After that, install the voice changer into a local directory:

```sh
git clone https://github.com/develOseven/avoc
cd avoc
pyenv local 3.12.3
python -m venv .venv
source .venv/bin/activate
CMAKE_ARGS="-DCMAKE_POLICY_VERSION_MINIMUM=3.5" pip install . -r requirements-3.12.3.txt
mkdir -p ~/.local/share/applications/
cp -t ~/.local/share/applications/ src/avoc/AVoc.desktop
echo "Path=$PWD" >> ~/.local/share/applications/AVoc.desktop
mkdir -p ~/.local/share/icons/hicolor/scalable/apps/
cp -t ~/.local/share/icons/hicolor/scalable/apps/ src/avoc/AVoc.svg
update-desktop-database
```

Launch from the menu or by running:

```sh
gio launch ~/.local/share/applications/AVoc.desktop
```

To uninstall:

```sh
rm ~/.local/share/applications/AVoc.desktop ~/.local/share/icons/hicolor/scalable/apps/AVoc.svg
```

## (Optional) Virtual Microphone

The voice changer will latch to the actual default microphone, so a virtual microphone isn't needed.

But there are cases when you would want to configure your operating system to provide a virtual microphone:

- When you absolutely don't want to be heard without the voice changer when something crashes and reverts to the direct microphone input.
- When you want to use the AVoc's QtMultimedia backend instead of its PipeWire backend (by uninstalling the pipewire-filtertools package from the Python environment).
- When you're not on the Linux operating system.

# Development

## Python Environment

Assign a compatible Python version to this directory using pyenv:

```sh
pyenv local 3.12.3
```

Create an environment using venv:

```sh
python -m venv .venv
```

or through VSCode with `~/.pyenv/shims/python` as the Python interpreter.

Install the dependencies:

```sh
source .venv/bin/activate
pip install -r requirements-3.12.3.txt
```

Run:

```sh
python -m main
```

(Optional) Get sources of the voice conversion library and install it in developer mode:

```sh
(cd .. && git clone https://github.com/develOseven/voiceconversion)
source .venv/bin/activate
pip uninstall voiceconversion
pip install -e ../voiceconversion --config-settings editable_mode=strict
```

It allows to work on the voice conversion library.

(Optional) Add to the "configurations" in the VSCode's launch.json:

```json
{
    "name": "Python Debugger: Module",
    "type": "debugpy",
    "request": "launch",
    "module": "main",
}
```
