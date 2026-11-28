// Safe storage: in-app browsers (Telegram, Instagram...), private mode and blocked cookies can THROW
// on any localStorage access. Before 28.11.2026 that stopped the whole script: no timer, no motto, empty first tab.
const dpglStore = (function () {
    let ls = null;
    try { ls = window.localStorage; ls.getItem('dpgl-probe'); } catch (e) { ls = null; }
    const mem = {};
    return {
        get(k) {
            try { if (ls) return ls.getItem(k); } catch (e) {}
            return Object.prototype.hasOwnProperty.call(mem, k) ? mem[k] : null;
        },
        set(k, v) {
            mem[k] = String(v);
            try { if (ls) ls.setItem(k, v); } catch (e) {}
        }
    };
})();

const REFRESH_INTERVAL = 30 * 60;
// Wall-clock deadline instead of "one tick = one second": phones freeze timers when the screen is off
// or the tab is in the background, a tick counter then stays frozen/stale.
let refreshDeadline = Date.now() + REFRESH_INTERVAL * 1000;

const IFRAME_WATCHDOG_MS = 15000;

function loadIframe(iframe) {
    if (!iframe) return;
    if (!iframe.getAttribute('src') && iframe.dataset.src) {
        iframe.removeAttribute('data-loaded');
        iframe.dataset.tries = '0';
        iframe.src = iframe.dataset.src;
        watchIframe(iframe);
    }
}

// If an embedded feed has not reported "load" within 15 s (flaky mobile network), retry once with a cache-buster.
function watchIframe(iframe) {
    window.setTimeout(() => {
        if (iframe.getAttribute('data-loaded') === '1') return;
        retryIframe(iframe);
    }, IFRAME_WATCHDOG_MS);
}

function retryIframe(iframe) {
    const tries = parseInt(iframe.dataset.tries || '0', 10);
    if (tries >= 2 || !iframe.getAttribute('src')) return;
    iframe.dataset.tries = String(tries + 1);
    iframe.removeAttribute('data-loaded');
    bustIframe(iframe);
    watchIframe(iframe);
}

function bustIframe(iframe) {
    // Reload without extra URL params: Inoreader shows unknown params (e.g. t=timestamp) in the feed title.
    const clean = (iframe.dataset.src || iframe.src || '').replace(/[&?]t=\d+/, '');
    if (!clean) return;
    iframe.src = 'about:blank';
    setTimeout(() => { iframe.src = clean; }, 60);
}

function renderCountdown(sec) {
    const el = document.getElementById('countdown');
    if (!el) return;
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    el.textContent = `${m < 10 ? '0' + m : m}:${s < 10 ? '0' + s : s}`;
}

function updateTimer() {
    let left = Math.ceil((refreshDeadline - Date.now()) / 1000);
    if (left > REFRESH_INTERVAL) {          // device clock moved backwards
        refreshDeadline = Date.now() + REFRESH_INTERVAL * 1000;
        left = REFRESH_INTERVAL;
    }
    if (left <= 0) {
        refreshAllIframes();
        refreshDeadline = Date.now() + REFRESH_INTERVAL * 1000;
        left = REFRESH_INTERVAL;
    }
    renderCountdown(left);
}

function refreshAllIframes() {
    document.querySelectorAll('iframe[src]').forEach(iframe => {
        iframe.removeAttribute('data-loaded');
        iframe.dataset.tries = '0';
        bustIframe(iframe);
        watchIframe(iframe);
    });
}

function openTab(evt, tabId) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));

    const tab = document.getElementById(tabId);
    tab.classList.add('active');
    const btn = (evt && (evt.currentTarget || evt.target)) || null;
    if (btn && btn.classList) btn.classList.add('active');

    const iframe = tab.querySelector('iframe');
    if (iframe) {
        loadIframe(iframe);
        // a tab whose feed never finished loading gets another try when opened
        if (iframe.getAttribute('src') && iframe.getAttribute('data-loaded') !== '1') retryIframe(iframe);
    }
}

// Initial load FIRST: nothing below may prevent the default tab and the timer from starting.
(function bootFeedAndTimer() {
    document.querySelectorAll('iframe').forEach(f => {
        f.addEventListener('load', () => { if (f.getAttribute('src')) f.setAttribute('data-loaded', '1'); });
    });
    const first = document.querySelector('.tab-content.active iframe');
    if (first && first.getAttribute('src')) {
        // src is already in the HTML (starts loading before JS): only watch it
        first.dataset.tries = '0';
        watchIframe(first);
    } else {
        loadIframe(first);
    }
    renderCountdown(REFRESH_INTERVAL);
    setInterval(updateTimer, 1000);
    const resync = () => {
        updateTimer();
        const act = document.querySelector('.tab-content.active iframe');
        if (act && !act.getAttribute('src')) loadIframe(act);
        else if (act && act.getAttribute('data-loaded') !== '1') retryIframe(act);
    };
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') resync(); });
    window.addEventListener('pageshow', resync);
    window.addEventListener('online', resync);
    window.addEventListener('focus', updateTimer);
})();

