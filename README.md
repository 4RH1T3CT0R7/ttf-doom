# 🎮 TTF-DOOM

### DOOM-style 3D raycaster running entirely inside a TrueType font

> The world's first 3D game engine implemented in TrueType font hinting bytecode.
> Every frame of 3D rendering is computed by your font renderer.

<p align="center">
  <a href="https://4rh1t3ct0r7.github.io/ttf-doom/">
    <img src="https://img.shields.io/badge/▶_PLAY_IN_BROWSER-00cc44?style=for-the-badge&logoColor=white" alt="Play in Browser" />
  </a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/font_size-6.5_KB-blue?style=flat-square" />
  <img src="https://img.shields.io/badge/tests-451_passing-brightgreen?style=flat-square" />
  <img src="https://img.shields.io/badge/rendering-TrueType_bytecode-orange?style=flat-square" />
  <img src="https://img.shields.io/badge/license-Apache_2.0-blue?style=flat-square" />
</p>

---

## 🤯 What is this?

A complete **DDA raycasting engine** that runs inside a `.ttf` font file's hinting virtual machine. When you type the letter **"A"** using this font, instead of seeing a normal glyph, you see a **3D first-person view of a maze** — computed entirely by the TrueType instruction set.

No WebAssembly. No JavaScript rendering. No shaders. The font file itself **is** the GPU.

The entire font is only **6,580 bytes**.

```
You type "A" → the font renders a 3D world
```

---

## 🎯 How it works

```
┌─────────────────────────────────────────────────────────────────┐
│  doom.doom (DSL)                                                │
│       │                                                         │
│       ▼                                                         │
│  Compiler (lexer → parser → codegen)                            │
│       │                                                         │
│       ▼                                                         │
│  TrueType hinting bytecode                                      │
│       │                                                         │
│       ▼                                                         │
│  doom.ttf  (6.5 KB variable font, 16 vertical bar contours)    │
│       │                                                         │
│       ▼                                                         │
│  Browser sets font-variation-settings (MOVX, MOVY, TURN)       │
│       │                                                         │
│       ▼                                                         │
│  Hinting VM executes raycaster, repositions bars via SCFS       │
│       │                                                         │
│       ▼                                                         │
│  The glyph IS the 3D view                                       │
└─────────────────────────────────────────────────────────────────┘
```

1. **DSL Source** — A custom language (`doom.doom`) describes the raycaster
2. **Compiler** — Tokenizes, parses, and translates to TrueType hinting bytecode
3. **Font File** — Bytecode injected into a `.ttf` with 16 vertical bar contours
4. **Browser** — JavaScript passes position/angle via `font-variation-settings`
5. **Hinting VM** — The font renderer executes the raycaster, repositions bars
6. **Display** — The glyph IS the 3D view

### Architecture: Font = GPU, JavaScript = CPU

```
JavaScript (CPU)                    TrueType Font (GPU)
├── Game state management           ├── DDA ray marching
├── Movement + collision            ├── Sin/cos lookup tables (256 entries)
├── Enemy AI + pathfinding          ├── Wall distance calculation
├── Input handling                  ├── Perspective projection
├── Canvas overlay                  ├── Bar height positioning
│   ├── Enemies (sprites)           └── SCFS glyph point manipulation
│   ├── Weapon + muzzle flash            (all in hinting bytecode)
│   ├── HUD (health/ammo/score)
│   └── Minimap
└── Sound (Web Audio API)
```

JavaScript handles game logic. The font handles **all 3D rendering**. Every frame, JS encodes the player's world position and angle into font variation axes. The font's hinting program raycasts 16 columns, computes wall distances, and repositions glyph contour points to form the 3D perspective view. The browser's font rasterizer then fills those contours — producing the final image.

---

## 🏆 Why this is unique

### vs. Other "DOOM runs on X" projects

