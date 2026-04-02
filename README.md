# py2gba

`py2gba` is a tiny stub CLI that converts a Python file into placeholder Game Boy Advance Thumb assembly.

It currently emits a valid symbol function with `bx lr` and includes the Python source as assembly comments. This keeps the command-line interface stable while the real transpiler is built.

## Install

From the repository root:

```bash
pip install -e .
```

## Usage

Generate an update stub:

```bash
py2gba input.py -o out.s --symbol player --kind update
```

Generate an init stub:

```bash
py2gba input.py -o out.s --symbol player --kind init
```

Arguments:

- `input`: path to an input `.py` file
- `-o, --output`: path for output assembly (`.s`)
- `--symbol`: base name for exported symbol (suffix `_init` or `_update` is added)
- `--kind`: one of `init` or `update` (default: `update`)

## Example output symbol names

- `--symbol player --kind init` -> `player_init`
- `--symbol player --kind update` -> `player_update`

## Status

This project is intentionally a placeholder. Replace `emit_stub` in `py2gba/__main__.py` with a real Python-to-Thumb translation pipeline when ready.