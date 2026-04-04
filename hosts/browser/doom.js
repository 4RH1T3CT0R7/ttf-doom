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

    // Combat / HUD state
    var health = 100;
    var ammo = 50;
    var score = 0;
    var muzzleFlashTimer = 0;
    var lastShotTime = 0;
    var SHOT_COOLDOWN = 0.55; // seconds — realistic firing rate
    var dead = false;

    // Debug overlay (toggled with Tab key)
    var debugMode = false;

    // --- Sprite preloading ---
    var sprites = {};
    var weaponFrames = []; // animated weapon frames
    function preloadSprites() {
        var files = {
            enemy1: 'sprites/enemy1.png',
            enemy2: 'sprites/enemy2.png',
            enemy1_dead: 'sprites/enemy1_dead.png',
            enemy2_dead: 'sprites/enemy2_dead.png'
        };
        for (var key in files) {
            sprites[key] = new Image();
            sprites[key].src = files[key];
        }
        // Weapon animation frames (CC0 FPS sprites)
        var wNames = ['weapon_idle', 'weapon_fire1', 'weapon_fire2', 'weapon_fire3', 'weapon_fire4'];
        for (var i = 0; i < wNames.length; i++) {
            weaponFrames[i] = new Image();
            weaponFrames[i].src = 'sprites/' + wNames[i] + '.png';
        }
    }
    preloadSprites();

    // --- Enemies ---
    var ENEMY_SPEED = 30;        // world units per second
    var ENEMY_ATTACK_RANGE = 25; // within this distance enemies deal damage
    var ENEMY_ATTACK_DPS = 10;   // damage per second on contact
    var ENEMY_DAMAGE = 35;       // damage per shot

    // Initial enemy spawn data (kept so we can reset on restart)
    // Spawn positions verified: all in open cells (map value = 0)
    var ENEMY_SPAWNS = [
        { x: 450, y: 200, hp: 100, type: 1 },  // cell(7,3) — open
        { x: 300, y: 800, hp: 100, type: 1 },   // cell(4,12) — open
        { x: 800, y: 480, hp: 100, type: 2 },   // cell(12,7) — open
        { x: 320, y: 480, hp: 150, type: 2 }    // cell(5,7) — open
    ];

    var enemies = [];

    /** Check if there is a clear line of sight from (x0,y0) to (x1,y1) */
    function hasLineOfSight(x0, y0, x1, y1) {
        var ddx = x1 - x0;
        var ddy = y1 - y0;
        var dist = Math.sqrt(ddx * ddx + ddy * ddy);
        if (dist < 1) return true;
        var steps = Math.ceil(dist / 4); // check every 4 units for precision
        for (var i = 1; i < steps; i++) {
            var t = i / steps;
            var cx = x0 + ddx * t;
            var cy = y0 + ddy * t;
            if (isWall(cx, cy)) return false;
        }
        return true;
    }

    function spawnEnemies() {
        enemies = ENEMY_SPAWNS.map(function (s) {
            return { x: s.x, y: s.y, hp: s.hp, alive: true, type: s.type, hurtTimer: 0 };
        });
    }
    spawnEnemies();

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
        // Toggle debug overlay with Tab (no conflict with movement keys)
        if (e.code === "Tab" && !e.repeat) { debugMode = !debugMode; e.preventDefault(); }
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

    function playShootSound() {
        if (!audioCtx) return;
        var osc = audioCtx.createOscillator();
        var gain = audioCtx.createGain();
        osc.type = "sawtooth";
        osc.frequency.setValueAtTime(150, audioCtx.currentTime);
        osc.frequency.exponentialRampToValueAtTime(50, audioCtx.currentTime + 0.15);
        gain.gain.setValueAtTime(0.15, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.15);
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.start();
        osc.stop(audioCtx.currentTime + 0.15);
    }

    function playEnemyDeathSound() {
        if (!audioCtx) return;
        var osc = audioCtx.createOscillator();
        var gain = audioCtx.createGain();
        osc.type = "square";
        osc.frequency.setValueAtTime(200, audioCtx.currentTime);
        osc.frequency.exponentialRampToValueAtTime(30, audioCtx.currentTime + 0.4);
        gain.gain.setValueAtTime(0.12, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.4);
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.start();
        osc.stop(audioCtx.currentTime + 0.4);
    }

    function playHurtSound() {
        if (!audioCtx) return;
        var osc = audioCtx.createOscillator();
        var gain = audioCtx.createGain();
        osc.type = "sawtooth";
        osc.frequency.setValueAtTime(100, audioCtx.currentTime);
        osc.frequency.exponentialRampToValueAtTime(60, audioCtx.currentTime + 0.2);
        gain.gain.setValueAtTime(0.08, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.2);
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.start();
        osc.stop(audioCtx.currentTime + 0.2);
    }

    // Initialise audio on first user interaction (browser autoplay policy)
    document.addEventListener("keydown", function handler() {
        initAudio();
        document.removeEventListener("keydown", handler);
    }, { once: true });

    // --- Enemy AI ---
    function updateEnemies(dt) {
        if (dead) return;
        enemies.forEach(function (e) {
            if (!e.alive) return;

            // Tick hurt flash timer
            if (e.hurtTimer > 0) e.hurtTimer -= dt;

            var dx = px - e.x;
            var dy = py - e.y;
            var dist = Math.sqrt(dx * dx + dy * dy);

            if (dist < ENEMY_ATTACK_RANGE) {
                // Attack player
                health -= ENEMY_ATTACK_DPS * dt;
                if (health <= 0) {
                    health = 0;
                    dead = true;
                }
                return;
            }

            // Simple chase -- move toward player if not too far
            if (dist < 500 && dist > 0) {
                var moveX = dx / dist * ENEMY_SPEED * dt;
                var moveY = dy / dist * ENEMY_SPEED * dt;

                // Collision check against walls for enemies too
                var nx = e.x + moveX;
                var ny = e.y + moveY;
                if (!isWall(nx, e.y)) e.x = nx;
                if (!isWall(e.x, ny)) e.y = ny;
            }
        });
    }

    // --- Shooting (hitscan) ---
    function shoot(now) {
        if (dead) return;
        if (ammo <= 0) return;
        if (now - lastShotTime < SHOT_COOLDOWN) return;
        lastShotTime = now;
        ammo--;

        playShootSound();
        muzzleFlashTimer = 0.1;

        // Hitscan: find closest enemy near crosshair
        var playerRad = angle / 256 * Math.PI * 2;
        var bestDist = Infinity;
        var bestEnemy = null;

        enemies.forEach(function (e) {
            if (!e.alive) return;
            var dx = e.x - px;
            var dy = e.y - py;
            var dist = Math.sqrt(dx * dx + dy * dy);
            if (dist < 1) return;

            var enemyRad = Math.atan2(dy, dx);
            var relAngle = enemyRad - playerRad;

            // Normalize to -PI..PI
            while (relAngle > Math.PI) relAngle -= Math.PI * 2;
            while (relAngle < -Math.PI) relAngle += Math.PI * 2;

            // Hit tolerance: ~5.7 degrees -- generous enough for fun
            if (Math.abs(relAngle) < 0.1 && dist < bestDist) {
                bestDist = dist;
                bestEnemy = e;
            }
        });

        if (bestEnemy) {
            bestEnemy.hp -= ENEMY_DAMAGE;
            bestEnemy.hurtTimer = 0.15;
            if (bestEnemy.hp <= 0) {
                bestEnemy.alive = false;
                score += 100;
                playEnemyDeathSound();
            } else {
                playHurtSound();
            }
        }
    }

    // --- Restart game ---
    function restartGame() {
        px = 480;
        py = 480;
        angle = 0;
        health = 100;
        ammo = 50;
        score = 0;
        muzzleFlashTimer = 0;
        lastShotTime = 0;
        dead = false;
        spawnEnemies();
    }

    // --- Overlay rendering ---

    /** Render all alive enemies onto the overlay canvas */
    function renderEnemies(ctx, w, h) {
        var playerRad = angle / 256 * Math.PI * 2;
        var fovHalfRad = 24 / 256 * Math.PI * 2; // ~67 degree FOV, half-angle

        // Collect visible enemies with their distance for depth sorting
        var visible = [];

        enemies.forEach(function (e) {
            if (!e.alive) return;

            var dx = e.x - px;
            var dy = e.y - py;
            var dist = Math.sqrt(dx * dx + dy * dy);
            if (dist < 1) return;

            var enemyRad = Math.atan2(dy, dx);
            var relAngle = enemyRad - playerRad;

            // Normalize to -PI..PI
            while (relAngle > Math.PI) relAngle -= Math.PI * 2;
            while (relAngle < -Math.PI) relAngle += Math.PI * 2;

            // FOV check
            if (Math.abs(relAngle) > fovHalfRad) return;

            // Line-of-sight check: don't show enemies behind walls
            if (!hasLineOfSight(px, py, e.x, e.y)) return;

            visible.push({ e: e, dist: dist, relAngle: relAngle });
        });

        // Sort far to near so closer enemies paint on top
        visible.sort(function (a, b) { return b.dist - a.dist; });

        visible.forEach(function (v) {
            var e = v.e;
            var dist = v.dist;
            var relAngle = v.relAngle;

            // Screen X: map relative angle to canvas width
            var screenX = (relAngle / fovHalfRad * 0.5 + 0.5) * w;

            // Size based on distance (closer = bigger)
            var size = Math.min(200, 3000 / dist);
            var screenY = h * 0.5; // vertically centered

            // Draw sprite image
            var spriteKey = e.type === 1 ? 'enemy1' : 'enemy2';
            var img = sprites[spriteKey];
            if (img && img.complete && img.naturalWidth > 0) {
                var spriteH = size * 2;
                var spriteW = spriteH * (img.width / img.height);

                // Pixelated scaling for retro look
                ctx.imageSmoothingEnabled = false;
                ctx.drawImage(img, screenX - spriteW / 2, screenY - spriteH / 2, spriteW, spriteH);
                ctx.imageSmoothingEnabled = true;

                // Hurt flash: semi-transparent white overlay
                if (e.hurtTimer > 0) {
                    ctx.globalAlpha = 0.5;
                    ctx.fillStyle = "#fff";
                    ctx.fillRect(screenX - spriteW / 2, screenY - spriteH / 2, spriteW, spriteH);
                    ctx.globalAlpha = 1.0;
                }
            } else {
                // Fallback: colored rectangle if sprite not loaded yet
                ctx.fillStyle = e.type === 1 ? "#c00" : "#d60";
                ctx.fillRect(screenX - size * 0.5, screenY - size, size, size * 2);
            }

            // Health bar above enemy
            if (e.hp < (e.type === 2 ? 150 : 100)) {
                var barW = size * 0.8;
                var barH = Math.max(2, size * 0.08);
                var barX = screenX - barW * 0.5;
                var barY = screenY - size - 6;
                var maxHp = e.type === 2 ? 150 : 100;
                var hpFrac = Math.max(0, e.hp / maxHp);

                ctx.fillStyle = "#300";
                ctx.fillRect(barX, barY, barW, barH);
                ctx.fillStyle = hpFrac > 0.3 ? "#0f0" : "#f00";
                ctx.fillRect(barX, barY, barW * hpFrac, barH);
            }
        });
    }

    /** Render the weapon at the bottom center of the overlay */
    function renderWeapon(ctx, w, h) {
        // Pixel-art DOOM-style pistol drawn on canvas
        // Scale factor based on screen height
        var S = Math.floor(h / 100); // pixel size
        if (S < 2) S = 2;
        var firing = muzzleFlashTimer > 0;
        var recoil = firing ? Math.floor(S * 2 * (muzzleFlashTimer / 0.15)) : 0;

        // Anchor: bottom-center of screen
        var bx = Math.floor(w / 2); // center x
        var by = h - recoil;        // bottom y (shifts up on recoil)

        ctx.imageSmoothingEnabled = false;

        // Helper: draw a pixel block
        function px(x, y, color) {
            ctx.fillStyle = color;
            ctx.fillRect(bx + x * S, by + y * S, S, S);
        }
        function rect(x, y, rw, rh, color) {
            ctx.fillStyle = color;
            ctx.fillRect(bx + x * S, by + y * S, rw * S, rh * S);
        }

        // --- Hand (green/tan skin like DOOM marine) ---
        var skin = '#b8956a';
        var skinDk = '#8a6d4a';
        var glove = '#4a6a2a'; // olive green glove
        var gloveDk = '#3a5420';

        // Forearm (bottom, coming from below-right)
        rect(-8, -12, 16, 14, skin);    // main forearm block
        rect(-9, -10, 1, 10, skinDk);   // left shadow
        rect(8, -10, 1, 10, skinDk);    // right shadow
        rect(-7, -6, 14, 8, skin);      // wider lower arm

        // Glove / wrist
        rect(-6, -14, 12, 4, glove);
        rect(-5, -15, 10, 2, gloveDk);
        rect(-7, -12, 1, 3, gloveDk);
        rect(6, -12, 1, 3, gloveDk);

        // Fingers gripping
        rect(-3, -17, 2, 3, skin);   // thumb
        rect(1, -17, 2, 3, skin);    // index finger area
        rect(-1, -16, 2, 2, skinDk); // grip shadow

        // --- Pistol body ---
        var metal = '#666';
        var metalLt = '#888';
        var metalDk = '#444';
        var grip = '#553';
        var gripDk = '#332';

        // Barrel (horizontal, pointing up-right from hand)
        rect(-2, -24, 4, 8, metal);      // barrel
        rect(-1, -26, 2, 3, metalDk);    // muzzle
        rect(-3, -22, 1, 6, metalDk);    // barrel left shadow
        rect(2, -22, 1, 6, metalLt);     // barrel right highlight

        // Slide
        rect(-4, -20, 8, 4, metalLt);    // slide body
        rect(-4, -20, 8, 1, metalDk);    // slide top edge
        rect(-4, -17, 1, 2, metalDk);    // slide shadow left
        rect(4, -20, 1, 4, metal);       // slide right edge

        // Trigger guard
        rect(-3, -16, 6, 1, metal);
        rect(-3, -16, 1, 3, metalDk);
        rect(2, -16, 1, 3, metalDk);

        // Trigger
        rect(0, -15, 1, 2, '#a33');

        // Grip (pistol handle)
        rect(-3, -13, 6, 5, grip);
        rect(-3, -13, 1, 5, gripDk);
        rect(2, -13, 1, 5, gripDk);
        rect(-2, -8, 4, 1, gripDk);     // grip bottom

        // Grip texture lines
        for (var i = 0; i < 3; i++) {
            rect(-1, -12 + i * 2, 3, 1, gripDk);
        }

        // --- Muzzle flash (when firing) ---
        if (firing) {
            var flashSize = S * 4;
            var fx = bx;
            var fy = by - 27 * S;

            // Outer glow
            ctx.fillStyle = 'rgba(255,200,50,0.4)';
            ctx.beginPath();
            ctx.arc(fx, fy, flashSize * 2, 0, Math.PI * 2);
            ctx.fill();

            // Core flash
            ctx.fillStyle = 'rgba(255,255,100,0.7)';
            ctx.beginPath();
            ctx.arc(fx, fy, flashSize, 0, Math.PI * 2);
            ctx.fill();

            // White center
            ctx.fillStyle = 'rgba(255,255,255,0.9)';
            ctx.beginPath();
            ctx.arc(fx, fy, flashSize * 0.4, 0, Math.PI * 2);
            ctx.fill();

            // Flash spikes
            ctx.strokeStyle = 'rgba(255,200,50,0.6)';
            ctx.lineWidth = S;
            for (var a = 0; a < 5; a++) {
                var ang = a * Math.PI * 2 / 5 - Math.PI / 2;
                var len = flashSize * (1.5 + Math.random() * 0.5);
                ctx.beginPath();
                ctx.moveTo(fx, fy);
                ctx.lineTo(fx + Math.cos(ang) * len, fy + Math.sin(ang) * len);
                ctx.stroke();
            }
        }

        ctx.imageSmoothingEnabled = true;
    }

    /** Render the in-game HUD (health, ammo, score) */
    function renderHUD(ctx, w, h) {
        var barH = 18;
        var barY = h - barH - 8;
        var barW = 140;

        // Background strip for readability
        ctx.fillStyle = "rgba(0, 0, 0, 0.5)";
        ctx.fillRect(0, barY - 4, w, barH + 12);

        // Health bar background
        ctx.fillStyle = "#300";
        ctx.fillRect(10, barY, barW, barH);
        // Health bar fill
        var hpFrac = Math.max(0, health) / 100;
        ctx.fillStyle = health > 30 ? "#0c0" : "#f00";
        ctx.fillRect(10, barY, barW * hpFrac, barH);
        // Health bar border
        ctx.strokeStyle = "#666";
        ctx.lineWidth = 1;
        ctx.strokeRect(10, barY, barW, barH);

        // Text
        ctx.fillStyle = "#fff";
        ctx.font = "bold 12px monospace";
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        ctx.fillText("HP: " + Math.floor(Math.max(0, health)), 15, barY + barH * 0.5);

        // Ammo
        ctx.fillStyle = ammo > 10 ? "#ff0" : "#f44";
        ctx.textAlign = "center";
        ctx.fillText("AMMO: " + ammo, w * 0.5, barY + barH * 0.5);

        // Score
        ctx.fillStyle = "#fff";
        ctx.textAlign = "right";
        ctx.fillText("SCORE: " + score, w - 10, barY + barH * 0.5);

        // Reset text align
        ctx.textAlign = "left";
    }

    /** Render the death screen overlay */
    function renderDeathScreen(ctx, w, h) {
        // Red tint
        ctx.fillStyle = "rgba(180, 0, 0, 0.55)";
        ctx.fillRect(0, 0, w, h);

        // "YOU DIED" text
        ctx.fillStyle = "#fff";
        ctx.font = "bold 48px monospace";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("YOU DIED", w * 0.5, h * 0.45);

        // Score
        ctx.font = "24px monospace";
        ctx.fillText("SCORE: " + score, w * 0.5, h * 0.55);

        // Restart instruction
        ctx.font = "18px monospace";
        ctx.fillStyle = "#ccc";
        ctx.fillText("Press R to restart", w * 0.5, h * 0.65);

        // Reset
        ctx.textAlign = "left";
        ctx.textBaseline = "alphabetic";
    }

    // --- Debug: JS raycast (mirrors font hinting VM ray marcher) ---
    function jsRaycast(col) {
        var ra = angle + col * 3 - 24; // FOV_HALF = 24
        while (ra < 0) ra += 256;
        while (ra >= 256) ra -= 256;
        var cosVal = Math.cos(ra / 256 * Math.PI * 2) * 256;
        var sinVal = Math.sin(ra / 256 * Math.PI * 2) * 256;
        var rpx = px, rpy = py;
        for (var s = 0; s < 14; s++) {
            rpx += cosVal / 4;
            rpy += sinVal / 4;
            if (isWall(rpx, rpy)) {
                return s + 1;
            }
        }
        return 14; // MAX_STEPS
    }

    /** Feature 1: Font Axis Debug Overlay — shows live font-variation-settings */
    function renderDebugOverlay(ctx, w, h, axisX, axisY, axisA) {
        var panelW = 310;
        var panelH = 240;
        var panelX = 12;
        var panelY = 40;

        // Semi-transparent background
        ctx.fillStyle = "rgba(0,0,0,0.75)";
        ctx.fillRect(panelX, panelY, panelW, panelH);

        // Border
        ctx.strokeStyle = "#0f0";
        ctx.lineWidth = 1;
        ctx.strokeRect(panelX, panelY, panelW, panelH);

        // Title
        ctx.fillStyle = "#0f0";
        ctx.font = "bold 11px monospace";
        ctx.textAlign = "left";
        ctx.textBaseline = "top";
        ctx.fillText("font-variation-settings", panelX + 10, panelY + 8);

        // Draw axis bars
        var axes = [
            { name: "MOVX", value: axisX },
            { name: "MOVY", value: axisY },
            { name: "TURN", value: axisA }
        ];
        var barX = panelX + 60;
        var barW = 140;
        var barH = 12;
        var startY = panelY + 32;

        for (var i = 0; i < axes.length; i++) {
            var ax = axes[i];
            var y = startY + i * 26;

            // Label
            ctx.fillStyle = "#0f0";
            ctx.font = "bold 11px monospace";
            ctx.fillText(ax.name, panelX + 10, y);

            // Bar background
            ctx.fillStyle = "#1a1a1a";
            ctx.fillRect(barX, y, barW, barH);
            ctx.strokeStyle = "#0a0";
            ctx.lineWidth = 0.5;
            ctx.strokeRect(barX, y, barW, barH);

            // Bar fill: (value + 1000) / 2000 maps -1000..1000 to 0..1
            var frac = (ax.value + 1000) / 2000;
            frac = Math.max(0, Math.min(1, frac));
            var fillW = barW * frac;

            ctx.fillStyle = "#0c0";
            ctx.fillRect(barX, y, fillW, barH);

            // Unfilled portion (dimmer)
            ctx.fillStyle = "#030";
            ctx.fillRect(barX + fillW, y, barW - fillW, barH);

            // Value text
            ctx.fillStyle = "#0f0";
            ctx.font = "11px monospace";
            ctx.fillText(ax.value.toFixed(1), barX + barW + 8, y);
        }

        // CSS string (live)
        var cssY = startY + axes.length * 26 + 12;
        ctx.fillStyle = "#0a0";
        ctx.font = "10px monospace";
        ctx.fillText("'MOVX' " + axisX.toFixed(1) + ", 'MOVY' " + axisY.toFixed(1) + ",", panelX + 10, cssY);
        ctx.fillText("'TURN' " + axisA.toFixed(1), panelX + 10, cssY + 14);

        // Font engine info
        var infoY = cssY + 38;
        ctx.fillStyle = "#0f0";
        ctx.font = "bold 11px monospace";
        ctx.fillText("TrueType Hinting VM", panelX + 10, infoY);

        ctx.fillStyle = "#0a0";
        ctx.font = "10px monospace";
        ctx.fillText("13 FDEF functions \u2022 795 storage", panelX + 10, infoY + 16);
        ctx.fillText("doom.ttf \u2022 6,580 bytes", panelX + 10, infoY + 30);
    }

    /** Feature 3: Glyph Inspector — shows per-column raycast bar heights */
    function renderGlyphInspector(ctx, w, h) {
        var inspW = 260;
        var inspH = 180;
        var inspX = 12;
        var inspY = h - inspH - 40;

        // Background
        ctx.fillStyle = "rgba(0,0,0,0.75)";
        ctx.fillRect(inspX, inspY, inspW, inspH);

        // Border
        ctx.strokeStyle = "#0f0";
        ctx.lineWidth = 1;
        ctx.strokeRect(inspX, inspY, inspW, inspH);

        // Title
        ctx.fillStyle = "#0f0";
        ctx.font = "bold 11px monospace";
        ctx.textAlign = "left";
        ctx.textBaseline = "top";
        ctx.fillText("Glyph 'A' \u2014 16 contours, 64 points", inspX + 8, inspY + 6);

        // Bar chart area
        var chartX = inspX + 14;
        var chartY = inspY + 26;
        var chartW = inspW - 28;
        var chartH = inspH - 60;
        var numCols = 16;
        var barW = 12;
        var gap = (chartW - numCols * barW) / (numCols - 1);

        for (var col = 0; col < numCols; col++) {
            var steps = jsRaycast(col);

            // Bar height proportional to wall distance (closer = taller bar)
            // steps ranges 1..14: 1=very close (tall bar), 14=far (short bar)
            var barFrac = 1 - (steps - 1) / 13; // 1=full height, 0=minimum
            var barH = Math.max(4, chartH * barFrac);

            var bx = chartX + col * (barW + gap);
            var by = chartY + chartH - barH;

            // Bar fill
            var intensity = Math.floor(100 + 155 * barFrac);
            ctx.fillStyle = "rgb(0," + intensity + ",0)";
            ctx.fillRect(bx, by, barW, barH);

            // Bar outline
            ctx.strokeStyle = "#0a0";
            ctx.lineWidth = 0.5;
            ctx.strokeRect(bx, by, barW, barH);

            // Column index label
            ctx.fillStyle = "#0a0";
            ctx.font = "8px monospace";
            ctx.textAlign = "center";
            ctx.fillText(col.toString(), bx + barW / 2, chartY + chartH + 10);
        }

        // Reset text alignment
        ctx.textAlign = "left";
    }

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

        // Draw enemies
        enemies.forEach(function (e) {
            if (!e.alive) return;
            var emx = e.x / 1024 * size;
            var emy = e.y / 1024 * size;
            ctx.fillStyle = e.type === 1 ? "#f44" : "#fa0";
            ctx.beginPath();
            ctx.arc(emx, emy, 2.5, 0, Math.PI * 2);
            ctx.fill();
        });

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

        // Feature 2: Ray visualization (only in debug mode)
        if (debugMode) {
            var dbgFovHalf = 24; // must match font's FOV_HALF
            var dbgNumCols = 16; // must match font's NUM_COLS

            for (var col = 0; col < dbgNumCols; col++) {
                var rayAngle = angle + col * 3 - dbgFovHalf;
                var rayRad = rayAngle / 256 * Math.PI * 2;

                var rx = px, ry = py;
                var rdx = Math.cos(rayRad) * 16;
                var rdy = Math.sin(rayRad) * 16;

                // Step until hitting a wall (mirrors font's ray marcher)
                for (var rs = 0; rs < 14; rs++) {
                    rx += rdx;
                    ry += rdy;
                    if (isWall(rx, ry)) break;
                }

                // Map to minimap coordinates
                var startMX = px / 1024 * size;
                var startMY = py / 1024 * size;
                var endMX = rx / 1024 * size;
                var endMY = ry / 1024 * size;

                // Color by distance (green = far, yellow = mid, red = close)
                var rdist = Math.sqrt((rx - px) * (rx - px) + (ry - py) * (ry - py));
                var maxDist = 14 * 16;
                var t = Math.min(1, rdist / maxDist);
                var rr = Math.floor(255 * (1 - t));
                var rg = Math.floor(255 * t);
                ctx.strokeStyle = "rgba(" + rr + "," + rg + ",0,0.6)";
                ctx.lineWidth = 0.5;
                ctx.beginPath();
                ctx.moveTo(startMX, startMY);
                ctx.lineTo(endMX, endMY);
                ctx.stroke();

                // Hit point dot
                ctx.fillStyle = "#ff0";
                ctx.beginPath();
                ctx.arc(endMX, endMY, 1.5, 0, Math.PI * 2);
                ctx.fill();
            }
        }
    }

    // FPS counter
    var frameCount = 0, lastFpsTime = performance.now(), fps = 0;
    var renderFrame = 0;  // separate counter for re-render jitter
    var lastFrameTime = performance.now();

    // --- Overlay canvas setup ---
    var overlay = document.getElementById("overlay");
    var octx = overlay ? overlay.getContext("2d") : null;

    function gameLoop() {
        // Delta time for frame-rate independent movement
        var now = performance.now();
        var dt = Math.min((now - lastFrameTime) / 1000, 0.05); // cap at 50ms
        lastFrameTime = now;

        // --- Handle restart ---
        if (dead && pressed["KeyR"]) {
            restartGame();
        }

        var moveAmt = 100 * dt;  // 100 units/sec (~1.5 cells/sec)
        var turnAmt = 40 * dt;   // 40 angle-units/sec (full turn in ~6.4s)

        if (!dead) {
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
                dx -= sinA * moveAmt;
                dy += cosA * moveAmt;
                moving = true;
            }
            if (pressed["KeyA"]) {
                dx += sinA * moveAmt;
                dy -= cosA * moveAmt;
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

            // --- Update enemies ---
            updateEnemies(dt);

            // --- Shooting ---
            if (pressed["Space"]) {
                shoot(now / 1000);
            }

            // --- Muzzle flash timer ---
            if (muzzleFlashTimer > 0) muzzleFlashTimer -= dt;
        }

        // --- Map game state to font axes ---
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

        // --- Render overlay ---
        if (overlay && octx) {
            var rect = el.getBoundingClientRect();
            var ow = Math.round(rect.width);
            var oh = Math.round(rect.height);

            // Only resize canvas when dimensions actually change (avoids clearing cost)
            if (overlay.width !== ow || overlay.height !== oh) {
                overlay.width = ow;
                overlay.height = oh;
            } else {
                octx.clearRect(0, 0, ow, oh);
            }

            // Position overlay to match the game element
            overlay.style.left = Math.round(rect.left) + "px";
            overlay.style.top = Math.round(rect.top) + "px";

            if (dead) {
                renderDeathScreen(octx, ow, oh);
            } else {
                renderEnemies(octx, ow, oh);
                renderWeapon(octx, ow, oh);
                renderHUD(octx, ow, oh);
            }

            // Debug overlays (drawn on top of everything)
            if (debugMode) {
                renderDebugOverlay(octx, ow, oh, axisX, axisY, axisA);
                renderGlyphInspector(octx, ow, oh);
            }
        }

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
                var aliveCount = enemies.filter(function (e) { return e.alive; }).length;
                statusEl.textContent = fps + " fps | pos=(" +
                    Math.round(px) + "," + Math.round(py) +
                    ") angle=" + angle.toFixed(1) +
                    " | enemies: " + aliveCount;
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
