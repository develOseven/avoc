# A-Voc Local Realtime Voice Changer for Desktop

A speech-to-speech converter that uses AI models locally to convert microphone audio to a different voice in near-realtime.

Suitable for gaming and streaming.

# Quick Start

# Features

- [X] Import of the voice models provided by the user
- [X] Switching between voices
- [ ] Pitch and volume adjustments
- [ ] Hotkeys and popup notifications for the ease of use in the background

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

## With Python Environment

Install:

```sh
mkdir avoc-installdir
cd avoc-installdir
pyenv local 3.12.3
python -m venv .venv
source .venv/bin/activate
pip install avoc
avoc_files=$(pip show --files avoc)
site_packages=$(echo "$avoc_files" | sed -nre 's/^Location:\s*(.*$)/\1/p')
desktop_file="$site_packages/$(echo "$avoc_files" | sed -nre 's/^\s*(.*A-Voc.desktop$)/\1/p')"
icon_file="$site_packages/$(echo "$avoc_files" | sed -nre 's/^\s*(.*A-Voc.svg$)/\1/p')"
cp -t ~/.local/share/applications/ "$desktop_file"
echo "Path=$PWD" >> ~/.local/share/applications/A-Voc.desktop
cp -t ~/.local/share/icons/hicolor/scalable/apps/ "$icon_file"
```

Launch:

```sh
gio launch ~/.local/share/applications/A-Voc.desktop
```

## (Optional) Virtual Microphone

To make a game take audio from the voice changer, the operating system needs to be configured to create a virtual microphone.

### Linux with PulseAudio

Add this to `~/.config/pulse/default.pa`:

```
load-module module-null-sink sink_name=voice-sink sink_properties=device.description=Voice_Sink
load-module module-remap-source master=voice-sink.monitor source_name=voice-mic source_properties=device.description=Voice_Microphone
```

And re-login or restart PulseAudio with `pulseaudio -k`

The Voice_Sink and Voice_Microphone devices will appear. Use the Voice_Sink as voice changer output, and use the Voice_Microphone as input for the game.

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
pip install .
```

(Optional) If it doesn't install, try installing reproducible requirements:

```sh
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
