(() => {
    const badge = document.querySelector('[data-new-orders-url]');
    if (!badge) return;
    let checking = false;
    async function refresh() {
        if (document.hidden || checking) return;
        checking = true;
        try {
            const response = await fetch(badge.dataset.newOrdersUrl, {
                credentials: 'same-origin', cache: 'no-store',
                signal: AbortSignal.timeout(10000),
            });
            if (!response.ok) return;
            const result = await response.json();
            if (typeof result.has_new_orders === 'boolean') badge.hidden = !result.has_new_orders;
        } catch (_) {
            // Keep the current indicator when a request cannot complete.
        } finally {
            checking = false;
        }
    }
    setInterval(refresh, 30000);
    document.addEventListener('visibilitychange', refresh);
    window.addEventListener('pageshow', event => { if (event.persisted) refresh(); });
})();