// Theme toggle
try {
    const themeBtn = document.getElementById('theme-toggle');
    if (themeBtn) {
        if (dpglStore.get('theme') === 'dark') {
            document.body.classList.add('dark');
            themeBtn.textContent = '☀️';
        }
        themeBtn.addEventListener('click', () => {
            document.body.classList.toggle('dark');
            const isDark = document.body.classList.contains('dark');
            themeBtn.textContent = isDark ? '☀️' : '🌙';
            dpglStore.set('theme', isDark ? 'dark' : 'light');
        });
    }
} catch (e) {}

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
try { (function initFloatingButtons() {
    const MIN_WIDTH = 700;
    const PAD = 6;
    const GAP = 6;
    const MIN_SPEED = 14; // px/sec
    const MAX_SPEED = 22; // px/sec

    const navs = Array.from(document.querySelectorAll('.tabs-nav'));
    if (!navs.length) return;

    const toggleBtn = document.getElementById('float-toggle');
    let enabled = dpglStore.get('dpgl-float-buttons') !== 'off';
    let active = false;
    let rafId = null;
    let lastTime = 0;
    let arenas = [];

    function updateToggleUi() {
        if (!toggleBtn) return;
        toggleBtn.textContent = enabled ? '⏸' : '▶';
        toggleBtn.title = enabled ? 'Остановить движение кнопок и девиза' : 'Включить движение кнопок и девиза';
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
            dpglStore.set('dpgl-float-buttons', enabled ? 'on' : 'off');
            updateToggleUi();
            document.dispatchEvent(new CustomEvent('dpgl-motion-toggle', { detail: { enabled } }));
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
})(); } catch (e) { if (window.console) console.warn("dpgl init failed", e); }

// Idle screensaver: dims screen and floats DPGL77 emblem while smoothly changing its size
try { (function initIdleScreensaver() {
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
        document.documentElement.classList.add('dpgl-screensaver-on');
        document.dispatchEvent(new CustomEvent('dpgl-screensaver', { detail: { active: true } }));
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
            document.documentElement.classList.remove('dpgl-screensaver-on');
            document.dispatchEvent(new CustomEvent('dpgl-screensaver', { detail: { active: false } }));
        }
        resetTimer();
    }

    // Idle = no page-level input for IDLE_MS. Timestamp + 1 s check instead of one long setTimeout:
    // mobile browsers delay/freeze long timers in the background.
    let lastActivity = Date.now();
    let lastActiveEl = null;

    function resetTimer() {
        lastActivity = Date.now();
    }

    function checkIdle() {
        // Touches inside a cross-origin iframe (the feeds) never reach this page, but focus moves into the iframe:
        // count that as activity once, then the normal 90 s countdown continues (never blocks forever).
        const ae = document.activeElement;
        if (ae && ae.tagName === 'IFRAME' && ae !== lastActiveEl) {
            lastActiveEl = ae;
            lastActivity = Date.now();
        } else if (!ae || ae.tagName !== 'IFRAME') {
            lastActiveEl = null;
        }
        if (!active && !document.hidden && Date.now() - lastActivity >= IDLE_MS) startSaver();
    }

    ['mousemove', 'mousedown', 'keydown', 'wheel', 'touchstart', 'touchmove', 'touchend', 'pointerdown', 'pointermove'].forEach(evt => {
        window.addEventListener(evt, stopSaver, { passive: true });
    });
    // scroll of the page or of the tab rows (scroll does not bubble: capture)
    window.addEventListener('scroll', resetTimer, { passive: true, capture: true });
    // focus moving into an iframe fires window blur
    window.addEventListener('blur', () => { window.setTimeout(checkIdle, 0); });
    window.addEventListener('pageshow', stopSaver);
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) stopSaver();
    });

    resetTimer();
    idleTimer = window.setInterval(checkIdle, 1000);
})(); } catch (e) { if (window.console) console.warn("dpgl init failed", e); }