| Project | Where it runs | Rendering engine |
|---------|--------------|-----------------|
| **doompdf** | PDF JavaScript | asm.js (compiled C) |
| **DOOMQL** | SQL database | SQL views |
| **DOOM Excel** | Excel formulas | Cell coloring |
| **TS Types DOOM** | TypeScript compiler | Type-level computation |
| **llama.ttf** | Font (HarfBuzz) | HarfBuzz WebAssembly shaping |
| **TTF-DOOM** | **Font hinting VM** | **Native TrueType bytecode** |

**What makes TTF-DOOM different:**

- 🔤 **Runs in ANY application that renders TrueType fonts** — browsers, Word, Notepad, Photoshop
- 📦 **6,580 bytes** total font file size (13 functions, 795 storage slots)
- 🧮 **Pure computation in hinting bytecode** — no JavaScript, no WebAssembly, no shaders in the rendering pipeline
- 🎯 **First serious use of TT hinting for general computation** — previous font-based projects (llama.ttf) used HarfBuzz WebAssembly, not actual hinting bytecode
- 🛠️ **Custom compiler toolchain** — a purpose-built DSL with lexer, parser, code generator, and fixed-point math stdlib

### Technical challenges solved

**1. F26Dot6 fixed-point arithmetic**

TrueType `MUL` and `DIV` operate on 26.6 fixed-point numbers, not plain integers. This means `1 * 4 = 0` due to fractional truncation. Solved with `DIV(a, 1)` pre-scaling to convert integers to F26Dot6 before arithmetic.

**2. No loop construct in TrueType**

The instruction set has no `while` or `for`. Loops are compiled to recursive `FDEF` function calls. The call stack is limited to ~64 frames, which constrains maximum ray steps.

**3. No return statement**

TrueType functions cannot early-return. A `return` inside a recursive while-loop does not exit. Solved with a **hit-flag pattern** — a variable that short-circuits computation once a ray hits a wall.

**4. State persistence across frames**

The browser's `prep` program resets all storage slots each frame. Game state cannot live in the font. Solved with a **stateless renderer architecture** — JavaScript owns all state, the font is a pure rendering function.

**5. Chrome glyph caching**

Chrome caches hinted glyph outlines and skips re-hinting for identical axis values. Solved with **sub-pixel axis value jitter** — adding `(frame % 3) * 0.01` to force re-execution.

**6. SCFS coordinate system**

The `SCFS` instruction expects F26Dot6 pixel coordinates, not font units. The font must auto-convert via `MPPEM` at runtime to work correctly at any display size.

---

## 🚀 Quick Start

```bash
# Clone
git clone https://github.com/4RH1T3CT0R7/ttf-doom.git
cd ttf-doom

# Install dependencies
pip install fonttools freetype-py pygame pytest

# Build the font
python game/build.py

# Start local server
python -m http.server 8765

# Open in Chrome/Edge
# http://localhost:8765/hosts/browser/index.html
```

### Python host (alternative)

```bash
python hosts/python/dev_host.py
```

---

## 🎮 Controls

| Key | Action |
|-----|--------|
| `W` / `↑` | Move forward |
| `S` / `↓` | Move backward |
| `A` | Strafe left |
| `D` | Strafe right |
| `←` `→` | Turn left / right |
| `Space` | Shoot |
| `R` | Restart (after death) |

---

## 🔧 The TTDoom DSL

The raycaster is written in a custom domain-specific language designed for this project:

```python
const MAP_W = 16
const CELL_SIZE = 64
const MAX_STEPS = 14

array map_data[256]
array sin_table[256]
array cos_table[256]

func raycast(col: int) -> int:
    var ra: int = player_angle + col * 3 - FOV_HALF
    var dx: int = get_cos(ra)
    var dy: int = get_sin(ra)
    var px: int = player_x
    var py: int = player_y
    var hit: int = 0
    while s < MAX_STEPS:
        if hit == 0:
            px = px + dx / 4
            py = py + dy / 4
            if get_map(px / CELL_SIZE, py / CELL_SIZE) > 0:
                hit = 1
        s = s + 1
    return res
```

