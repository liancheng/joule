#!/bin/sh

# Runs the end-to-end integration tests in a headless Neovim with busted.
cd "$(dirname "$0")" || exit
nvim -l itests/minit.lua "$@"
