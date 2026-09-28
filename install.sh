#!/bin/sh
# mic-monitor installer for macOS and Linux.
#
# Install or upgrade:
#
#     curl -fsSL https://raw.githubusercontent.com/ringo380/mic-monitor/main/install.sh | sh
#
# Uninstall:
#
#     curl -fsSL https://raw.githubusercontent.com/ringo380/mic-monitor/main/install.sh | sh -s -- --uninstall
#
# What it does:
#
#   1. Finds Python 3.10 or newer. If there is none: macOS installs it with
#      Homebrew, Debian and Ubuntu with apt. Otherwise it tells you where to
#      get it.
#   2. Creates a private virtual environment in ~/.local/share/mic-monitor/venv
#      (recreated on every run, so running the line again upgrades).
#   3. Installs mic-monitor into it from GitHub (no git needed).
#   4. Links the two commands, mic-monitor and mic-monitor-tray, into
#      ~/.local/bin and makes sure that folder is on your PATH.
#   5. Starts the tray icon.
#
# Uninstall stops mic-monitor and removes everything above. Your saved settings
# (~/.config/mic-monitor) and logs (~/.local/state/mic-monitor) are kept.
#
# Options: --uninstall, --no-launch (do not start the tray icon). Set
# MIC_MONITOR_SOURCE to a local checkout or another archive to install from it.

set -eu

SOURCE="${MIC_MONITOR_SOURCE:-https://github.com/ringo380/mic-monitor/archive/refs/heads/main.zip}"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/mic-monitor"
VENV="$DATA/venv"
BIN="$HOME/.local/bin"
APPS="mic-monitor mic-monitor-tray"
OS="$(uname -s)"
SELF_URL="https://raw.githubusercontent.com/ringo380/mic-monitor/main/install.sh"

UNINSTALL=0
LAUNCH=1
for arg in "$@"; do
    case "$arg" in
        --uninstall) UNINSTALL=1 ;;
        --no-launch) LAUNCH=0 ;;
        *) printf 'unknown option: %s\n' "$arg" >&2; exit 2 ;;
    esac
done

say() { printf '%s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

remove_owned() {
    # Only ever delete inside our own data folder.
    case "$1" in
        "$DATA"/?*) rm -rf "$1" ;;
        *) die "refusing to delete outside $DATA: $1" ;;
    esac
}

stop_running() {
    # Stop the background worker through the CLI when we have one (it goes
    # through the PID file), then anything left from this or another install.
    if [ -x "$BIN/mic-monitor" ]; then
        "$BIN/mic-monitor" stop >/dev/null 2>&1 || true
    fi
    pkill -f "$VENV/" >/dev/null 2>&1 || true
    pkill -f 'mic_monitor\.worker' >/dev/null 2>&1 || true
    pkill -f 'mic-monitor-tray' >/dev/null 2>&1 || true
}

python_ok() {
    # 3.10 or newer, with a working venv module (Debian splits it out).
    "$1" -c 'import sys, venv, ensurepip; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
        >/dev/null 2>&1
}

find_python() {
    for p in python3.14 python3.13 python3.12 python3.11 python3.10 python3 python \
             /opt/homebrew/bin/python3 /usr/local/bin/python3 \
             /Library/Frameworks/Python.framework/Versions/3.*/bin/python3; do
        path="$(command -v "$p" 2>/dev/null)" || continue
        # On a Mac without the developer tools, /usr/bin/python3 is a stub
        # that opens an install dialog instead of running.
        if [ "$OS" = Darwin ] && [ "$path" = /usr/bin/python3 ] && ! xcode-select -p >/dev/null 2>&1; then
            continue
        fi
        if python_ok "$path"; then
            printf '%s\n' "$path"
            return 0
        fi
    done
    return 1
}

install_python() {
    case "$OS" in
        Darwin)
            if command -v brew >/dev/null 2>&1; then
                say 'Python 3.10 or newer was not found. Installing it with Homebrew (a few minutes)...'
                brew install python >/dev/null || die 'Homebrew could not install Python. Install it from https://www.python.org/downloads/macos/ and run this installer again.'
            else
                die 'Python 3.10 or newer was not found. Install it from https://www.python.org/downloads/macos/ (or install Homebrew) and run this installer again.'
            fi
            ;;
        Linux)
            if command -v apt-get >/dev/null 2>&1; then
                say 'Python 3.10 or newer was not found. Installing it with apt (sudo may ask for your password)...'
                sudo apt-get install -y python3 python3-venv python3-pip libportaudio2 \
                    || die 'apt could not install Python. Install python3, python3-venv and libportaudio2 with your package manager and run this installer again.'
            else
                die 'Python 3.10 or newer was not found. Install python3 (with the venv module) and the PortAudio library with your package manager and run this installer again.'
            fi
            ;;
        *)
            die "unsupported system: $OS"
            ;;
    esac
}