// Animated motto: letter ignition, muzzle flashes, spark bursts (28.11.2026)
try { (function initMotto() {
    const h1 = document.querySelector('header.top h1.motto') || document.querySelector('header.top h1');
    if (!h1) return;

    const MOTTO = (h1.getAttribute('aria-label') || h1.textContent || '').replace(/\s+/g, ' ').trim() || 'Информация — тоже оружие';
    h1.classList.add('motto');
    if (!h1.getAttribute('aria-label')) h1.setAttribute('aria-label', MOTTO);

    // Reduced motion: the OS asks for it (iOS "Reduce Motion", Android "Remove animations"/battery saver).
    // Then no flashes/shake/sparks: only a calm static gradient with a soft glow (CSS .motto-calm).
    // Visitors can force the full animation once with ?motion=full (remembered).
    let osReduce = false;
    try { osReduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) {}
    try {
        const q = new URLSearchParams(window.location.search).get('motion');
        if (q === 'full') dpglStore.set('dpgl-motion', 'full');
        else if (q === 'auto') dpglStore.set('dpgl-motion', 'auto');
    } catch (e) {}
    const motionPref = dpglStore.get('dpgl-motion');
    const forceFull = motionPref === 'full';
    if (forceFull) document.documentElement.classList.add('dpgl-motion-full');
    const reduceMotion = osReduce && !forceFull;
    h1.classList.add('motto-ready');
    if (reduceMotion) {
        h1.classList.add('motto-static', 'motto-calm', 'is-settled');
        return;
    }

    const SPARK_COLORS = ['#fff8e0', '#ffe9a8', '#ffd27a', '#c69b4b', '#ffb347'];
    const BURST_COLORS = ['#ff7a2a', '#e85d2a', '#c41e12', '#ff9a3a', '#c69b4b', '#8b1a14'];
    const DEBRIS_COLORS = ['#c69b4b', '#a32a1c', '#e07a3d', '#8b1a14', '#f3d78a'];

    let userPaused = dpglStore.get('dpgl-float-buttons') === 'off';
    let letters = [];
    let words = [];
    let canvas = null;
    let ctx = null;
    let particles = [];
    let flashes = [];
    let rafId = null;
    let lastTime = 0;
    let pulseTimer = null;
    let introTimer = null;
    let introIndex = 0;
    let introDone = userPaused;
    let settled = userPaused;
    let running = false;
    let cssW = 0;
    let cssH = 0;

    function isMobile() {
        return window.matchMedia('(max-width: 640px)').matches || window.innerWidth < 700;
    }

    function isHeld() {
        if (userPaused) return true;
        if (document.hidden) return true;
        if (document.documentElement.classList.contains('dpgl-screensaver-on')) return true;
        const ss = document.getElementById('dpgl-screensaver');
        return !!(ss && ss.classList.contains('active'));
    }

    function wrapText() {
        const raw = h1.textContent.replace(/\s+/g, ' ').trim();
        h1.textContent = '';
        const stage = document.createElement('span');
        stage.className = 'motto-stage';
        raw.split(/(\s+)/).forEach(part => {
            if (!part) return;
            if (/^\s+$/.test(part)) {
                stage.appendChild(document.createTextNode(part));
                return;
            }
            const word = document.createElement('span');
            word.className = 'motto-word';
            word.setAttribute('data-word', part);
            const wordLetters = [];
            Array.from(part).forEach(ch => {
                const el = document.createElement('span');
                el.className = 'motto-letter';
                el.textContent = ch;
                word.appendChild(el);
                letters.push(el);
                wordLetters.push(el);
            });
            words.push({ el: word, letters: wordLetters });
            stage.appendChild(word);
        });
        canvas = document.createElement('canvas');
        canvas.className = 'motto-fx';
        canvas.setAttribute('aria-hidden', 'true');
        h1.appendChild(stage);
        h1.appendChild(canvas);
        ctx = canvas.getContext('2d');
        if (settled) {
            letters.forEach(el => el.classList.add('is-on'));
            h1.classList.add('is-settled');
        }
    }

    function sizeCanvas() {
        if (!canvas) return;
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        const rect = canvas.getBoundingClientRect();
        cssW = Math.max(1, Math.round(rect.width));
        cssH = Math.max(1, Math.round(rect.height));
        const w = Math.max(1, Math.round(cssW * dpr));
        const h = Math.max(1, Math.round(cssH * dpr));
        if (canvas.width !== w || canvas.height !== h) {
            canvas.width = w;
            canvas.height = h;
        }
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function localPoint(el) {
        const r = el.getBoundingClientRect();
        const c = canvas.getBoundingClientRect();
        return { x: r.left + r.width / 2 - c.left, y: r.top + r.height / 2 - c.top };
    }

    function pick(arr) {
        return arr[(Math.random() * arr.length) | 0];
    }

    function spawnBurst(x, y, power) {
        const mobile = isMobile();
        const base = mobile ? 14 : 32;
        const count = Math.max(8, Math.round(base * power));
        for (let i = 0; i < count; i++) {
            const debris = Math.random() < 0.28;
            const angle = Math.random() * Math.PI * 2;
            const speed = (debris ? 70 : 110) * power * (0.35 + Math.random());
            const upward = (mobile ? 18 : 32) * power;
            particles.push({
                x, y,
                vx: Math.cos(angle) * speed,
                vy: Math.sin(angle) * speed - upward,
                life: 1,
                decay: (debris ? 0.9 : 1.15) * (0.85 + Math.random() * 0.5),
                size: debris ? 2 + Math.random() * 2.6 : 1 + Math.random() * 2.1,
                color: debris ? pick(DEBRIS_COLORS) : (Math.random() < 0.55 ? pick(SPARK_COLORS) : pick(BURST_COLORS)),
                type: debris ? 'debris' : 'spark',
                rot: Math.random() * Math.PI,
                vr: (Math.random() - 0.5) * 10,
                g: debris ? 220 : 120,
                drag: debris ? 0.978 : 0.986
            });
        }
        flashes.push({
            x, y,
            r: 3,
            maxR: (mobile ? 24 : 42) * (0.7 + 0.5 * power),
            a: 0.95 * Math.min(1, 0.55 + power * 0.5),
            decay: 3.6
        });
    }

    function shake(strong) {
        h1.classList.remove('is-shake');
        void h1.offsetWidth;
        h1.style.animationDuration = strong ? '.32s' : '.22s';
        h1.classList.add('is-shake');
        window.setTimeout(() => {
            h1.classList.remove('is-shake');
            h1.style.animationDuration = '';
        }, 340);
    }

    function igniteLetter(el, power) {
        if (!el) return;
        el.classList.add('is-flash');
        el.classList.remove('is-on');
        const p = localPoint(el);
        spawnBurst(p.x, p.y, power);
        window.setTimeout(() => {
            el.classList.remove('is-flash');
            el.classList.add('is-on');
        }, 130);
    }

    function ensureLoop() {
        if (running || isHeld()) return;
        running = true;
        lastTime = performance.now();
        rafId = requestAnimationFrame(step);
    }

    function step(now) {
        if (isHeld()) {
            running = false;
            rafId = null;
            return;
        }
        // rAF timestamp can be slightly BEFORE performance.now() taken at start: negative dt used to give a negative
        // gradient radius -> exception -> loop never re-armed (no sparks on phones)
        const dt = Math.max(0, Math.min(0.05, (now - lastTime) / 1000 || 0.016));
        lastTime = now;

        for (let i = particles.length - 1; i >= 0; i--) {
            const p = particles[i];
            p.vx *= Math.pow(p.drag, dt * 60);
            p.vy = p.vy * Math.pow(p.drag, dt * 60) + p.g * dt;
            p.x += p.vx * dt;
            p.y += p.vy * dt;
            p.rot += p.vr * dt;
            p.life -= p.decay * dt;
            if (p.life <= 0) particles.splice(i, 1);
        }
        for (let i = flashes.length - 1; i >= 0; i--) {
            const f = flashes[i];
            f.r += (f.maxR - f.r) * Math.min(1, 10 * dt);
            f.a -= f.decay * dt;
            if (f.a <= 0) flashes.splice(i, 1);
        }

        try { draw(); } catch (e) { particles.length = 0; flashes.length = 0; }

        if (particles.length || flashes.length) {
            rafId = requestAnimationFrame(step);
        } else {
            running = false;
            rafId = null;
        }
    }

    function draw() {
        if (!ctx) return;
        ctx.clearRect(0, 0, cssW, cssH);
        for (const f of flashes) {
            const fr = Math.max(0.5, f.r);
            const g = ctx.createRadialGradient(f.x, f.y, 0, f.x, f.y, fr);
            g.addColorStop(0, `rgba(255, 248, 224, ${0.95 * f.a})`);
            g.addColorStop(0.35, `rgba(255, 210, 122, ${0.55 * f.a})`);
            g.addColorStop(0.7, `rgba(255, 122, 42, ${0.28 * f.a})`);
            g.addColorStop(1, 'rgba(196, 30, 18, 0)');
            ctx.fillStyle = g;
            ctx.beginPath();
            ctx.arc(f.x, f.y, fr, 0, Math.PI * 2);
            ctx.fill();
        }
        for (const p of particles) {
            ctx.save();
            ctx.translate(p.x, p.y);
            ctx.rotate(p.rot);
            ctx.globalAlpha = Math.max(0, p.life);
            ctx.fillStyle = p.color;
            if (p.type === 'debris') {
                ctx.fillRect(-p.size, -p.size * 0.35, p.size * 2.1, p.size * 0.7);
            } else {
                const len = Math.min(9, Math.hypot(p.vx, p.vy) * 0.04);
                ctx.beginPath();
                ctx.ellipse(0, 0, p.size + len, p.size * 0.55, Math.atan2(p.vy, p.vx), 0, Math.PI * 2);
                ctx.fill();
            }
            ctx.restore();
        }
        ctx.globalAlpha = 1;
    }

    function schedulePulse() {
        window.clearTimeout(pulseTimer);
        if (!introDone || isHeld()) return;
        const wait = isMobile() ? 5000 + Math.random() * 3000 : 8000 + Math.random() * 4000;
        pulseTimer = window.setTimeout(runPulse, wait);
    }

    function runPulse() {
        if (isHeld() || !introDone || !words.length) {
            schedulePulse();
            return;
        }
        sizeCanvas();
        const word = words[(Math.random() * words.length) | 0];
        const power = 0.55;
        word.letters.forEach((el, i) => {
            window.setTimeout(() => igniteLetter(el, power), i * 45);
        });
        const mid = word.letters[Math.floor(word.letters.length / 2)] || word.el;
        const p = localPoint(mid);
        spawnBurst(p.x, p.y, 0.7);
        shake(false);
        ensureLoop();
        schedulePulse();
    }

    function playIntro() {
        if (introDone || isHeld() || !letters.length) {
            if (!introDone && letters.length && !isHeld()) {
                // continue after a pause mid-intro
            } else {
                return;
            }
        }
        sizeCanvas();
        const stepMs = 78;
        const startDelay = introIndex === 0 ? 180 : 0;

        function next() {
            if (isHeld()) return;
            if (introIndex >= letters.length) {
                introDone = true;
                settled = true;
                h1.classList.add('is-settled');
                shake(true);
                schedulePulse();
                return;
            }
            const el = letters[introIndex];
            const isWordEnd = introIndex === letters.length - 1 || !el.parentElement || el.parentElement !== letters[introIndex + 1].parentElement;
            igniteLetter(el, isWordEnd ? 1.05 : 0.85);
            if (isWordEnd) shake(introIndex === letters.length - 1);
            introIndex += 1;
            introTimer = window.setTimeout(next, stepMs);
            ensureLoop();
        }

        introTimer = window.setTimeout(next, startDelay);
    }

    function onPauseChange() {
        if (isHeld()) {
            window.clearTimeout(introTimer);
            window.clearTimeout(pulseTimer);
            pulseTimer = null;
            introTimer = null;
            if (rafId) {
                cancelAnimationFrame(rafId);
                rafId = null;
            }
            running = false;
            return;
        }
        sizeCanvas();
        if (!introDone) {
            playIntro();
            ensureLoop();
            return;
        }
        ensureLoop();
        schedulePulse();
    }

    wrapText();
    sizeCanvas();

    let resizeTimer = null;
    window.addEventListener('resize', () => {
        window.clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(sizeCanvas, 120);
    });
    if (window.ResizeObserver && canvas) {
        new ResizeObserver(() => sizeCanvas()).observe(h1);
    }

    document.addEventListener('dpgl-motion-toggle', ev => {
        userPaused = !(ev && ev.detail && ev.detail.enabled);
        onPauseChange();
    });
    document.addEventListener('dpgl-screensaver', onPauseChange);
    let hiddenAt = 0;
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) hiddenAt = Date.now();
        onPauseChange();
        // coming back to the phone after a while: replay a pulse so the motto visibly "wakes up"
        if (!document.hidden && introDone && hiddenAt && Date.now() - hiddenAt > 15000) {
            hiddenAt = 0;
            window.setTimeout(runPulse, 500);
        }
    });
    // tap / click on the motto fires a burst (touch screens have no hover)
    let lastTap = 0;
    h1.addEventListener('pointerup', () => {
        if (!introDone || isHeld() || Date.now() - lastTap < 1200) return;
        lastTap = Date.now();
        runPulse();
    });

    if (!userPaused) playIntro();
    else {
        letters.forEach(el => el.classList.add('is-on'));
        h1.classList.add('is-settled');
    }

    window.__dpglMotto = {
        get introDone() { return introDone; },
        get paused() { return isHeld(); },
        get particleCount() { return particles.length; }
    };
})(); } catch (e) { if (window.console) console.warn("dpgl init failed", e); }
