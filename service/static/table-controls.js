/* Sorting and pagination for existing HTML tables, including async refreshes.
   The timing workspace owns its server-side table and is excluded here. */
(() => {
    'use strict';
    const seen = new WeakSet();
    const zh = document.documentElement.lang.startsWith('zh');
    const labels = zh ? {prev: '上一页', next: '下一页', jump: '跳转到第几页', go: '跳转'}
        : {prev: 'Previous', next: 'Next', jump: 'Go to page', go: 'Go'};
    function element(tag, text) {
        const result = document.createElement(tag);
        if (text !== undefined) result.textContent = text;
        return result;
    }
    function sortValue(cell) {
        const raw = (cell?.dataset.sortValue ?? cell?.dataset.utcTime ?? cell?.textContent ?? '').trim();
        if (!raw || ['—', '-', 'N/A'].includes(raw)) return null;
        if (/^\d{4}-\d{2}-\d{2}/.test(raw)) {
            const at = Date.parse(raw);
            if (Number.isFinite(at)) return at;
        }
        const match = raw.replaceAll(',', '').match(/^(-?\d+(?:\.\d+)?)\s*([KMB%]?)$/i);
        if (match) return Number(match[1]) * ({K: 1e3, M: 1e6, B: 1e9}[match[2].toUpperCase()] || 1);
        return raw;
    }
    function enhance(table) {
        if (seen.has(table) || table.hasAttribute('data-server-table') || !table.tHead || !table.tBodies[0]) return;
        seen.add(table);
        const body = table.tBodies[0];
        const headers = [...table.tHead.rows[0].cells];
        if (!headers.length) return;
        let rows = [...body.rows], page = 1, sort = -1, direction = 1;
        const size = 15;
        const wrapper = element('div'); wrapper.className = 'tl-table-wrap';
        table.before(wrapper); wrapper.append(table);
        const controls = element('nav'); controls.className = 'tl-table-controls';
        controls.setAttribute('aria-label', labels.jump);
        const info = element('span'); info.setAttribute('aria-live', 'polite');
        const previous = element('button', labels.prev), next = element('button', labels.next);
        previous.type = next.type = 'button';
        const jumpForm = element('form');
        const jumpLabel = element('label', `${labels.jump} `);
        const input = element('input'); input.type = 'number'; input.min = '1'; input.required = true;
        input.setAttribute('aria-label', labels.jump);
        jumpLabel.append(input);
        const go = element('button', labels.go); go.type = 'submit';
        jumpForm.append(jumpLabel, go);
        controls.append(info, previous, next, jumpForm); wrapper.after(controls);
        const buttons = headers.map((th, index) => {
            const button = element('button'); button.type = 'button'; button.className = 'tl-table-sort';
            const label = th.textContent.trim();
            button.textContent = `${label} ↕`;
            button.addEventListener('click', () => {
                direction = sort === index ? -direction : 1; sort = index; page = 1; render();
            });
            th.replaceChildren(button); th.scope = 'col';
            return {button, label};
        });
        const observer = new MutationObserver(changes => {
            if (changes.some(change => change.target === body)) rows = [...body.rows];
            render();
        });
        function render() {
            observer.disconnect();
            const placeholder = rows.length === 0 || (rows.length === 1 && rows[0].cells.length === 1 && rows[0].cells[0].colSpan > 1);
            const total = placeholder ? 0 : rows.length;
            const pages = Math.max(1, Math.ceil(total / size));
            page = Math.min(pages, Math.max(1, page));
            const ordered = [...rows];
            if (sort >= 0 && !placeholder) ordered.sort((a, b) => {
                const left = sortValue(a.cells[sort]), right = sortValue(b.cells[sort]);
                if (left === null || right === null) return left === right ? 0 : left === null ? 1 : -1;
                if (typeof left === 'number' && typeof right === 'number') return direction * (left - right);
                return direction * String(left).localeCompare(String(right), document.documentElement.lang, {numeric: true});
            });
            body.replaceChildren(...ordered.slice((page - 1) * size, page * size));
            buttons.forEach(({button, label}, index) => {
                headers[index].setAttribute('aria-sort', sort === index ? direction === 1 ? 'ascending' : 'descending' : 'none');
                button.textContent = `${label} ${sort === index ? direction === 1 ? '↑' : '↓' : '↕'}`;
            });
            info.textContent = zh ? `第 ${page} / ${pages} 页 · 共 ${total} 条` : `Page ${page} / ${pages} · ${total} rows`;
            previous.disabled = page <= 1; next.disabled = page >= pages;
            input.value = page; input.max = pages;
            observer.observe(table, {childList: true, subtree: true});
        }
        previous.addEventListener('click', () => { page -= 1; render(); });
        next.addEventListener('click', () => { page += 1; render(); });
        jumpForm.addEventListener('submit', event => { event.preventDefault(); page = Number(input.value); render(); });
        render();
    }
    document.querySelectorAll('table').forEach(enhance);
    new MutationObserver(changes => {
        for (const change of changes) for (const added of change.addedNodes) {
            if (added.nodeType !== Node.ELEMENT_NODE) continue;
            if (added.matches('table')) enhance(added);
            added.querySelectorAll('table').forEach(enhance);
        }
    }).observe(document.body, {childList: true, subtree: true});
})();
