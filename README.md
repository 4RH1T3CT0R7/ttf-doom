# TTF-DOOM

**A 3D raycasting engine running inside a TrueType font's hinting virtual machine.**

Yes, the font file is the game engine. No, we are not sorry.

<p align="center">
  <a href="https://4rh1t3ct0r7.github.io/ttf-doom/">
    <img src="https://img.shields.io/badge/PLAY_IN_BROWSER-00cc44?style=for-the-badge" alt="Play in Browser" />
  </a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/font_size-6.5_KB-2563eb?style=flat-square" />
  <img src="https://img.shields.io/badge/rendering-TrueType_bytecode-f97316?style=flat-square" />
  <img src="https://img.shields.io/badge/tests-451_passing-22c55e?style=flat-square" />
  <img src="https://img.shields.io/badge/license-Apache_2.0-6366f1?style=flat-square" />
</p>

The first project to use the TrueType hinting instruction set for 3D rendering. Previous font-based computation projects (such as [llama.ttf](https://github.com/fuglede/llama.ttf)) rely on HarfBuzz WebAssembly shaping — a completely different mechanism. TTF-DOOM runs directly in the hinting bytecode interpreter (FDEF, CALL, RS, WS, SCFS) that ships with every TrueType renderer on every operating system.

The entire rendering engine fits in 6,580 bytes.

---

## How it works

A custom DSL compiles to TrueType hinting bytecode. The bytecode is injected into a `.ttf` font containing 16 vertical bar contours. JavaScript passes player position and angle through `font-variation-settings`, the font's hinting VM raycasts against a 16x16 map, and SCFS instructions reposition the bars to form a 3D perspective view.

```
game.doom (DSL) → compiler → doom.ttf (TT bytecode)
                                  ↓
browser JS (position/angle) → font-variation-settings → GETVARIATION
                                  ↓
                         hinting VM raycasts → SCFS moves points
                                  ↓
                         glyph renders as 3D view
```

The font is a pure renderer. JavaScript handles game state, movement, and collision. The canvas overlay adds enemies, weapon, and HUD on top of the font-rendered walls.

## What runs inside the font

- DDA ray marching (16 columns, 14 max steps)
- Sin/cos lookup tables (256 entries)
- Wall distance calculation and height mapping
- F26Dot6 coordinate conversion via MPPEM
- 13 FDEF functions, 795 storage slots

## Comparison

| Project | Environment | Rendering |
|---------|------------|-----------|
| doompdf | PDF JavaScript | Compiled C via asm.js |
| DOOMQL | SQL database | SQL views |
| DOOM Excel | Spreadsheet formulas | Cell coloring |
| TS Types DOOM | TypeScript compiler | Type-level WebAssembly |
| **TTF-DOOM** | **Font hinting VM** | **TrueType bytecode** |

TTF-DOOM is the first project to use TrueType font hinting for 3D rendering. Previous font-based computation (llama.ttf) used HarfBuzz WebAssembly shaping, not the hinting instruction set.

## Quick start

```bash
git clone https://github.com/4RH1T3CT0R7/ttf-doom.git
cd ttf-doom
pip install fonttools freetype-py pygame pytest
python game/build.py
python -m http.server 8765
# Open http://localhost:8765/hosts/browser/index.html in Chrome/Edge
```

## Controls

| Key | Action |
|-----|--------|
| W/S or arrows | Move forward/backward |
| A/D | Strafe |
| Left/Right arrows | Turn |
| Space | Shoot |
| R | Restart |

## Project structure

```
compiler/       DSL lexer, parser, code generator → TrueType assembly
fontgen/        Font builder, glyph generator, sin/cos tables
game/           Raycaster source (doom.doom) and build script
hosts/browser/  Browser demo with canvas overlay
hosts/python/   Python/pygame development host
tests/          451 tests
doom.ttf        The playable font (6,580 bytes)
```

## Technical challenges

**TrueType MUL truncation** — `MUL(1, 4) = 0` because TT MUL does `(a*b)/64`. Fixed with `DIV(a, 1)` pre-scaling to get correct integer multiply.

**No loops** — While loops compile to recursive FDEF calls. FreeType limits call depth to ~64, constraining column count and ray steps.

**No early return** — `return` inside a recursive while doesn't exit the function. Replaced with hit-flag pattern.

**Browser caching** — Chrome caches hinted glyphs and skips re-hinting on axis changes. Solved with per-frame axis jitter.

**Coordinate mismatch** — SCFS expects F26Dot6 pixel coordinates, not font units. Auto-conversion via MPPEM at runtime.

## Specs

| | |
|-|-|
| Font size | 6,580 bytes |
| Functions | 13 FDEF |
| Storage | 795 slots |
| Columns | 16 |
| Ray steps | 14 max |
| FOV | 67 degrees |
| Map | 16x16 tiles |

## License

[Apache License 2.0](LICENSE)
