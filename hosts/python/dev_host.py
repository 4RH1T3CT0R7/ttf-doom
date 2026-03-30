"""TTDoom Python development host.

Renders the DOOM raycaster font using FreeType and displays it via
pygame.  Accepts keyboard input (WASD + arrows), encodes player state
into font variation axes, and blits the resulting glyph bitmap to the
screen -- providing a native alternative to the browser demo.

Usage::

    python hosts/python/dev_host.py
"""

from __future__ import annotations

import math
import os
import sys
import freetype
import pygame

# ---------------------------------------------------------------------------
# 16x16 level map -- must match game/build.py LEVEL_1
# ---------------------------------------------------------------------------

MAP: list[int] = [
    1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1,
    1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1,
    1, 0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0, 0, 1,
    1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1,
    1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1,
    1, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 1,
    1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1,
    1, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 1,
    1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1,
    1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1,
    1, 0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0, 0, 1,
    1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1,
    1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1,
    1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1,
    1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
]

MAP_SIZE: int = 16
CELL_SIZE: int = 64
WORLD_SIZE: int = MAP_SIZE * CELL_SIZE  # 1024

# Movement tuning
MOVE_SPEED: float = 100.0   # world units per second
TURN_SPEED: float = 40.0    # angle units per second (full turn ~6.4s)
MARGIN: float = 8.0         # wall collision margin

# Display
SCREEN_W: int = 800
SCREEN_H: int = 600

# Colours
COL_BG = (0, 0, 0)
COL_HUD = (0, 255, 0)
COL_MINIMAP_BG = (30, 30, 30)
COL_MINIMAP_WALL = (80, 80, 80)
COL_MINIMAP_PLAYER = (255, 0, 0)


def is_wall(wx: float, wy: float) -> bool:
    """Return True if world coordinate (*wx*, *wy*) is inside a wall."""
    gx = int(wx // CELL_SIZE)
    gy = int(wy // CELL_SIZE)
    if gx < 0 or gx >= MAP_SIZE or gy < 0 or gy >= MAP_SIZE:
        return True
    return MAP[gy * MAP_SIZE + gx] == 1


def load_font() -> freetype.Face:
    """Load doom.ttf, handling paths with non-ASCII characters."""
    font_path = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "doom.ttf")
    )
    if not os.path.isfile(font_path):
        print(f"ERROR: Font not found at {font_path}", file=sys.stderr)
        print("Run 'python game/build.py' first to generate doom.ttf.", file=sys.stderr)
        sys.exit(1)

    # Read font bytes and load from memory to avoid FreeType path
    # encoding issues with non-ASCII directory names (e.g. Cyrillic).
    with open(font_path, "rb") as fh:
        font_data = fh.read()
    face = freetype.Face.from_bytes(font_data)
    return face


def bitmap_to_surface(bitmap: freetype.Bitmap) -> pygame.Surface | None:
    """Convert a FreeType grayscale bitmap to a green-on-black pygame Surface."""
    bw, bh = bitmap.width, bitmap.rows
    if bw == 0 or bh == 0:
        return None

    pitch = bitmap.pitch
    buf = bytes(bitmap.buffer)

    # Build a 32-bit RGBA pixel buffer for pygame
    pixels = bytearray(bw * bh * 4)
    idx = 0
    for y in range(bh):
        row_start = y * pitch
        for x in range(bw):
            v = buf[row_start + x]
            pixels[idx] = 0        # R
            pixels[idx + 1] = v    # G
            pixels[idx + 2] = 0    # B
            pixels[idx + 3] = 255  # A
            idx += 4

    surf = pygame.image.frombuffer(pixels, (bw, bh), "RGBA")
    return surf


def draw_minimap(
    screen: pygame.Surface,
    px: float,
    py: float,
    angle: float,
    map_pixel_size: int = 130,
    padding: int = 10,
) -> None:
    """Draw a small minimap in the top-right corner of *screen*."""
    sw = screen.get_width()
    ox = sw - map_pixel_size - padding
    oy = padding
    cell_px = map_pixel_size / MAP_SIZE

    # Background
    pygame.draw.rect(screen, COL_MINIMAP_BG, (ox, oy, map_pixel_size, map_pixel_size))

    # Walls
    for my in range(MAP_SIZE):
        for mx in range(MAP_SIZE):
            if MAP[my * MAP_SIZE + mx] == 1:
                rect = (
                    ox + mx * cell_px,
                    oy + my * cell_px,
                    cell_px + 1,
                    cell_px + 1,
                )
                pygame.draw.rect(screen, COL_MINIMAP_WALL, rect)

    # Player position
    pmx = ox + px / WORLD_SIZE * map_pixel_size
    pmy = oy + py / WORLD_SIZE * map_pixel_size
    pygame.draw.circle(screen, COL_MINIMAP_PLAYER, (int(pmx), int(pmy)), 3)

    # Look direction
    rad = angle / 256 * math.pi * 2
    lx = pmx + math.cos(rad) * 15
    ly = pmy + math.sin(rad) * 15
    pygame.draw.line(screen, COL_MINIMAP_PLAYER, (int(pmx), int(pmy)), (int(lx), int(ly)), 1)

    # Border
    pygame.draw.rect(screen, (60, 60, 60), (ox, oy, map_pixel_size, map_pixel_size), 1)


