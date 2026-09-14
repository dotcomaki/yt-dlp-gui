#!/bin/bash
# Double-click entry point for install.sh — Finder runs .command files in a
# new Terminal window, so this needs no command-line use at all.
cd "$(dirname "$0")"
./install.sh
echo
read -p "Press Enter to close this window..."
