(() => {
    'use strict';
    const toggle = document.querySelector('.navigation-toggle');
    const sidebar = document.querySelector('.sidebar');
    const backdrop = document.querySelector('.sidebar-backdrop');
    const workspace = document.querySelector('.workspace-body');
    const mobile = window.matchMedia('(max-width: 900px)');
    function setNavigation(open, restoreFocus = true) {
        if (!toggle) return;
        const expanded = open && mobile.matches;
        document.body.classList.toggle('navigation-open', expanded);
        toggle.setAttribute('aria-expanded', String(expanded));
        backdrop.hidden = !expanded;
        workspace.inert = expanded;
        sidebar.inert = mobile.matches && !expanded;
        if (expanded) {
            sidebar.setAttribute('role', 'dialog');
            sidebar.setAttribute('aria-modal', 'true');
            (sidebar.querySelector('[aria-current="page"]') || sidebar.querySelector('a'))?.focus();
        } else {
            sidebar.removeAttribute('role');
            sidebar.removeAttribute('aria-modal');
            if (restoreFocus) toggle.focus({preventScroll: true});
        }
    }
    toggle?.addEventListener('click', () => setNavigation(toggle.getAttribute('aria-expanded') !== 'true'));
    backdrop?.addEventListener('click', () => setNavigation(false));
    document.querySelector('.navigation-close')?.addEventListener('click', () => setNavigation(false));
    mobile.addEventListener('change', () => setNavigation(false, false));
    if (toggle) setNavigation(false, false);
    document.addEventListener('keydown', event => {
        if (toggle?.getAttribute('aria-expanded') === 'true') {
            if (event.key === 'Escape') { event.preventDefault(); setNavigation(false); }
            if (event.key === 'Tab') {
                const items = [...sidebar.querySelectorAll('a, button')].filter(item => item.getClientRects().length);
                const first = items[0], last = items.at(-1);
                if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
                else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
            }
        }
        if (event.key === 'Escape') {
            document.querySelectorAll('.nav-menu[open]').forEach(menu => {
                menu.open = false; menu.querySelector('summary').focus();
            });
        }
    });
    document.addEventListener('click', event => {
        document.querySelectorAll('.nav-menu[open]').forEach(menu => {
            if (!menu.contains(event.target)) menu.open = false;
        });
    });
})();
