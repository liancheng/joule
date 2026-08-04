#!/bin/sh

uv run --frozen pytest --full-trace "$@"
