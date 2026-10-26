(() => {
    const form = document.getElementById('order-form');
    if (!form) return;
    const rows = [...form.querySelectorAll('.order-product')];
    rows.forEach(row => {
        const name = row.querySelector('.order-product-name');
        const details = row.querySelector('.order-product-details');
        if (!name || !details) return;
        name.addEventListener('click', () => {
            details.hidden = !details.hidden;
            name.setAttribute('aria-expanded', String(!details.hidden));
        });
    });
    const date = document.getElementById('id_delivery_date');
    const search = document.getElementById('product-search');
    const category = document.getElementById('product-category');
    const selectedOnly = document.getElementById('selected-only');
    const review = document.getElementById('review-order');
    const status = document.getElementById('order-status');
    const totalOutput = document.getElementById('order-total');
    const retry = document.getElementById('retry-prices');
    let pricesReady = true;
    let loading = false;
    let revision = 0;
    let controller;

    function money(cents) {
        const dollars = (cents / 100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
        return `$${dollars}.${(cents % 100n).toString().padStart(2, '0')}`;
    }

    function filterProducts() {
        const query = search.value.trim().toLocaleLowerCase();
        let visible = 0;
        rows.forEach(row => {
            const selected = Number(row.querySelector('.quantity-input').value) > 0;
            row.hidden = !row.dataset.search.toLocaleLowerCase().includes(query)
                || (category.value && row.dataset.category !== category.value)
                || (selectedOnly.checked && !selected);
            if (!row.hidden) visible += 1;
        });
        document.getElementById('product-count').textContent = `Showing ${visible} of ${rows.length} products`;
        document.getElementById('product-empty').hidden = visible !== 0;
    }

    function updateOrder() {
        let total = 0n;
        let selected = 0;
        let quantities = 0;
        let invalid = false;
        let missingPrice = false;
        rows.forEach(row => {
            const input = row.querySelector('.quantity-input');
            const quantity = input.value === '' ? 0 : Number(input.value);
            const valid = input.validity.valid && Number.isInteger(quantity) && quantity >= 0 && quantity <= 100000;
            const output = row.querySelector('[data-line-total]');
            if (!valid) {
                invalid = true;
                output.textContent = '—';
                return;
            }
            if (quantity > 0) {
                selected += 1;
                quantities += quantity;
            }
            if (!pricesReady) {
                output.textContent = '—';
            } else if (row.dataset.unitCents === '' && quantity > 0) {
                missingPrice = true;
                output.textContent = 'Price needed';
            } else {
                const lineTotal = BigInt(row.dataset.unitCents || '0') * BigInt(quantity);
                total += lineTotal;
                output.textContent = money(lineTotal);
            }
        });
        const tooLarge = total > 99999999999999n;
        totalOutput.textContent = !pricesReady || missingPrice || invalid ? '—' : money(total);
        document.getElementById('selection-count').textContent = `${selected} product${selected === 1 ? '' : 's'} selected · ${quantities} selling units`;
        review.disabled = form.dataset.canOrder !== 'true' || !pricesReady || !selected || invalid || missingPrice || tooLarge;
        if (loading) status.textContent = 'Updating prices for your delivery date…';
        else if (!pricesReady) status.textContent = 'Prices could not be updated. Retry before reviewing your order.';
        else if (form.dataset.hasDates !== 'true') status.textContent = 'Delivery dates need to be configured before you can order.';
        else if (form.dataset.canOrder !== 'true') status.textContent = 'Your pricing needs bakery review before you can order.';
        else if (invalid) status.textContent = 'Enter whole quantities from 0 to 100,000.';
        else if (missingPrice) status.textContent = 'A selected product has no price for this date. Set its quantity to 0 or choose another date.';
        else if (tooLarge) status.textContent = 'This order is too large. Reduce the quantities or contact the bakery.';
        else if (!selected) status.textContent = 'Enter quantities to start your order.';
        else status.textContent = 'Your total includes all selected products, including those hidden by search.';
        filterProducts();
    }

    async function refreshPrices() {
        if (!date?.value) return;
        const currentRevision = ++revision;
        controller?.abort();
        controller = new AbortController();
        pricesReady = false;
        loading = true;
        retry.hidden = true;
        form.setAttribute('aria-busy', 'true');
        rows.forEach(row => row.querySelector('[data-price]').textContent = 'Updating…');
        updateOrder();
        try {
            const url = new URL(form.dataset.pricesUrl, window.location.origin);
            url.searchParams.set('location', form.elements.location.value);
            url.searchParams.set('date', date.value);
            const response = await fetch(url, {credentials: 'same-origin', signal: controller.signal,
                headers: {'Accept': 'application/json'}});
            if (!response.ok) throw new Error('Prices unavailable');
            const data = await response.json();
            if (currentRevision !== revision) return;
            rows.forEach(row => {
                const cents = data.prices[row.dataset.productId];
                row.dataset.unitCents = cents == null ? '' : cents;
                row.querySelector('[data-price]').textContent = cents == null ? 'Price unavailable' : money(BigInt(cents));
            });
            document.getElementById('pricing-date').textContent = new Date(data.date + 'T12:00:00').toLocaleDateString('en-US',
                {month: 'short', day: 'numeric', year: 'numeric'});
            pricesReady = true;
        } catch (error) {
            if (currentRevision !== revision) return;
            rows.forEach(row => row.querySelector('[data-price]').textContent = 'Price unavailable');
            retry.hidden = false;
        } finally {
            if (currentRevision === revision) {
                loading = false;
                form.removeAttribute('aria-busy');
                updateOrder();
            }
        }
    }

    form.querySelectorAll('[data-step]').forEach(button => button.addEventListener('click', () => {
        const input = button.parentElement.querySelector('.quantity-input');
        input.value = Math.min(100000, Math.max(0, (parseInt(input.value, 10) || 0) + Number(button.dataset.step)));
        input.dispatchEvent(new Event('input', {bubbles: true}));
    }));
    form.querySelectorAll('.quantity-input').forEach(input => input.addEventListener('input', updateOrder));
    search.addEventListener('input', filterProducts);
    category.addEventListener('change', filterProducts);
    selectedOnly.addEventListener('change', filterProducts);
    date?.addEventListener('change', refreshPrices);
    retry.addEventListener('click', refreshPrices);
    form.addEventListener('submit', event => {
        updateOrder();
        if (review.disabled) event.preventDefault();
    });
    updateOrder();
})();
