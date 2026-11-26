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

// Slowly drifting, collision-bouncing buttons in .tabs-nav arenas
(function initFloatingButtons() {
    const MIN_WIDTH = 700;
    const PAD = 6;
    const GAP = 5;
    const MIN_SPEED = 14; // px/sec (slow and smooth)
    const MAX_SPEED = 22; // px/sec

    const navs = Array.from(document.querySelectorAll('.tabs-nav'));
    if (!navs.length) return;

    const toggleBtn = document.getElementById('float-toggle');
    const reducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let enabled = localStorage.getItem('dpgl-float-buttons') !== 'off' && !reducedMotion;
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
            arena.items.forEach(item => {
                item.el.classList.remove('floating-btn');
                item.el.style.transform = '';
                item.el.style.width = '';
            });
        });
        arenas = [];
        active = false;
    }

    function buildArena(nav) {
        const els = Array.from(nav.querySelectorAll('.tab-btn'));
        if (!els.length) return null;

        // Measure natural widths/heights before switching to absolute positioning
        const navRect = nav.getBoundingClientRect();
        const rects = els.map(el => el.getBoundingClientRect());
        nav.classList.add('floating-arena');
        const W = nav.clientWidth;
        const H = nav.clientHeight;

        const items = [];
        els.forEach((el, idx) => {
            const w = Math.ceil(rects[idx].width);
            const h = Math.ceil(rects[idx].height);
            el.classList.add('floating-btn');

            // Initial non-overlapping placement inside arena
            let x = Math.max(PAD, Math.min(W - w - PAD, rects[idx].left - navRect.left));
            let y = PAD + ((idx % 2) * Math.max(0, (H - h - PAD * 2) * 0.72));
            y = Math.max(PAD, Math.min(H - h - PAD, y));

            const angle = (Math.random() * Math.PI * 2);
            const speed = MIN_SPEED + Math.random() * (MAX_SPEED - MIN_SPEED);
            const item = {
                el, w, h, x, y,
                vx: Math.cos(angle) * speed,
                vy: Math.sin(angle) * speed,
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

        // Resolve any initial overlaps gently
        for (let pass = 0; pass < 12; pass++) {
            for (let i = 0; i < items.length; i++) {
                for (let j = i + 1; j < items.length; j++) {
                    const a = items[i], b = items[j];
                    const ox = (a.w + b.w) / 2 + GAP - Math.abs((a.x + a.w / 2) - (b.x + b.w / 2));
                    const oy = (a.h + b.h) / 2 + GAP - Math.abs((a.y + a.h / 2) - (b.y + b.h / 2));
                    if (ox > 0 && oy > 0) {
                        if (ox < oy) {
                            const dir = (a.x + a.w / 2) < (b.x + b.w / 2) ? -1 : 1;
                            a.x += dir * ox * 0.5;
                            b.x -= dir * ox * 0.5;
                        } else {
                            const dir = (a.y + a.h / 2) < (b.y + b.h / 2) ? -1 : 1;
                            a.y += dir * oy * 0.5;
                            b.y -= dir * oy * 0.5;
                        }
                        a.x = Math.max(PAD, Math.min(W - a.w - PAD, a.x));
                        a.y = Math.max(PAD, Math.min(H - a.h - PAD, a.y));
                        b.x = Math.max(PAD, Math.min(W - b.w - PAD, b.x));
                        b.y = Math.max(PAD, Math.min(H - b.h - PAD, b.y));
                    }
                }
            }
        }

        items.forEach(item => {
            item.el.style.transform = `translate3d(${item.x.toFixed(2)}px, ${item.y.toFixed(2)}px, 0)`;
        });

        return { nav, items };
    }

    function step(now) {
        if (!active) return;
        const dt = Math.min(0.05, (now - lastTime) / 1000 || 0.016);
        lastTime = now;

        for (const arena of arenas) {
            const W = arena.nav.clientWidth;
            const H = arena.nav.clientHeight;
            const items = arena.items;

            // Integrate positions & bounce off walls
            for (const it of items) {
                if (it.paused) continue;
                it.x += it.vx * dt;
                it.y += it.vy * dt;

                if (it.x <= PAD) {
                    it.x = PAD;
                    it.vx = Math.abs(it.vx);
                } else if (it.x + it.w >= W - PAD) {
                    it.x = Math.max(PAD, W - PAD - it.w);
                    it.vx = -Math.abs(it.vx);
                }

                if (it.y <= PAD) {
                    it.y = PAD;
                    it.vy = Math.abs(it.vy);
                } else if (it.y + it.h >= H - PAD) {
                    it.y = Math.max(PAD, H - PAD - it.h);
                    it.vy = -Math.abs(it.vy);
                }
            }

            // Pairwise AABB collisions
            for (let i = 0; i < items.length; i++) {
                for (let j = i + 1; j < items.length; j++) {
                    const a = items[i], b = items[j];
                    const acx = a.x + a.w / 2, acy = a.y + a.h / 2;
                    const bcx = b.x + b.w / 2, bcy = b.y + b.h / 2;
                    const ox = (a.w + b.w) / 2 + GAP - Math.abs(acx - bcx);
                    const oy = (a.h + b.h) / 2 + GAP - Math.abs(acy - bcy);

                    if (ox > 0 && oy > 0) {
                        if (ox < oy) {
                            const sign = acx < bcx ? -1 : 1;
                            if (a.paused && !b.paused) {
                                b.x -= sign * ox;
                                b.vx = -sign * Math.abs(b.vx);
                            } else if (b.paused && !a.paused) {
                                a.x += sign * ox;
                                a.vx = sign * Math.abs(a.vx);
                            } else if (!a.paused && !b.paused) {
                                a.x += sign * ox * 0.5;
                                b.x -= sign * ox * 0.5;
                                const tmp = a.vx;
                                a.vx = b.vx;
                                b.vx = tmp;
                                if ((a.vx - b.vx) * sign < 0) {
                                    a.vx = sign * Math.abs(a.vx);
                                    b.vx = -sign * Math.abs(b.vx);
                                }
                            }
                        } else {
                            const sign = acy < bcy ? -1 : 1;
                            if (a.paused && !b.paused) {
                                b.y -= sign * oy;
                                b.vy = -sign * Math.abs(b.vy);
                            } else if (b.paused && !a.paused) {
                                a.y += sign * oy;
                                a.vy = sign * Math.abs(a.vy);
                            } else if (!a.paused && !b.paused) {
                                a.y += sign * oy * 0.5;
                                b.y -= sign * oy * 0.5;
                                const tmp = a.vy;
                                a.vy = b.vy;
                                b.vy = tmp;
                                if ((a.vy - b.vy) * sign < 0) {
                                    a.vy = sign * Math.abs(a.vy);
                                    b.vy = -sign * Math.abs(b.vy);
                                }
                            }
                        }
                    }
                }
            }

            // Apply transforms
            for (const it of items) {
                it.el.style.transform = `translate3d(${it.x.toFixed(2)}px, ${it.y.toFixed(2)}px, 0)`;
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

    // Start after layout settles
    if (document.readyState === 'complete') start();
    else window.addEventListener('load', start);
})();
