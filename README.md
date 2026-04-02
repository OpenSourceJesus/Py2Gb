# py2gba

`py2gba` converts a Python file into placeholder Game Boy Advance Thumb assembly.

It emits:

- a valid exported symbol function (`<symbol>_init` or `<symbol>_update`) with `bx lr`
- the source script as assembly comments for traceability
- pygame ABI weak stubs (`py2gba_pygame_*`) for detected supported pygame calls
- `bl` call shims for top-level pygame expression statements (for example `pygame.quit()`)

This keeps the command-line interface stable while the real transpiler is built.

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
- `--strict-pygame`: fail if unsupported pygame calls are detected

## Example output symbol names

- `--symbol player --kind init` -> `player_init`
- `--symbol player --kind update` -> `player_update`

## Status

This is still a placeholder backend, but it is now pygame-aware.

Supported call paths:

- `pygame.init`
- `pygame.quit`
- `pygame.display.set_mode`
- `pygame.display.flip`
- `pygame.display.update`
- `pygame.event.get`
- `pygame.event.poll`
- `pygame.event.pump`
- `pygame.key.get_pressed`
- `pygame.key.get_mods`
- `pygame.time.Clock`
- `pygame.time.Clock.tick`
- `pygame.time.get_ticks`
- `pygame.draw.rect`
- `pygame.draw.circle`
- `pygame.draw.line`
- `pygame.draw.polygon`
- `pygame.transform.rotate`
- `pygame.transform.scale`
- `pygame.image.load`
- `pygame.mixer.Sound`
- `pygame.font.Font`

Notes:

- These calls generate ABI placeholder labels that you can implement in your GBA runtime.
- `pygame.quit()` maps to BIOS `SoftReset` (`swi 0x00`) in the weak stub.
- Unsupported `pygame.*` calls are listed in output comments (and fail with `--strict-pygame`).
- Replace `emit_stub` in `py2gba/__main__.py` with a real Python-to-Thumb translation pipeline when ready.