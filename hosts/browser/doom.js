/**
 * TTDoom browser host -- game state + input + rendering via font hinting.
 *
 * Architecture: JS = CPU (game logic, state, collision), Font = GPU (raycasting).
 * JS passes player position and angle to the font via variation axes.
 * The font's hinting VM raycasts and repositions glyph bars.
 *
 * Axis encoding (fvar range -1000..1000, GETVARIATION normalizes to F2Dot14):
 *   MOVX: player_x mapped to -1000..1000 (world range 0..1024)
 *   MOVY: player_y mapped to -1000..1000
 *   TURN: player_angle mapped to -1000..1000 (angle range 0..256)
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

    // Movement constants
    var MOVE_SPEED = 3;
    var TURN_SPEED = 1;
    var CELL_SIZE = 64;

    // 16x16 map -- must match game/build.py LEVEL_1
    var MAP = [
        1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
        1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,
        1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,
        1,0,0,1,1,1,0,0,0,1,1,1,0,0,0,1,
        1,0,0,1,0,0,0,0,0,0,0,1,0,0,0,1,
        1,0,0,1,0,0,0,0,0,0,0,1,0,0,0,1,
        1,0,0,0,0,0,1,0,1,0,0,0,0,0,0,1,
        1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,
        1,0,0,0,0,0,1,0,1,0,0,0,0,0,0,1,
        1,0,0,1,0,0,0,0,0,0,0,1,0,0,0,1,
        1,0,0,1,0,0,0,0,0,0,0,1,0,0,0,1,
        1,0,0,1,1,1,0,0,0,1,1,1,0,0,0,1,
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

    // --- Sound effects (Web Audio API, procedural) ---
    var audioCtx = null;
    var lastFootstepTime = 0;
    var FOOTSTEP_INTERVAL = 0.3; // seconds between footstep clicks

    function initAudio() {
        if (audioCtx) return;
        try {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        } catch (e) {
            // Web Audio not supported -- sounds disabled silently.
        }
    }

    function playFootstep(now) {
        if (!audioCtx) return;
        if (now - lastFootstepTime < FOOTSTEP_INTERVAL) return;
        lastFootstepTime = now;

        // Short percussive click
        var osc = audioCtx.createOscillator();
        var gain = audioCtx.createGain();
        osc.type = "square";
        osc.frequency.value = 80;
        gain.gain.setValueAtTime(0.04, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.06);
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.start(audioCtx.currentTime);
        osc.stop(audioCtx.currentTime + 0.06);
    }

    function playTurnSound() {
        if (!audioCtx) return;

        // Subtle filtered noise whoosh
        var bufferSize = audioCtx.sampleRate * 0.05; // 50ms
        var buffer = audioCtx.createBuffer(1, bufferSize, audioCtx.sampleRate);
        var data = buffer.getChannelData(0);
        for (var i = 0; i < bufferSize; i++) {
            data[i] = (Math.random() * 2 - 1) * 0.015;
        }
        var source = audioCtx.createBufferSource();
        source.buffer = buffer;

        var filter = audioCtx.createBiquadFilter();
        filter.type = "bandpass";
        filter.frequency.value = 2000;
        filter.Q.value = 2;

        var gain = audioCtx.createGain();
        gain.gain.setValueAtTime(0.03, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.05);

        source.connect(filter);
        filter.connect(gain);
        gain.connect(audioCtx.destination);
        source.start(audioCtx.currentTime);
    }

    // Initialise audio on first user interaction (browser autoplay policy)
    document.addEventListener("keydown", function handler() {
        initAudio();
        document.removeEventListener("keydown", handler);
    }, { once: true });

    // --- Minimap ---
    function drawMinimap() {
        var c = document.getElementById("minimap");
        if (!c) return;
        var ctx = c.getContext("2d");
        var size = 150;
        var cell = size / 16;

        ctx.fillStyle = "#111";
        ctx.fillRect(0, 0, size, size);

        // Draw walls
        ctx.fillStyle = "#333";
        for (var y = 0; y < 16; y++) {
            for (var x = 0; x < 16; x++) {
                if (MAP[y * 16 + x] === 1) {
                    ctx.fillRect(x * cell, y * cell, cell + 0.5, cell + 0.5);
                }
            }
        }

        // Draw player
        var pmx = px / 1024 * size;
        var pmy = py / 1024 * size;
        ctx.fillStyle = "#f00";
        ctx.beginPath();
        ctx.arc(pmx, pmy, 3, 0, Math.PI * 2);
        ctx.fill();

        // Draw look direction
        var rad = angle / 256 * Math.PI * 2;
        ctx.strokeStyle = "#f00";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(pmx, pmy);
        ctx.lineTo(pmx + Math.cos(rad) * 20, pmy + Math.sin(rad) * 20);
        ctx.stroke();

        // FOV cone (67 degrees = ~0.37 * 256 angle units)
        var fovHalf = 67 / 2 * Math.PI / 180;
        ctx.strokeStyle = "rgba(255,0,0,0.25)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(pmx, pmy);
        ctx.lineTo(pmx + Math.cos(rad - fovHalf) * 30, pmy + Math.sin(rad - fovHalf) * 30);
        ctx.moveTo(pmx, pmy);
        ctx.lineTo(pmx + Math.cos(rad + fovHalf) * 30, pmy + Math.sin(rad + fovHalf) * 30);
        ctx.stroke();
    }

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
        var turning = false;
        if (pressed["ArrowRight"]) { angle = (angle + turnAmt) % 256; turning = true; }
        if (pressed["ArrowLeft"])  { angle = (angle - turnAmt + 256) % 256; turning = true; }
        if (turning) playTurnSound();

        // --- Movement ---
        var rad = angle / 256 * Math.PI * 2;
        var cosA = Math.cos(rad);
        var sinA = Math.sin(rad);
        var dx = 0, dy = 0;
        var moving = false;

        if (pressed["KeyW"] || pressed["ArrowUp"]) {
            dx += cosA * moveAmt;
            dy += sinA * moveAmt;
            moving = true;
        }
        if (pressed["KeyS"] || pressed["ArrowDown"]) {
            dx -= cosA * moveAmt;
            dy -= sinA * moveAmt;
            moving = true;
        }
        if (pressed["KeyD"]) {
            dx += sinA * moveAmt;
            dy -= cosA * moveAmt;
            moving = true;
        }
        if (pressed["KeyA"]) {
            dx -= sinA * moveAmt;
            dy += cosA * moveAmt;
            moving = true;
        }

        if (moving) playFootstep(now / 1000);

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
        //   position: (raw+16384)/32 -> 0..1024 when raw is -16384..+16384
        //   angle:    (raw+16384)/128 -> 0..256 when raw is -16384..+16384
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

        // --- Minimap ---
        drawMinimap();

        // --- FPS ---
        frameCount++;
        var now2 = performance.now();
        if (now2 - lastFpsTime >= 1000) {
            fps = frameCount;
            frameCount = 0;
            lastFpsTime = now2;
            if (statusEl) {
                statusEl.textContent = fps + " fps | pos=(" +
                    Math.round(px) + "," + Math.round(py) +
                    ") angle=" + angle.toFixed(1);
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
