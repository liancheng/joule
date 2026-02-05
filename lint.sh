#!/bin/sh

uv tool run ruff check --fix src/ tests/
uv tool run ruff format
