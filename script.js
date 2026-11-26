const REFRESH_INTERVAL = 30 * 60;
let timeLeft = REFRESH_INTERVAL;

function loadIframe(iframe) {
    if (!iframe.src && iframe.dataset.src) {
        iframe.src = iframe.dataset.src;
    }
}

function updateTimer() {
    const m = Math.floor(timeLeft / 60);
    const s = timeLeft % 60;
    document.getElementById('countdown').textContent =
        `${m < 10 ? '0' + m : m}:${s < 10 ? '0' + s : s}`;

    if (timeLeft <= 0) {
        refreshAllIframes();
        timeLeft = REFRESH_INTERVAL;
    } else {
        timeLeft--;
    }
}

function refreshAllIframes() {
    document.querySelectorAll('iframe[src]').forEach(iframe => {
        try {
            const url = new URL(iframe.src);
            url.searchParams.set('t', Date.now());
            iframe.src = url.toString();
        } catch (e) {
            const clean = iframe.src.replace(/[&?]t=\d+/, '');
            iframe.src = clean + (clean.includes('?') ? '&' : '?') + 't=' + Date.now();
        }
    });
}

function openTab(evt, tabId) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));

    const tab = document.getElementById(tabId);
    tab.classList.add('active');
    evt.currentTarget.classList.add('active');

    const iframe = tab.querySelector('iframe');
    if (iframe) loadIframe(iframe);
}

// Theme toggle
const themeBtn = document.getElementById('theme-toggle');
if (localStorage.getItem('theme') === 'dark') {
    document.body.classList.add('dark');
    themeBtn.textContent = '☀️';
}
themeBtn.addEventListener('click', () => {
    document.body.classList.toggle('dark');
    const isDark = document.body.classList.contains('dark');
    themeBtn.textContent = isDark ? '☀️' : '🌙';
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
});

// Initial load
loadIframe(document.querySelector('.tab-content.active iframe'));
setInterval(updateTimer, 1000);

let reloadingForUpdate = false;
let sessionStamp = null;

function reloadForUpdate() {
    if (reloadingForUpdate) return;
    reloadingForUpdate = true;
    window.location.reload();
}

async function shellStamp() {
    const files = ['./index.html', './style.css', './script.js'];
    const parts = [];
    for (const file of files) {
        const response = await fetch(file, { cache: 'no-store' });
        if (!response.ok) return null;
        parts.push(await response.text());
    }
    const text = parts.join('\n');
    if (!crypto.subtle) return String(text.length);
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
    return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
}

async function reloadIfShellChanged() {
    if (reloadingForUpdate) return;
    try {
        const stamp = await shellStamp();
        if (!stamp) return;
        if (sessionStamp === null) {
            sessionStamp = stamp;
            return;
        }
        if (stamp !== sessionStamp) reloadForUpdate();
    } catch (e) {}
}

if ('serviceWorker' in navigator) {
    navigator.serviceWorker.addEventListener('message', event => {
        if (!event.data || event.data.type !== 'dpgl-reload') return;
        reloadForUpdate();
    });

    navigator.serviceWorker.register('./sw.js').then(registration => {
        const checkForUpdate = () => {
            registration.update().catch(() => {});
            reloadIfShellChanged();
        };
        checkForUpdate();
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') checkForUpdate();
        });
        setInterval(checkForUpdate, 30 * 60 * 1000);
    }).catch(() => {});
}

