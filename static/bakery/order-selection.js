(() => {
    const table = document.querySelector('[data-order-selection]');
    if (!table) return;
    const checkboxes = [...table.querySelectorAll('[data-select-order]')];
    const selectAll = table.querySelector('[data-select-all]');
    const actions = document.querySelector('[data-selection-actions]');
    const selected = () => checkboxes.filter(input => input.checked);

    function updateSelection() {
        const count = selected().length;
        actions.hidden = count === 0;
        document.querySelector('[data-selection-count]').textContent = `${count} selected`;
        checkboxes.forEach(input => input.closest('tr').classList.toggle('is-selected', input.checked));
        selectAll.checked = checkboxes.length > 0 && count === checkboxes.length;
        selectAll.indeterminate = count > 0 && count < checkboxes.length;
    }
    selectAll.addEventListener('change', () => {
        checkboxes.forEach(input => { input.checked = selectAll.checked; });
        updateSelection();
    });
    checkboxes.forEach(input => input.addEventListener('change', updateSelection));

    function documentUrl(action) {
        const url = new URL(table.dataset.documentsUrl, window.location.href);
        selected().forEach(input => url.searchParams.append('order', input.value));
        url.searchParams.set('action', action);
        return url.href;
    }
    document.querySelector('[data-print-orders]').addEventListener('click', () => {
        if (selected().length) window.open(documentUrl('print'), '_blank', 'noopener');
    });
    document.querySelector('[data-download-orders]').addEventListener('click', () => {
        if (selected().length) window.location.assign(documentUrl('download'));
    });
    window.addEventListener('pageshow', updateSelection);
    updateSelection();
})();
