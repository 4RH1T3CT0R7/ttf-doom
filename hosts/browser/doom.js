/**
 * TTDoom browser host -- game state + input + rendering via font hinting.
 *
 * Architecture: JS = CPU (game logic, state, collision), Font = GPU (raycasting).
 * JS passes player position and angle to the font via variation axes.
 * The font's hinting VM raycasts and repositions glyph bars.
 *
 * Axis encoding (fvar range 0..1000, GETVARIATION normalizes to F2Dot14):
 *   MOVX: player_x mapped to 0..1000 (world range 0..1024)
 *   MOVY: player_y mapped to 0..1000
 *   TURN: player_angle mapped to 0..1000 (angle range 0..256)
 *   FIRE: unused for now
 *   ACTN: unused for now
 */
(function () {
    "use strict";

    var el = document.getElementById("game");
    var statusEl = document.getElementById("status");

    // --- Game state (managed entirely in JS) ---
    var px = 480;       // world x (0..1024, cell_size=64, 16x16 grid)
    var py = 480;       // world y (center of map = cell 7,7)
    var angle = 0;      // 0..255 (256 = full circle)
    var health = 100;

    // Movement constants
    var MOVE_SPEED = 3;
    var TURN_SPEED = 1;
    var CELL_SIZE = 64;

    // 16x16 map (must match the map loaded into the font's prep)
    var MAP = [
        1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
        1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,
        1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,
        1,0,0,1,1,0,0,0,0,0,0,1,0,0,0,1,
        1,0,0,1,0,0,0,0,0,0,0,1,0,0,0,1,
        1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,
        1,0,0,0,0,0,1,0,1,0,0,0,0,0,0,1,
        1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,
        1,0,0,0,0,0,1,0,1,0,0,0,0,0,0,1,
        1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,
        1,0,0,1,0,0,0,0,0,0,0,1,0,0,0,1,
        1,0,0,1,1,0,0,0,0,0,0,1,0,0,0,1,
        1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,
        1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,
        1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,
        1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1
    ];

    function isWall(wx, wy) {
        var gx = Math.floor(wx / CELL_SIZE);
        var gy = Math.floor(wy / CELL_SIZE);
        if (gx < 0 || gx >= 16 || gy < 0 || gy >= 16) return true;
        return MAP[gy * 16 + gx] === 1;
    }

    // Key state
    var pressed = {};
    document.addEventListener("keydown", function (e) {
        pressed[e.code] = true;
        if (["ArrowUp","ArrowDown","ArrowLeft","ArrowRight","Space"].indexOf(e.code) !== -1)
            e.preventDefault();
    });
    document.addEventListener("keyup", function (e) { pressed[e.code] = false; });

    // FPS counter
    var frameCount = 0, lastFpsTime = performance.now(), fps = 0;
    var renderFrame = 0;  // separate counter for re-render jitter
    var lastFrameTime = performance.now();

    function gameLoop() {
        // Delta time for frame-rate independent movement
        var now = performance.now();
        var dt = Math.min((now - lastFrameTime) / 1000, 0.05); // cap at 50ms
        lastFrameTime = now;

        var moveAmt = 100 * dt;  // 100 units/sec (~1.5 cells/sec)
        var turnAmt = 40 * dt;   // 40 angle-units/sec (full turn in ~6.4s)

        // --- Turn ---
        if (pressed["ArrowRight"]) angle = (angle + turnAmt) % 256;
        if (pressed["ArrowLeft"])  angle = (angle - turnAmt + 256) % 256;

        // --- Movement ---
        var rad = angle / 256 * Math.PI * 2;
        var cosA = Math.cos(rad);
        var sinA = Math.sin(rad);
        var dx = 0, dy = 0;

        if (pressed["KeyW"] || pressed["ArrowUp"]) {
            dx += cosA * moveAmt;
            dy += sinA * moveAmt;
        }
        if (pressed["KeyS"] || pressed["ArrowDown"]) {
            dx -= cosA * moveAmt;
            dy -= sinA * moveAmt;
        }
        if (pressed["KeyD"]) {
            dx += sinA * moveAmt;
            dy -= cosA * moveAmt;
        }
        if (pressed["KeyA"]) {
            dx -= sinA * moveAmt;
            dy += cosA * moveAmt;
        }

        // --- Collision (axis-independent sliding) ---
        var newX = px + dx;
        var newY = py + dy;
        var margin = 8; // keep player away from walls

        if (!isWall(newX + margin, py) && !isWall(newX - margin, py)) {
            px = newX;
        }
        if (!isWall(px, newY + margin) && !isWall(px, newY - margin)) {
            py = newY;
        }

        // Clamp to world bounds
        px = Math.max(8, Math.min(1016, px));
        py = Math.max(8, Math.min(1016, py));

        // --- Map game state to font axes ---
        // fvar axes have range -1000..0..1000. Must use FULL range
        // so F2Dot14 normalization spans -16384..+16384.
        // DSL decodes: value = (F2Dot14 + 16384) / divisor
        //   position: (raw+16384)/32 → 0..1024 when raw is -16384..+16384
        //   angle:    (raw+16384)/128 → 0..256 when raw is -16384..+16384
        renderFrame++;
        var axisX = (px / 1024 * 2000) - 1000;
        var axisY = (py / 1024 * 2000) - 1000;
        var axisA = (angle / 256 * 2000) - 1000;

        // Clamp to axis range
        axisX = Math.max(-1000, Math.min(1000, axisX));
        axisY = Math.max(-1000, Math.min(1000, axisY));
        axisA = Math.max(-1000, Math.min(1000, axisA));

        // Add sub-pixel jitter to force Chrome re-hinting each frame
        var jitter = (renderFrame % 3) * 0.01;

        el.style.fontVariationSettings =
            "'MOVX' " + (axisX + jitter).toFixed(3) +
            ", 'MOVY' " + axisY.toFixed(3) +
            ", 'TURN' " + axisA.toFixed(3) +
            ", 'FIRE' 0" +
            ", 'ACTN' 0";

        // --- FPS ---
        frameCount++;
        var now = performance.now();
        if (now - lastFpsTime >= 1000) {
            fps = frameCount;
            frameCount = 0;
            lastFpsTime = now;
            if (statusEl) {
                statusEl.textContent = fps + " fps | pos=(" +
                    Math.round(px) + "," + Math.round(py) +
                    ") angle=" + angle;
            }
        }

        requestAnimationFrame(gameLoop);
    }

    // Start after font loads
    if (document.fonts) {
        document.fonts.ready.then(function () {
            if (statusEl) statusEl.textContent = "Ready";
            gameLoop();
        });
    } else {
        setTimeout(function () { gameLoop(); }, 500);
    }
})();
