(() => {
    const table = document.querySelector('[data-order-selection]');
    if (!table) return;

    const checkboxes = [...table.querySelectorAll('[data-select-order]')];
    const selectAll = table.querySelector('[data-select-all]');
    const actions = document.querySelector('[data-selection-actions]');
    const count = document.querySelector('[data-selection-count]');
    const printSummary = document.querySelector('[data-print-summary]');
    const selectedRows = () => checkboxes.filter(input => input.checked).map(input => input.closest('tr'));

    function updateSelection() {
        const selected = selectedRows();
        actions.hidden = selected.length === 0;
        count.textContent = `${selected.length} selected`;
        printSummary.textContent = `${selected.length} selected order${selected.length === 1 ? '' : 's'}`;
        table.classList.toggle('has-selection', selected.length > 0);
        document.querySelector('.order-view-summary').classList.toggle('has-selection', selected.length > 0);
        printSummary.classList.toggle('has-selection', selected.length > 0);
        checkboxes.forEach(input => input.closest('tr').classList.toggle('is-selected', input.checked));
        selectAll.checked = checkboxes.length > 0 && selected.length === checkboxes.length;
        selectAll.indeterminate = selected.length > 0 && selected.length < checkboxes.length;
    }

    selectAll.addEventListener('change', () => {
        checkboxes.forEach(input => { input.checked = selectAll.checked; });
        updateSelection();
    });
    checkboxes.forEach(input => input.addEventListener('change', updateSelection));

    document.querySelector('[data-print-orders]').addEventListener('click', () => {
        if (selectedRows().length) window.print();
    });

    // Quote CSV cells and prevent user-entered names becoming spreadsheet formulas.
    function csvCell(value) {
        const safe = /^[=+\-@\t\r\n]/.test(value) ? `'${value}` : value;
        return `"${safe.replace(/"/g, '""')}"`;
    }

    document.querySelector('[data-download-orders]').addEventListener('click', () => {
        const rows = selectedRows();
        if (!rows.length) return;
        const cellValues = row => [...row.cells].slice(1).map(cell => cell.innerText.trim().replace(/\s+/g, ' '));
        const csv = [cellValues(table.tHead.rows[0]), ...rows.map(cellValues)]
            .map(values => values.map(csvCell).join(',')).join('\r\n');
        const url = URL.createObjectURL(new Blob(['\uFEFF', csv, '\r\n'], {type: 'text/csv;charset=utf-8;'}));
        const link = document.createElement('a');
        link.href = url;
        link.download = 'selected-orders.csv';
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    });

    window.addEventListener('pageshow', updateSelection);
    updateSelection();
})();