This compiles to TrueType hinting assembly:

```
FDEF[]           ; define function
  PUSHB[] 3      ; storage index for player_angle
  RS[]           ; read storage → push player_angle
  ...            ; DDA ray marching in bytecode
  SVTCA[0]       ; set freedom/projection vector to Y axis
  SCFS[]         ; move glyph point to computed position
ENDF[]           ; end function
```

---

## 📁 Project Structure

```
ttf-doom/
├── compiler/              # DSL → TrueType bytecode compiler
│   ├── lexer.py           #   Tokenizer with indent/dedent tracking
│   ├── parser.py          #   Recursive descent parser → AST
│   ├── codegen.py         #   AST → TrueType assembly code generator
│   ├── stdlib.py          #   Fixed-point math intrinsics (fixmul, fixdiv)
│   ├── allocator.py       #   Storage slot / function ID allocator
│   └── pipeline.py        #   End-to-end compilation pipeline
├── fontgen/               # Font construction
│   ├── font_builder.py    #   Variable font assembly (fvar, gvar, prep)
│   ├── glyph_builder.py   #   Multi-bar glyph contour generation
│   └── math_tables.py     #   Sin/cos lookup table generation
├── game/
│   ├── doom.doom          #   Raycaster source in TTDoom DSL
│   └── build.py           #   Build script: doom.doom → doom.ttf
├── hosts/
│   ├── browser/           #   Browser demo (HTML + JS game loop)
│   └── python/            #   Python/pygame host (FreeType rendering)
├── tests/                 #   451 tests covering the full stack
├── docs/                  #   GitHub Pages deployment
├── doom.ttf               #   The playable font (6,580 bytes)
└── README.md
```

---

## 📊 Technical Specs

| Metric | Value |
|--------|-------|
| Font file size | **6,580 bytes** |
| FDEF functions | 13 |
| Storage slots | 795 |
| Render columns | 16 |
| Max ray steps per column | 14 |
| Field of view | 67 degrees |
| Map size | 16 x 16 tiles |
| Cell size | 64 world units |
| Sin/cos table entries | 256 |
| Trig scale factor | 256 |
| Font variation axes | 5 (MOVX, MOVY, TURN, FIRE, ACTN) |
| Axis range | -1000 to +1000 |
| Tests | **451** |

---

## 🎯 How the font renders 3D

The glyph for `A` contains **16 vertical bar contours** (4 points each = 64 points total). On every frame:

1. The host sets variation axes (`MOVX`, `MOVY`, `TURN`) encoding the player's world position and look angle
2. The font's `prep` program loads sin/cos tables and the 16x16 map into storage
3. The glyph hinting program reads axis values via `GETVARIATION`
4. It decodes F2Dot14 axis values back to world coordinates and angle
5. For each of the 16 columns, it casts a ray using **DDA traversal**
6. The ray hit distance determines bar height via **perspective projection** (`height = WALL_SCALE / distance`)
7. The program moves glyph points via `SCFS` to position each bar's top and bottom
8. The browser's rasterizer fills the repositioned contours — **producing the 3D view**

The font is a **pure function**: `(position, angle) → 3D frame`. No side effects, no persistent state.

---

## 🌐 Live Demo

**[Play TTF-DOOM in your browser →](https://4rh1t3ct0r7.github.io/ttf-doom/)**

Requires a Chromium-based browser (Chrome, Edge, Brave) with TrueType hinting enabled.

---

## 🤝 Contributing

Contributions are welcome! Some interesting directions:

- **More rendering columns** — increase from 16 to 32 for higher resolution
- **Texture mapping** — encode wall textures in the font
- **Additional host platforms** — native apps, other font renderers
- **Performance optimization** — reduce instruction count per frame
- **New maps** — design more complex level layouts

---

## 📄 License

Apache License 2.0 — see [LICENSE](LICENSE) for details.

---

<p align="center">
  <i>Yes, the font file is the game engine. No, we are not sorry.</i>
</p>
