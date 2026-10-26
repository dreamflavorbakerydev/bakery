(() => {
    const add = document.getElementById('add-customer-product');
    if (!add) return;
    add.addEventListener('click', () => {
        const total = document.getElementById('id_products-TOTAL_FORMS');
        const index = Number(total.value);
        if (index >= 2000) return;
        const template = document.getElementById('empty-customer-product');
        const holder = document.getElementById('customer-product-forms');
        holder.insertAdjacentHTML('beforeend', template.innerHTML.replaceAll('__prefix__', String(index)));
        total.value = String(index + 1);
        holder.lastElementChild.querySelector('select')?.focus();
    });
})();
