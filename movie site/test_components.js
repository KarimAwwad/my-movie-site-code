#!/usr/bin/env node
// Backend checks for components.js. Renders the templates in a sandbox with stubbed page helpers
// and asserts the data tables and emitted markup are sane.

const fs = require('fs');
const vm = require('vm');

const PASSES = [];
const FAILS = [];

function check(name, ok, detail = '') {
    (ok ? PASSES : FAILS).push(name);
    console.log((ok ? 'PASS  ' : 'FAIL  ') + name + (detail ? `   [${detail}]` : ''));
}

const src = fs.readFileSync('components.js', 'utf8') +
    '\n;globalThis.__T=T;globalThis.__D={GENRES,COUNTRIES,REGIONS,NETWORKS,FILTER_DEFS,' +
    'GENRE_CARDS,NAV_PAGES,COLLECTIONS,LEGAL_DOCS,FIRST_NETWORK,GENRE_BY_KEY,yearPills,DISCORD_URL};';

const ctx = {
    pageUrl: k => (k ? k + '.html' : 'index.html'),
    APP_BASE: '/',
    initialAvatar: () => 'data:,',
    avatarFallback: () => {},
    SK: {hero: () => '<div class="sk"></div>'},
    console,
    Date,
};
ctx.window = ctx;
ctx.self = ctx;
ctx.globalThis = ctx;

vm.createContext(ctx);
vm.runInContext(src, ctx, {filename: 'components.js'});

const T = ctx.__T;
const D = ctx.__D;

const ARGS = {
    grid: [true],
    dashboard: ['watchhistory'],
    auth: ['register'],
    banner: ['<i></i>', 'Title', 'Sub', '#fff'],
    legal: ['privacy'],
};

const ids = html => [...html.matchAll(/id="([^"]+)"/g)].map(m => m[1]);

console.log('--- every template renders ---');
for (const key of Object.keys(T)) {
    let out = '';
    let err = '';
    try {
        out = T[key](...(ARGS[key] || []));
    } catch (e) {
        err = e.message;
    }
    check(`T.${key} renders`, !err && typeof out === 'string' && out.length > 0, err);
    if (!err) check(`T.${key} has no undefined/NaN`, !/undefined|NaN/.test(out),
        (out.match(/undefined|NaN/) || [''])[0]);
    if (!err) {
        const seen = new Set();
        const dupes = ids(out).filter(i => seen.has(i) || !seen.add(i));
        check(`T.${key} has no duplicate ids`, dupes.length === 0, dupes.join(','));
    }
}

console.log('\n--- a real page combination has no duplicate ids ---');
const shell = T.header() + T.tabbar() + T.toolbar() + T.grid(true) + T.home() + T.footer();
const shellIds = ids(shell);
const shellDupes = shellIds.filter((i, n) => shellIds.indexOf(i) !== n);
check('header+tabbar+toolbar+grid+home+footer unique', shellDupes.length === 0,
    [...new Set(shellDupes)].join(','));
check('grid heading does not reuse category-title', ids(T.grid(true)).includes('grid-title')
    && !ids(T.grid(true)).includes('category-title'));
check('toolbar still owns category-title', ids(T.toolbar()).includes('category-title'));

console.log('\n--- filter definitions ---');
for (const [key, def] of Object.entries(D.FILTER_DEFS)) {
    check(`filter "${key}" has a title`, typeof def.title === 'string' && def.title.length > 0);
    check(`filter "${key}" id is a popover`, /^popover-/.test(def.id || ''), def.id);
    check(`filter "${key}" has pills`, Array.isArray(def.pills) || typeof def.pills === 'function');
}

