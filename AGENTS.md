# Contributor guide

Joule is a Jsonnet language server written in Python using `pygls`. It leverages `tree-sitter-jsonnet` for parsing Jsonnet documents.

## Testing

Joule uses the Python built-in `unittest` package for testing. Tests live in the `tests/` folder. The script `tests/run.sh` discovers and runs all the test cases.
