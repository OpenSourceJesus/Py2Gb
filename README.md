# py2gba

`py2gba` converts a Python file into placeholder Game Boy assembly entrypoints.

It emits:

- a valid exported symbol function (`<symbol>_init` or `<symbol>_update`)
- the source script as assembly comments for traceability
- pygame usage analysis comments (supported/unsupported)

This keeps the command-line interface stable while the real transpiler is built.

## Install

From the repository root:

```bash
pip install -e .
```

## Usage

Generate a GBA update entrypoint:

```bash
py2gba input.py -o out.s --symbol player --kind update --target gba
```

Generate a GBC init entrypoint:

```bash
py2gba input.py -o out.s --symbol player --kind init --target gbc
```

Arguments:

- `input`: path to an input `.py` file
- `-o, --output`: path for output assembly (`.s`)
- `--symbol`: base name for exported symbol (suffix `_init` or `_update` is added)
- `--kind`: one of `init` or `update` (default: `update`)
- `--target`: one of `gba` or `gbc` (default: `gba`)
- `--strict-pygame`: fail if unsupported pygame calls are detected

## Example output symbol names

- `--symbol player --kind init` -> `player_init`
- `--symbol player --kind update` -> `player_update`

## Status

This is still a placeholder backend, but it is pygame-aware and target-aware.

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

- Unsupported `pygame.*` calls are listed in output comments (and fail with `--strict-pygame`).
- `pygame.key.get_pressed()[pygame.K_*]` indexing is recognized for:
  - `pygame.K_LEFT`
  - `pygame.K_RIGHT`
  - `pygame.K_UP`
  - `pygame.K_DOWN`
  - `pygame.K_A`
  - `pygame.K_B`
  - `pygame.K_START`
  - `pygame.K_SELECT`
- No pygame ABI weak stubs are emitted.
- Replace `emit_asm` in `py2gba/__main__.py` with a real translation pipeline when ready.

## `gbc-py` physics aliases

When exporting `gbc-py` scripts through the Blender pipeline, the runtime injects
these aliases so scripts can access physics state directly:

- `rigidbodies` (alias to `rigidBodiesIds`)
- `colliders` (alias to `collidersIds`)
- `physics` (alias to `sim`)
- `PyRapier2d` (module reference when available)
- `get_rigidbody(name)` and `get_collider(name)` (dict `.get` helpers)

Example:

```python
player_body = get_rigidbody("Player")
ground_col = get_collider("Ground")

if player_body is not None and physics is not None:
    pos = physics.get_rigid_body_position(player_body)
    # custom logic using pos[0], pos[1]
```