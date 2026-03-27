/**
 * TTDoom browser host -- game loop and input handling.
 *
 * Maps keyboard input to font variation axis values and updates the
 * font-variation-settings CSS property each frame, causing the TrueType
 * hinting VM to execute one game tick and reposition glyph points.
 *
 * Axis mapping (F2Dot14 via fvar normalisation):
 *   MOVX  -1000..+1000  forward/backward movement
 *   MOVY  -1000..+1000  strafe left/right
 *   TURN  -1000..+1000  rotate left/right
 *   FIRE     0..+1000   fire button
 *   ACTN     0..+1000   action button
 */

(function () {
    "use strict";

    var el = document.getElementById("game");
    var statusEl = document.getElementById("status");

    // Current key state.
    var pressed = {};

    // Axis values, updated each frame.
    var axes = {
        MOVX: 0,
        MOVY: 0,
        TURN: 0,
        FIRE: 0,
        ACTN: 0
    };

    // Frame counter for the status display.
    var frameCount = 0;
    var lastFpsTime = performance.now();
    var fps = 0;

    // --- Input listeners ---

    document.addEventListener("keydown", function (e) {
        pressed[e.code] = true;
        // Prevent scrolling with arrow keys and space.
        if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Space"].indexOf(e.code) !== -1) {
            e.preventDefault();
        }
    });

    document.addEventListener("keyup", function (e) {
        pressed[e.code] = false;
    });

    // --- Game loop ---

    function gameLoop() {
        // Map movement keys to axis values.
        // Positive = forward/right, negative = backward/left.
        // The axis range is -1000..+1000 with 0 as neutral.
        axes.MOVX = 0;
        if (pressed["KeyW"] || pressed["ArrowUp"]) axes.MOVX = 1000;
        if (pressed["KeyS"] || pressed["ArrowDown"]) axes.MOVX = -1000;

        axes.MOVY = 0;
        if (pressed["KeyD"]) axes.MOVY = 1000;
        if (pressed["KeyA"]) axes.MOVY = -1000;

        axes.TURN = 0;
        if (pressed["ArrowRight"]) axes.TURN = 1000;
        if (pressed["ArrowLeft"]) axes.TURN = -1000;

        axes.FIRE = pressed["Space"] ? 1000 : 0;
        axes.ACTN = pressed["KeyE"] ? 1000 : 0;

        // Apply axis values as font variation settings.
        el.style.fontVariationSettings =
            "'MOVX' " + axes.MOVX +
            ", 'MOVY' " + axes.MOVY +
            ", 'TURN' " + axes.TURN +
            ", 'FIRE' " + axes.FIRE +
            ", 'ACTN' " + axes.ACTN;

        // FPS tracking.
        frameCount++;
        var now = performance.now();
        if (now - lastFpsTime >= 1000) {
            fps = frameCount;
            frameCount = 0;
            lastFpsTime = now;
            if (statusEl) {
                statusEl.textContent = fps + " fps | axes: " +
                    "MOVX=" + axes.MOVX +
                    " MOVY=" + axes.MOVY +
                    " TURN=" + axes.TURN;
            }
        }

        requestAnimationFrame(gameLoop);
    }

    // --- Font load detection ---

    // Wait for the custom font to load before starting the game loop.
    if (document.fonts) {
        document.fonts.ready.then(function () {
            if (statusEl) statusEl.textContent = "Ready";
            gameLoop();
        });
    } else {
        // Fallback for browsers without the Font Loading API.
        setTimeout(function () {
            if (statusEl) statusEl.textContent = "Ready (fallback)";
            gameLoop();
        }, 500);
    }
})();