def main() -> None:
    """Run the TTDoom pygame host."""
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption("TTDoom - Python Host")
    clock = pygame.time.Clock()

    face = load_font()
    face.set_pixel_sizes(0, SCREEN_H)

    # Player state
    px: float = 480.0
    py: float = 480.0
    angle: float = 0.0

    hud_font = pygame.font.SysFont("monospace", 16)

    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        dt = min(dt, 0.05)  # cap at 50 ms

        # --- Events ---
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        keys = pygame.key.get_pressed()

        # --- Turn ---
        if keys[pygame.K_RIGHT]:
            angle = (angle + TURN_SPEED * dt) % 256
        if keys[pygame.K_LEFT]:
            angle = (angle - TURN_SPEED * dt) % 256

        # --- Movement ---
        rad = angle / 256 * math.pi * 2
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        dx: float = 0.0
        dy: float = 0.0

        if keys[pygame.K_w] or keys[pygame.K_UP]:
            dx += cos_a * MOVE_SPEED * dt
            dy += sin_a * MOVE_SPEED * dt
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            dx -= cos_a * MOVE_SPEED * dt
            dy -= sin_a * MOVE_SPEED * dt
        if keys[pygame.K_d]:
            dx += sin_a * MOVE_SPEED * dt
            dy -= cos_a * MOVE_SPEED * dt
        if keys[pygame.K_a]:
            dx -= sin_a * MOVE_SPEED * dt
            dy += cos_a * MOVE_SPEED * dt

        # --- Collision (axis-independent sliding) ---
        nx = px + dx
        ny = py + dy
        if not is_wall(nx + MARGIN, py) and not is_wall(nx - MARGIN, py):
            px = nx
        if not is_wall(px, ny + MARGIN) and not is_wall(px, ny - MARGIN):
            py = ny

        px = max(MARGIN, min(WORLD_SIZE - MARGIN, px))
        py = max(MARGIN, min(WORLD_SIZE - MARGIN, py))

        # --- Encode axes (game state -> fvar design coordinates) ---
        # fvar range is -1000..1000.  Map from game range to axis range:
        #   position (0..1024) -> (-1000..1000)
        #   angle    (0..256)  -> (-1000..1000)
        axis_x = (px / WORLD_SIZE * 2000) - 1000
        axis_y = (py / WORLD_SIZE * 2000) - 1000
        axis_a = (angle / 256 * 2000) - 1000

        axis_x = max(-1000.0, min(1000.0, axis_x))
        axis_y = max(-1000.0, min(1000.0, axis_y))
        axis_a = max(-1000.0, min(1000.0, axis_a))

        face.set_var_design_coords([axis_x, axis_y, axis_a, 0.0, 0.0])
        face.load_char("A", freetype.FT_LOAD_RENDER | freetype.FT_LOAD_NO_AUTOHINT)

        bitmap = face.glyph.bitmap

        # --- Render ---
        screen.fill(COL_BG)

        surf = bitmap_to_surface(bitmap)
        if surf is not None:
            scaled = pygame.transform.scale(surf, (SCREEN_W, SCREEN_H))
            screen.blit(scaled, (0, 0))

        # --- Crosshair ---
        cx, cy = SCREEN_W // 2, SCREEN_H // 2
        cross_len = 10
        cross_col = (0, 200, 0)
        pygame.draw.line(screen, cross_col, (cx - cross_len, cy), (cx + cross_len, cy), 1)
        pygame.draw.line(screen, cross_col, (cx, cy - cross_len), (cx, cy + cross_len), 1)

        # --- Minimap ---
        draw_minimap(screen, px, py, angle)

        # --- HUD ---
        fps_text = hud_font.render(
            f"FPS: {clock.get_fps():.0f} | pos=({px:.0f},{py:.0f}) angle={angle:.1f}",
            True,
            COL_HUD,
        )
        screen.blit(fps_text, (10, SCREEN_H - 25))

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