ensure_portaudio() {
    # sounddevice ships PortAudio on macOS but not on Linux.
    [ "$OS" = Linux ] || return 0
    if ldconfig -p 2>/dev/null | grep -q libportaudio; then return 0; fi
    if command -v apt-get >/dev/null 2>&1; then
        say 'Installing the PortAudio library with apt (sudo may ask for your password)...'
        sudo apt-get install -y libportaudio2 || die 'apt could not install libportaudio2.'
    else
        say 'Note: the PortAudio library (libportaudio2) was not found; install it with your package manager before running mic-monitor.'
    fi
}

ensure_path() {
    case ":$PATH:" in *":$BIN:"*) return 0 ;; esac
    line='export PATH="$HOME/.local/bin:$PATH"'
    case "${SHELL:-}" in
        */zsh) rc="$HOME/.zprofile" ;;
        */bash) if [ -f "$HOME/.bash_profile" ]; then rc="$HOME/.bash_profile"; else rc="$HOME/.profile"; fi ;;
        */fish) rc="" ;;
        *) rc="$HOME/.profile" ;;
    esac
    if [ -n "$rc" ] && ! grep -qs '\.local/bin' "$rc"; then
        printf '\n# mic-monitor: commands installed for this user\n%s\n' "$line" >> "$rc"
        PATH_FILE="$rc"
    fi
    export PATH="$BIN:$PATH"
}

# ---------------------------------------------------------------- uninstall

if [ "$UNINSTALL" = 1 ]; then
    say 'Uninstalling mic-monitor...'
    stop_running
    remove_owned "$VENV"
    for app in $APPS; do
        # Only remove links that point into our venv.
        if [ -L "$BIN/$app" ]; then
            case "$(readlink "$BIN/$app")" in "$VENV"/*) rm -f "$BIN/$app" ;; esac
        fi
    done
    rmdir "$DATA" 2>/dev/null || true
    say ''
    say 'mic-monitor is uninstalled.'
    say ''
    say 'Kept, delete them if you want a clean slate:'
    say "  settings   ${XDG_CONFIG_HOME:-$HOME/.config}/mic-monitor"
    say "  logs       ${XDG_STATE_HOME:-$HOME/.local/state}/mic-monitor"
    exit 0
fi

# ------------------------------------------------------------------ install

say 'Installing mic-monitor...'
say ''

if ! PY="$(find_python)"; then
    install_python
    PY="$(find_python)" || die 'Python was installed but could not be found afterwards. Open a new terminal and run this installer again.'
fi
say "Python:   $PY"
ensure_portaudio

stop_running

say "Creating: $VENV"
mkdir -p "$DATA"
remove_owned "$VENV"
"$PY" -m venv "$VENV" || die "could not create a virtual environment with $PY."
VPY="$VENV/bin/python"

say "Package:  $SOURCE"
"$VPY" -m pip install --quiet --disable-pip-version-check "$SOURCE" \
    || die "pip could not install mic-monitor from $SOURCE."

mkdir -p "$BIN"
for app in $APPS; do
    [ -x "$VENV/bin/$app" ] || die "expected $VENV/bin/$app after install, but it is missing."
    ln -sf "$VENV/bin/$app" "$BIN/$app"
done

PATH_FILE=""
ensure_path

INSTALLED="$("$BIN/mic-monitor" --version)" || die 'the installed mic-monitor command does not run.'

if [ "$LAUNCH" = 1 ]; then
    nohup "$BIN/mic-monitor-tray" </dev/null >/dev/null 2>&1 &
fi

say ''
say "$INSTALLED is installed."
say ''
say 'Tray icon:'
if [ "$LAUNCH" = 1 ]; then
    say '  running now (green = on, grey = off, click to toggle)'
fi
say '  start it any time with: mic-monitor-tray'
say ''
say 'Commands (open a new terminal first):'
say '  mic-monitor            toggle monitoring on or off'
say '  mic-monitor list       show your audio devices'
say '  mic-monitor config --in <mic> --out <headphones>'
say '                         pick devices by part of their name'
if [ -n "$PATH_FILE" ]; then
    say ''
    say "Added ~/.local/bin to your PATH in $PATH_FILE"
fi
if [ "$OS" = Darwin ]; then
    say ''
    say 'macOS asks once for microphone access the first time monitoring starts.'
fi
say ''
say 'Uninstall:'
say "  curl -fsSL $SELF_URL | sh -s -- --uninstall"
