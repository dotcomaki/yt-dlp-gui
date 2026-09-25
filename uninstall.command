#!/usr/bin/env bash
# Double-clickable wrapper for uninstall.sh (macOS Finder).
cd "$(dirname "${BASH_SOURCE[0]}")"
./uninstall.sh
echo
read -n 1 -s -r -p "Press any key to close."