console.log('\n--- pill markup is quote-safe ---');
const toolbar = T.toolbar();
const pillTags = [...toolbar.matchAll(/<div class="filter-pill[^>]*>/g)].map(m => m[0]);
check('pills were emitted', pillTags.length > 0, String(pillTags.length));
check('every pill carries data-value and data-label',
    pillTags.every(p => /data-value="/.test(p) && /data-label="/.test(p)));
check('no pill value contains a single quote',
    [...toolbar.matchAll(/data-value="([^"]*)"/g)].every(m => !m[1].includes("'")));
check('no pill value contains a double quote',
    [...toolbar.matchAll(/data-value="([^"]*)"/g)].every(m => !m[1].includes('"')));

console.log('\n--- genre pills match the movie/tv id table ---');
for (const [key, , movieId, tvId] of D.GENRES) {
    const tag = pillTags.find(p => p.includes(`data-value="${key}"`));
    if (!tag) { check(`genre ${key} pill exists`, false); continue; }
    if (movieId === null) check(`genre ${key} is tv-only`, tag.includes('tv-only'));
    if (tvId === null) check(`genre ${key} is movie-only`, tag.includes('movie-only'));
}

console.log('\n--- year pills are rebuilt per render ---');
const years = D.yearPills();
check('first year pill is All', years[0][0] === '');
check('current year comes first', years[1][0] === String(new Date().getFullYear()), years[1][0]);
check('older is last', years[years.length - 1][0] === 'older');
check('year pills are a function, not a frozen array',
    typeof D.FILTER_DEFS.year.pills === 'function');

console.log('\n--- dashboard pane aliasing ---');
for (const [input, pane] of [['watchhistory', 'history'], ['history', 'history'],
                             ['profile', 'overview'], ['overview', 'overview'],
                             ['nonsense', 'overview']]) {
    const html = T.dashboard(input);
    check(`tab "${input}" renders pane-${pane}`, ids(html).includes(`pane-${pane}`));
}
check('watchhistory marks the history tab active',
    /class="dash-tab active" href="watchhistory\.html"/.test(T.dashboard('watchhistory')));
check('settings renders the settings form', ids(T.dashboard('settings')).includes('settings-content'));

console.log('\n--- network heading is derived from the data ---');
const home = T.home();
check('heading uses NETWORKS[0]', home.includes('TRENDING ON ' + D.FIRST_NETWORK.name.toUpperCase()));
check('see-all points at NETWORKS[0]', home.includes(`id="network-see-all" href="${D.FIRST_NETWORK.key}.html"`));

console.log('\n--- supporting tables ---');
check('every GENRE_CARDS key has a genre row', D.GENRE_CARDS.every(([k]) => D.GENRE_BY_KEY[k]));
check('every NAV_PAGES entry has a page key', D.NAV_PAGES.every(p => typeof p[0] === 'string' && p[0]));
check('every COLLECTIONS entry has a key', D.COLLECTIONS.every(c => c.key));
check('every NETWORKS entry has a key and name', D.NETWORKS.every(n => n.key && n.name));
check('every REGIONS entry has a value and label', D.REGIONS.every(r => Array.isArray(r) && r.length === 2));
check('every COUNTRY code is two uppercase letters',
    D.COUNTRIES.every(([c]) => /^[A-Z]{2}$/.test(c)));
check('no duplicate country codes', new Set(D.COUNTRIES.map(c => c[0])).size === D.COUNTRIES.length);
check('no duplicate network keys', new Set(D.NETWORKS.map(n => n.key)).size === D.NETWORKS.length);

console.log('\n--- legal pages ---');
for (const [doc, def] of Object.entries(D.LEGAL_DOCS)) {
    check(`legal "${doc}" has a title`, typeof def.title === 'string' && def.title.length > 0);
    let html = '';
    try { html = def.html(); } catch (e) { html = ''; }
    check(`legal "${doc}" renders`, html.length > 0);
}
check('unknown legal doc falls back to about', T.legal('nope').includes('RUIN.TO is a home'));
check('Discord link is set', /^https:\/\/discord\.gg\//.test(D.DISCORD_URL), D.DISCORD_URL);

console.log(`\n${PASSES.length} passed, ${FAILS.length} failed`);
for (const name of FAILS) console.log('  FAILED: ' + name);
process.exit(FAILS.length ? 1 : 0);