// Slowly drifting, horizontal-only collision-bouncing buttons (single-row height preserved)
(function initFloatingButtons() {
    const MIN_WIDTH = 700;
    const PAD = 6;
    const GAP = 6;
    const MIN_SPEED = 14; // px/sec
    const MAX_SPEED = 22; // px/sec

    const navs = Array.from(document.querySelectorAll('.tabs-nav'));
    if (!navs.length) return;

    const toggleBtn = document.getElementById('float-toggle');
    let enabled = localStorage.getItem('dpgl-float-buttons') !== 'off';
    let active = false;
    let rafId = null;
    let lastTime = 0;
    let arenas = [];

    function updateToggleUi() {
        if (!toggleBtn) return;
        toggleBtn.textContent = enabled ? '⏸' : '▶';
        toggleBtn.title = enabled ? 'Остановить движение кнопок' : 'Включить движение кнопок';
        toggleBtn.setAttribute('aria-label', toggleBtn.title);
    }

    function teardown() {
        if (rafId) {
            cancelAnimationFrame(rafId);
            rafId = null;
        }
        arenas.forEach(arena => {
            arena.nav.classList.remove('floating-arena');
            arena.nav.style.height = '';
            arena.items.forEach(item => {
                item.el.classList.remove('floating-btn');
                item.el.style.transform = '';
                item.el.style.top = '';
            });
        });
        arenas = [];
        active = false;
    }

    function buildArena(nav) {
        const els = Array.from(nav.querySelectorAll('.tab-btn'));
        if (!els.length) return null;

        // Measure natural single-row height and button positions before absolute positioning
        const navRect = nav.getBoundingClientRect();
        const rects = els.map(el => el.getBoundingClientRect());
        const naturalHeight = Math.ceil(navRect.height);
        const W = nav.clientWidth;

        // If buttons already fill almost the entire row width, skip floating in this bar
        const totalButtonsW = rects.reduce((sum, r) => sum + Math.ceil(r.width), 0) + GAP * (els.length - 1) + PAD * 2;
        if (totalButtonsW >= W - 12) return null;

        nav.classList.add('floating-arena');
        nav.style.height = naturalHeight + 'px';

        // Place buttons left-to-right with even breathing room across the row
        const freeSpace = W - totalButtonsW;
        const extraStep = freeSpace / (els.length + 1);
        let cursor = PAD + extraStep;

        const items = [];
        els.forEach((el, idx) => {
            const w = Math.ceil(rects[idx].width);
            const h = Math.ceil(rects[idx].height);
            const topPx = Math.round((naturalHeight - h) / 2);

            el.classList.add('floating-btn');
            el.style.top = topPx + 'px';

            const x = cursor;
            cursor += w + GAP + extraStep;

            const dir = idx % 2 === 0 ? 1 : -1;
            const speed = MIN_SPEED + Math.random() * (MAX_SPEED - MIN_SPEED);
            const item = {
                el, w, x,
                vx: dir * speed,
                paused: false
            };

            el._floatItem = item;
            if (!el._floatBound) {
                el._floatBound = true;
                el.addEventListener('mouseenter', () => { if (el._floatItem) el._floatItem.paused = true; });
                el.addEventListener('mouseleave', () => { if (el._floatItem) el._floatItem.paused = false; });
                el.addEventListener('focus', () => { if (el._floatItem) el._floatItem.paused = true; });
                el.addEventListener('blur', () => { if (el._floatItem) el._floatItem.paused = false; });
            }

            items.push(item);
        });

        items.forEach(it => {
            it.el.style.transform = `translate3d(${it.x.toFixed(2)}px, 0, 0)`;
        });

        return { nav, items };
    }

    function step(now) {
        if (!active) return;
        const dt = Math.min(0.05, (now - lastTime) / 1000 || 0.016);
        lastTime = now;

        for (const arena of arenas) {
            const W = arena.nav.clientWidth;
            const items = arena.items;

            // Move horizontally only and bounce off left/right edges
            for (const it of items) {
                if (it.paused) continue;
                it.x += it.vx * dt;
                if (it.x <= PAD) {
                    it.x = PAD;
                    it.vx = Math.abs(it.vx);
                } else if (it.x + it.w >= W - PAD) {
                    it.x = Math.max(PAD, W - PAD - it.w);
                    it.vx = -Math.abs(it.vx);
                }
            }

            // Adjacent 1D elastic collisions (buttons stay ordered left-to-right, never overlap)
            for (let i = 0; i < items.length - 1; i++) {
                const a = items[i];
                const b = items[i + 1];
                const overlap = (a.x + a.w + GAP) - b.x;
                if (overlap > 0) {
                    if (a.paused && !b.paused) {
                        b.x = Math.min(W - PAD - b.w, a.x + a.w + GAP);
                        b.vx = Math.abs(b.vx);
                    } else if (b.paused && !a.paused) {
                        a.x = Math.max(PAD, b.x - GAP - a.w);
                        a.vx = -Math.abs(a.vx);
                    } else if (!a.paused && !b.paused) {
                        a.x = Math.max(PAD, a.x - overlap * 0.5);
                        b.x = Math.min(W - PAD - b.w, b.x + overlap * 0.5);
                        const tmp = a.vx;
                        a.vx = b.vx;
                        b.vx = tmp;
                        if (a.vx > b.vx) {
                            a.vx = -Math.abs(a.vx);
                            b.vx = Math.abs(b.vx);
                        }
                    }
                }
            }

            for (const it of items) {
                it.el.style.transform = `translate3d(${it.x.toFixed(2)}px, 0, 0)`;
            }
        }

        rafId = requestAnimationFrame(step);
    }

    function start() {
        teardown();
        if (!enabled || window.innerWidth < MIN_WIDTH) return;
        arenas = navs.map(buildArena).filter(Boolean);
        if (!arenas.length) return;
        active = true;
        lastTime = performance.now();
        rafId = requestAnimationFrame(step);
    }

    updateToggleUi();
    if (toggleBtn) {
        toggleBtn.addEventListener('click', () => {
            enabled = !enabled;
            localStorage.setItem('dpgl-float-buttons', enabled ? 'on' : 'off');
            updateToggleUi();
            if (enabled) start(); else teardown();
        });
    }

    let resizeTimer = null;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
            if (enabled) start(); else teardown();
        }, 180);
    });

    // Start right away as soon as DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();

