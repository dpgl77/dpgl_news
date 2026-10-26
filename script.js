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