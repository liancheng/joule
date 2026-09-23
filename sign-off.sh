#!/bin/sh

JOULE_ROOT=$(
  cd "$(dirname "$0")" || exit
  pwd
)
sh "$JOULE_ROOT/vendor/tree-sitter-jsonnet/sign-off.sh"
sh "$JOULE_ROOT/test.sh"