// Idle screensaver: dims screen and floats DPGL77 emblem while smoothly changing its size
(function initIdleScreensaver() {
    const IDLE_MS = 90 * 1000; // 90 seconds of inactivity
    const BASE_H = 180;        // base emblem height (px)
    const ASPECT = 656 / 894;  // shield aspect ratio
    const MIN_SCALE = 0.55;
    const MAX_SCALE = 1.65;

    let overlay = null;
    let img = null;
    let idleTimer = null;
    let active = false;
    let rafId = null;
    let lastTime = 0;
    let x = 100, y = 100, vx = 42, vy = 32, phase = 0;

    function ensureOverlay() {
        if (overlay) return;
        overlay = document.createElement('div');
        overlay.id = 'dpgl-screensaver';
        overlay.setAttribute('aria-hidden', 'true');
        img = document.createElement('img');
        img.src = 'img/dpgl77-shield-large.png';
        img.alt = '';
        img.decoding = 'async';
        overlay.appendChild(img);
        document.body.appendChild(overlay);

        // Any click or touch on the screensaver dismisses it immediately
        overlay.addEventListener('pointerdown', stopSaver);
    }

    function tick(now) {
        if (!active) return;
        const dt = Math.min(0.05, (now - lastTime) / 1000 || 0.016);
        lastTime = now;

        phase += dt * 0.55; // slow breathing size cycle (~11.4s full cycle)
        const scale = MIN_SCALE + (MAX_SCALE - MIN_SCALE) * (0.5 + 0.5 * Math.sin(phase));
        const h = Math.min(BASE_H * scale, window.innerHeight * 0.65);
        const w = h * ASPECT;

        x += vx * dt;
        y += vy * dt;

        const maxX = Math.max(0, window.innerWidth - w);
        const maxY = Math.max(0, window.innerHeight - h);

        if (x <= 0) { x = 0; vx = Math.abs(vx); }
        else if (x >= maxX) { x = maxX; vx = -Math.abs(vx); }

        if (y <= 0) { y = 0; vy = Math.abs(vy); }
        else if (y >= maxY) { y = maxY; vy = -Math.abs(vy); }

        img.style.width = w.toFixed(1) + 'px';
        img.style.height = h.toFixed(1) + 'px';
        img.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0)`;

        rafId = requestAnimationFrame(tick);
    }

    function startSaver() {
        if (active || document.hidden) return;
        ensureOverlay();
        active = true;
        const startH = Math.min(BASE_H, window.innerHeight * 0.45);
        const startW = startH * ASPECT;
        x = Math.max(0, (window.innerWidth - startW) / 2);
        y = Math.max(0, (window.innerHeight - startH) / 2);
        const angle = (0.35 + Math.random() * 0.8) * (Math.random() < 0.5 ? 1 : -1);
        const speed = 46;
        vx = Math.cos(angle) * speed;
        vy = Math.sin(angle) * speed;
        phase = 0;
        overlay.classList.add('active');
        lastTime = performance.now();
        rafId = requestAnimationFrame(tick);
    }

    function stopSaver() {
        if (active) {
            active = false;
            if (rafId) {
                cancelAnimationFrame(rafId);
                rafId = null;
            }
            if (overlay) overlay.classList.remove('active');
        }
        resetTimer();
    }

    function resetTimer() {
        clearTimeout(idleTimer);
        idleTimer = setTimeout(startSaver, IDLE_MS);
    }

    ['mousemove', 'mousedown', 'keydown', 'wheel', 'touchstart', 'pointerdown'].forEach(evt => {
        window.addEventListener(evt, stopSaver, { passive: true });
    });
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            clearTimeout(idleTimer);
        } else {
            stopSaver();
        }
    });

    resetTimer();
})();
