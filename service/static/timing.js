(() => {
    'use strict';
    const config = JSON.parse(document.getElementById('timing-config').textContent);
    const text = (key, values = {}) => Object.entries(values).reduce(
        (result, [name, value]) => result.replaceAll(`{${name}}`, value), config.texts[key] || key);
    const $ = (selector) => document.querySelector(selector);
    const form = $('#timing-filters');
    const number = new Intl.NumberFormat(config.locale);
    const filters = ['window', 'project_name', 'session_id', 'agent_type', 'model_name', 'agent_version', 'user_id', 'from', 'to'];
    const columns = {
        projects: ['project_name', 'session_count', 'turn_count', 'agent_ms', 'active_wall_ms', 'parallelism', 'duration.p50_ms', 'duration.p95_ms'],
        sessions: ['session_id', 'project_name', 'agent_type', 'turn_count', 'agent_ms', 'gap_ms', 'duration.p50_ms', 'duration.p95_ms', 'finished_at'],
        tools: ['tool', 'kind', 'call_count', 'exclusive_ms', 'share', 'duration.average_ms', 'duration.p95_ms'],
        turns: ['turn_id', 'project_name', 'session_id', 'agent_type', 'model_name', 'duration_ms', 'time_to_first_token_ms', 'timing_source', 'finished_at'],
    };
    let state, controller, table;

    function node(tag, value, className) {
        const element = document.createElement(tag);
        if (value !== undefined) element.textContent = value;
        if (className) element.className = className;
        return element;
    }
    function duration(value) {
        if (value === null || value === undefined) return '—';
        if (value < 1000) return `${Math.round(value)} ms`;
        if (value < 60000) return `${+(value / 1000).toFixed(1)} s`;
        if (value < 3600000) return `${+(value / 60000).toFixed(1)} min`;
        return `${+(value / 3600000).toFixed(2)} h`;
    }
    function readLocation() {
        const params = new URLSearchParams(location.search);
        state = Object.fromEntries(filters.filter(k => params.has(k)).map(k => [k, params.get(k)]));
        if (!['today', 'week', 'month', 'quarter', 'all', 'custom'].includes(state.window)) state.window = 'week';
        state.view = Object.hasOwn(columns, params.get('view')) ? params.get('view') : 'projects';
        state.page = Math.max(1, Number.parseInt(params.get('page'), 10) || 1);
        state.sort = columns[state.view].includes(params.get('sort')) ? params.get('sort') : defaultSort(state.view);
        state.order = params.get('order') === 'asc' ? 'asc' : 'desc';
        for (const field of filters) {
            if (form.elements[field]) form.elements[field].value = state[field] || '';
        }
        showDates();
    }
    function defaultSort(view) { return view === 'tools' ? 'exclusive_ms' : view === 'turns' ? 'duration_ms' : 'agent_ms'; }
    function showDates() {
        const custom = form.elements.window.value === 'custom';
        document.querySelectorAll('.timing-custom').forEach(el => { el.hidden = !custom; el.querySelector('input').required = custom; });
    }
    function saveLocation(push = true) {
        const params = new URLSearchParams();
        for (const [key, value] of Object.entries(state)) if (value) params.set(key, value);
        const url = `${location.pathname}?${params}`;
        if (url !== location.pathname + location.search) history[push ? 'pushState' : 'replaceState']({}, '', url);
        document.querySelectorAll('[data-locale-switcher] input[name=next]').forEach(el => { el.value = url; });
    }
    function query(view) {
        const params = new URLSearchParams();
        for (const key of filters) if (state[key] && !['from', 'to'].includes(key)) params.set(key, state[key]);
        if (state.window === 'custom') {
            if (!state.from || !state.to || state.to < state.from) throw new Error('Invalid date range');
            params.set('from', new Date(`${state.from}T00:00:00Z`).toISOString());
            params.set('to', new Date(Date.parse(`${state.to}T00:00:00Z`) + 86400000).toISOString());
        }
        params.set('view', view);
        for (const key of ['page', 'sort', 'order']) params.set(key, state[key]);
        return `${config.endpoint}?${params}`;
    }
    async function fetchJSON(url, signal) {
        const response = await fetch(url, {signal});
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const result = await response.json();
        if (!result.success) throw new Error(result.error);
        return result;
    }
    function renderSummary(result) {
        const s = result.summary;
        const scope = [state.user_id ? text('member_scope', {id: state.user_id}) : '',
            state.agent_version ? text('version_scope', {version: state.agent_version}) : ''].filter(Boolean);
        $('#timing-scope-note').textContent = scope.join(' · ');
        $('#timing-scope-note').hidden = scope.length === 0;
        $('#timing-empty').hidden = s.turn_count > 0;
        const metrics = [
            ['agent_ms', duration(s.agent_ms), `${number.format(s.turn_count)} ${text('turn_count')}`],
            ['active_wall_ms', duration(s.active_wall_ms), `${number.format(s.session_count)} ${text('session_count')}`],
            ['p50', duration(s.duration.p50_ms), `${number.format(s.duration.samples)} ${text('samples')}`],
            ['p95', duration(s.duration.p95_ms), `${number.format(s.duration.samples)} ${text('samples')}`],
            ['parallelism', s.parallelism === null ? '—' : `${s.parallelism.toFixed(2)}×`, ''],
            ['ttft', duration(s.ttft.p50_ms), `${number.format(s.ttft.samples)} ${text('samples')}`],
        ];
        const metricNodes = metrics.map(([key, value, detail]) => {
            const item = node('div');
            item.append(node('div', text(key), 'timing-metric-label'), node('div', value, 'timing-metric-value'), node('div', detail, 'timing-metric-detail'));
            return item;
        });
        $('#timing-metrics').replaceChildren(...metricNodes);
        $('#timing-coverage').textContent = text('coverage_note', {measured: s.session_count, observed: s.observed_session_count, missing: s.unmeasured_session_count});
        $('#timing-tools-coverage').textContent = text('tools_coverage', {count: s.tool_measured_turns, total: s.turn_count});
        renderHistogram(result.histogram);
        const byKind = new Map();
        for (const row of s.breakdown) {
            const key = `${row.family}:${row.kind}`;
            if (!byKind.has(key)) byKind.set(key, {...row, duration_ms: 0, share: 0});
            const total = byKind.get(key);
            total.duration_ms += row.duration_ms;
            total.share += row.share;
        }
        const slices = [...byKind.values()].sort((a, b) => b.duration_ms - a.duration_ms);
        $('#timing-breakdown').replaceChildren(...slices.map(row => {
            const item = node('div', undefined, 'timing-breakdown-row');
            if (row.kind === 'unobserved') item.dataset.unknown = 'true';
            item.append(node('span', text(row.kind)), node('span', `${duration(row.duration_ms)} · ${(row.share * 100).toFixed(1)}%`));
            const track = node('div', undefined, 'timing-track');
            const fill = node('span');
            fill.style.width = `${row.share * 100}%`;
            track.append(fill); item.append(track);
            return item;
        }));
        if (!slices.length) $('#timing-breakdown').append(node('p', text('empty'), 'muted'));
        const largest = slices.find(row => row.kind !== 'unobserved' && row.duration_ms > 0);
        const unknown = slices.find(row => row.kind === 'unobserved');
        $('#timing-insight').textContent = largest
            ? `${text('bottleneck')}: ${text(largest.kind)} · ${duration(largest.duration_ms)} (${(largest.share * 100).toFixed(1)}%). ${unknown && unknown.share > .25 ? text('unobserved_note') : ''}`
            : text('unobserved_note');
        if (state.view === 'projects' && !state.project_name) {
            $('#timing-projects').replaceChildren(...(result.table?.rows || []).map(r => {
                const option = node('option'); option.value = r.project_name; return option;
            }));
        }
    }
    function renderHistogram(buckets) {
        const maximum = Math.max(1, ...buckets.map(b => b.count));
        const short = value => value < 60000 ? `${value / 1000}s` : `${value / 60000}m`;
        const binNodes = buckets.map(b => {
            const label = b.upper_ms === null ? `≥${short(b.lower_ms)}` : b.lower_ms === 0 ? `<${short(b.upper_ms)}` : `${short(b.lower_ms)}–${short(b.upper_ms)}`;
            const item = node('div', undefined, 'timing-bin');
            item.title = `${label}: ${number.format(b.count)}`;
            const bar = node('div', undefined, 'timing-bin-bar');
            bar.style.height = `${b.count / maximum * 130}px`;
            item.append(node('span', number.format(b.count), 'timing-bin-count'), bar, node('span', label, 'timing-bin-label'));
            return item;
        });
        $('#timing-histogram').replaceChildren(...binNodes);
        $('#timing-histogram').setAttribute('aria-label', `${text('distribution')}: ${buckets.map((b, i) => `${binNodes[i].title}`).join('; ')}`);
    }
    function valueFor(row, key) { return key.split('.').reduce((value, part) => value?.[part], row); }
    function formatCell(row, key) {
        const value = valueFor(row, key);
        if (value === null || value === undefined) return '—';
        if (key.endsWith('_ms')) return duration(value);
        if (key === 'parallelism') return `${value.toFixed(2)}×`;
        if (key === 'share') return `${(value * 100).toFixed(1)}%`;
        if (key === 'kind' || key === 'timing_source') return text(value);
        if (key === 'finished_at') return value.slice(0, 19).replace('T', ' ');
        return typeof value === 'number' ? number.format(value) : value;
    }
    function drillState(key, value, row) {
        const next = {...state, [key]: value, page: 1, order: 'desc'};
        if (key === 'project_name') { delete next.session_id; next.view = 'sessions'; }
        if (key === 'session_id') {
            next.view = 'turns'; next.project_name = row.project_name; next.agent_type = row.agent_type;
            next.user_id = row.user_id;
        }
        next.sort = defaultSort(next.view);
        return next;
    }
    function drill(key, value, row) {
        state = drillState(key, value, row);
        for (const field of filters) if (form.elements[field]) form.elements[field].value = state[field] || '';
        saveLocation(); refresh();
    }
    function renderTable(result) {
        table = result.table;
        state.page = table.page; state.sort = table.sort;
        saveLocation(false);
        const header = node('tr');
        for (const key of columns[state.view]) {
            const th = node('th');
            th.scope = 'col';
            const selected = key === table.sort;
            th.setAttribute('aria-sort', selected ? table.order === 'asc' ? 'ascending' : 'descending' : 'none');
            const button = node('button', `${text(key)} ${selected ? (table.order === 'asc' ? '↑' : '↓') : '↕'}`);
            button.type = 'button';
            button.dataset.sort = key;
            button.addEventListener('click', () => {
                state.order = selected && table.order === 'asc' ? 'desc' : 'asc';
                state.sort = key; state.page = 1;
                saveLocation(); refresh();
            });
            th.append(button); header.append(th);
        }
        $('#timing-table thead').replaceChildren(header);
        $('#timing-table caption').textContent = text(state.view);
        $('#timing-table tbody').replaceChildren(...table.rows.map(row => {
            const tr = node('tr');
            for (const key of columns[state.view]) {
                const td = node('td');
                const value = formatCell(row, key);
                if (['project_name', 'session_id'].includes(key)) {
                    const link = node('a', value);
                    const params = new URLSearchParams(drillState(key, row[key], row));
                    link.href = `${location.pathname}?${params}`;
                    link.title = value;
                    link.addEventListener('click', event => {
                        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
                        event.preventDefault(); drill(key, row[key], row);
                    });
                    td.append(link);
                } else { td.textContent = value; td.title = String(value); }
                tr.append(td);
            }
            return tr;
        }));
        if (!table.rows.length) {
            const row = node('tr'); const cell = node('td', text('empty'), 'muted');
            cell.colSpan = columns[state.view].length; row.append(cell); $('#timing-table tbody').append(row);
        }
        $('#timing-page').textContent = text('page', {page: table.page, pages: table.pages, total: number.format(table.total)});
        $('#timing-prev').disabled = table.page <= 1;
        $('#timing-next').disabled = table.page >= table.pages;
        $('#timing-page-input').value = table.page;
        $('#timing-page-input').max = table.pages;
        $('#timing-view-note').textContent = state.view === 'tools' ? text('tool_note') : state.view === 'sessions' ? text('gap_note') : '';
    }
    async function refresh() {
        const focusedSort = document.activeElement?.dataset.sort;
        controller?.abort();
        controller = new AbortController();
        const {signal} = controller;
        $('#timing-status').textContent = text('loading');
        $('#timing-retry').hidden = true;
        $('#timing-results').classList.add('is-loading');
        $('#timing-results').setAttribute('aria-busy', 'true');
        document.querySelectorAll('[data-view]').forEach(button => {
            const selected = button.dataset.view === state.view;
            button.setAttribute('aria-selected', String(selected)); button.tabIndex = selected ? 0 : -1;
        });
        $('#timing-table-panel').setAttribute('aria-labelledby', `tab-${state.view}`);
        try {
            const result = await fetchJSON(query(state.view), signal);
            if (signal.aborted) return;
            renderSummary(result); renderTable(result);
            $('#timing-status').textContent = '';
            $('#timing-results').hidden = false;
            if (focusedSort) {
                [...document.querySelectorAll('#timing-table th button')].find(button => button.dataset.sort === focusedSort)?.focus({preventScroll: true});
            }
        } catch (error) {
            if (error.name !== 'AbortError') {
                $('#timing-status').textContent = text('error'); $('#timing-retry').hidden = false;
                $('#timing-results').hidden = true;
            }
        } finally {
            if (!signal.aborted) {
                $('#timing-results').setAttribute('aria-busy', 'false');
                $('#timing-results').classList.remove('is-loading');
            }
        }
    }
    form.addEventListener('submit', event => {
        event.preventDefault();
        for (const field of filters) {
            if (form.elements[field]) state[field] = form.elements[field].value.trim();
        }
        if (state.window !== 'custom') { delete state.from; delete state.to; }
        state.page = 1; saveLocation(); refresh();
    });
    form.elements.window.addEventListener('change', showDates);
    $('#timing-reset').addEventListener('click', () => {
        state = {window: 'week', view: 'projects', page: 1, sort: 'agent_ms', order: 'desc'};
        form.reset(); showDates(); saveLocation(); refresh();
    });
    document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => {
        state.view = button.dataset.view; state.page = 1; state.sort = defaultSort(state.view); state.order = 'desc';
        saveLocation(); refresh();
    }));
    $('.timing-tabs').addEventListener('keydown', event => {
        const tabs = [...document.querySelectorAll('[data-view]')];
        const index = tabs.indexOf(document.activeElement);
        if (index < 0 || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const target = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
        tabs[target].focus(); tabs[target].click();
    });
    function go(page) { state.page = page; saveLocation(); refresh(); }
    $('#timing-prev').addEventListener('click', () => go(table.page - 1));
    $('#timing-next').addEventListener('click', () => go(table.page + 1));
    $('#timing-jump').addEventListener('submit', event => { event.preventDefault(); go(Number($('#timing-page-input').value)); });
    $('#timing-retry').addEventListener('click', refresh);
    addEventListener('popstate', () => { readLocation(); refresh(); });
    readLocation(); refresh();
})();
