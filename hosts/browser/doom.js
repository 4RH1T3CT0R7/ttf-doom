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
    var MOVE_SPEED = 6;
    var TURN_SPEED = 5;
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

    function gameLoop() {
        // --- Turn ---
        if (pressed["ArrowRight"]) angle = (angle + TURN_SPEED) % 256;
        if (pressed["ArrowLeft"])  angle = (angle - TURN_SPEED + 256) % 256;

        // --- Movement ---
        var rad = angle / 256 * Math.PI * 2;
        var cosA = Math.cos(rad);
        var sinA = Math.sin(rad);
        var dx = 0, dy = 0;

        if (pressed["KeyW"] || pressed["ArrowUp"]) {
            dx += cosA * MOVE_SPEED;
            dy += sinA * MOVE_SPEED;
        }
        if (pressed["KeyS"] || pressed["ArrowDown"]) {
            dx -= cosA * MOVE_SPEED;
            dy -= sinA * MOVE_SPEED;
        }
        if (pressed["KeyD"]) {
            dx += sinA * MOVE_SPEED;
            dy -= cosA * MOVE_SPEED;
        }
        if (pressed["KeyA"]) {
            dx -= sinA * MOVE_SPEED;
            dy += cosA * MOVE_SPEED;
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

        // --- Map game state to font axes (0..1000) ---
        var axisX = Math.round(px / 1024 * 1000);
        var axisY = Math.round(py / 1024 * 1000);
        var axisA = Math.round(angle / 256 * 1000);

        axisX = Math.max(0, Math.min(1000, axisX));
        axisY = Math.max(0, Math.min(1000, axisY));
        axisA = Math.max(0, Math.min(1000, axisA));

        el.style.fontVariationSettings =
            "'MOVX' " + axisX +
            ", 'MOVY' " + axisY +
            ", 'TURN' " + axisA +
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
