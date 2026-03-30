# TTDoom -- DOOM in a TrueType Font

A 3D raycasting engine that runs entirely inside a TrueType font's hinting virtual machine.
The font's glyph hinting program performs DDA raycasting and positions vertical bar contours
to render a first-person 3D view.

## How it works

1. A custom DSL is compiled to TrueType hinting bytecode
2. The bytecode is injected into a .ttf font file
3. The host (browser JS or Python/pygame) passes player position/angle via font variation axes
4. The font's hinting VM raycasts and repositions glyph points
5. The rasteriser renders the glyph -- which IS the 3D view

## Quick start

```bash
pip install fonttools freetype-py pygame pytest
python game/build.py
```

### Browser demo

```bash
python -m http.server 8765
# Open http://localhost:8765/hosts/browser/index.html
```

### Python host (requires freetype-py + pygame)

```bash
python hosts/python/dev_host.py
```

## Controls

| Key           | Action       |
|---------------|-------------|
| W / Up        | Move forward |
| S / Down      | Move back    |
| A             | Strafe left  |
| D             | Strafe right |
| Left / Right  | Turn         |
| Escape        | Quit (Python)|

Minimap overlay in the top-right corner shows position and look direction.

## Architecture

```
compiler/        DSL lexer, parser, code generator -> TrueType assembly
fontgen/         Font builder, glyph generator, sin/cos tables
game/doom.doom   Raycaster source in TTDoom DSL
game/build.py    Compiles doom.doom into doom.ttf
hosts/browser/   Browser demo (JS game loop + font rendering)
hosts/python/    Python/pygame host (FreeType rendering)
tests/           451 tests covering compiler, fontgen, and raycaster
```

## Technical details

- 16 rendering columns (vertical bars in glyph)
- 14 max ray steps per column
- 67-degree field of view
- Sin/cos lookup tables (256 entries, scale=256)
- 16x16 tile map
- Font size: ~6.5 KB
- 13 FDEF functions in hinting bytecode
- JS=CPU architecture: host handles game logic, font handles rendering

## How the font renders 3D

The `A` glyph contains 16 vertical bar contours. On each frame:

1. The host sets variation axes (MOVX, MOVY, TURN) encoding player state
2. The font's `prep` program loads sin/cos tables and the map into storage
3. The glyph hinting program reads axis values via `GETVARIATION`
4. For each of the 16 columns, it casts a ray using DDA traversal
5. Ray hit distance determines bar height (perspective projection)
6. The program moves glyph points via `SHPIX` to position each bar
7. The rasteriser fills the repositioned contours -- producing the 3D view
