/**
 * ruin-stream — HLS resolver + proxy for RUIN.TO
 *
 * Free plan: 50 subrequests per invocation. Everything is budgeted to fit.
 *
 * /resolve?id=<tmdb>        -> { url, provider }
 * /probe?id=<tmdb>&p=<name> -> hop log for one provider
 * /raw?u=<url>[&ref=][&auth][&via=proxy] -> response body head
 * /scan?id=<tmdb>           -> dump every bundle
 * /grep?u=<url>&q=<regex>   -> matching lines from one bundle
 * /hls?u=<url>              -> proxied playlist / segment
 * /health                   -> bench state
 * /tmdb?id=<tmdb>           -> TMDB diagnostic
 */

const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

const MIN_SECONDS = 480;
const BUDGET = 40;
const MAX_CANDIDATES = 12;
const MAX_CHUNKS = 9;
const MAX_APIS = 8;
const CONCURRENCY = 4;

const ALLOWED_HOSTS = [];

// Several distinct backbones; Cloudflare-protected hosts block one but not all.
const PROXIES = [
  (u) => `https://corsproxy.io/?url=${encodeURIComponent(u)}`,
  (u) => `https://api.codetabs.com/v1/proxy?quest=${encodeURIComponent(u)}`,
  (u) => `https://api.allorigins.win/raw?url=${encodeURIComponent(u)}`,
  (u) => `https://api.cors.lol/?url=${encodeURIComponent(u)}`,
];

/* ------------------------------------------------------------------ utils */

const cors = {
  'access-control-allow-origin': '*',
  'access-control-allow-headers': '*',
  'access-control-allow-methods': 'GET,POST,OPTIONS',
};

const json = (o, s = 200) =>
  new Response(JSON.stringify(o, null, 2), {
    status: s,
    headers: { 'content-type': 'application/json; charset=utf-8', ...cors },
  });

const enc = (p) => p.split('/').map(encodeURIComponent).join('/');
const abs = (u, b) => { try { return new URL(u, b).toString(); } catch { return u; } };

const BROWSER = {
  'user-agent': UA,
  'accept-language': 'en-US,en;q=0.9',
  'sec-ch-ua': '"Chromium";v="131", "Not_A Brand";v="24"',
  'sec-ch-ua-mobile': '?0',
  'sec-ch-ua-platform': '"Windows"',
  'upgrade-insecure-requests': '1',
};

let budget = BUDGET;
const left = () => budget;
const spend = () => { budget--; return budget > 0; };

async function req(url, o = {}) {
  spend();
  return fetch(url, {
    method: o.method || 'GET',
    headers: {
      ...BROWSER,
      accept: o.accept || 'text/html,application/xhtml+xml,*/*;q=0.8',
      'sec-fetch-dest': o.dest || 'document',
      'sec-fetch-mode': o.mode || 'navigate',
      'sec-fetch-site': o.site || 'cross-site',
      ...(o.referer ? { referer: o.referer } : {}),
      ...(o.origin ? { origin: o.origin } : {}),
      ...(o.headers || {}),
    },
    body: o.body,
    redirect: 'follow',
    cf: { cacheTtl: 0 },
  });
}

const XHR = { dest: 'empty', mode: 'cors', accept: 'application/json, text/plain, */*' };

async function viaProxy(url, o = {}) {
  for (const p of PROXIES) {
    if (budget <= 1) break;
    try {
      const pr = await req(p(url), { ...o, site: 'cross-site' });
      const b = await pr.text();
      if (pr.ok && b.length > 20) return { status: 200, ok: true, body: b, url, via: 'proxy' };
    } catch {}
  }
  return null;
}

async function text(url, o = {}) {
  if (budget <= 1) return { status: 508, ok: false, body: '', url };
  const r = await req(url, o);
  if (![403, 429, 503].includes(r.status)) {
    return { status: r.status, ok: r.ok, body: await r.text(), url: r.url };
  }
  const p = await viaProxy(url, o);
  if (p) return p;
  return { status: r.status, ok: r.ok, body: await r.text(), url: r.url };
}

/** Fetch strictly through a proxy. */
async function proxied(url, o = {}) {
  const p = await viaProxy(url, o);
  if (p) return p;
  return { status: 502, ok: false, body: '', url };
}

async function jsonFetch(url, o = {}) {
  const r = await text(url, { ...o, ...XHR });
  let data = null;
  try { data = JSON.parse(r.body); } catch {}
  return { ...r, data };
}

function m3u8s(blob) {
  if (!blob) return [];
  const s = String(blob)
    .replace(/\\\//g, '/').replace(/&amp;/g, '&')
    .replace(/\\u0026/g, '&').replace(/\\u003d/g, '=')
    .replace(/\\"/g, '"').replace(/\\n/g, '\n');
  const out = new Set();
  const re = /https?:\/\/[^\s"'<>\\)]+?\.m3u8[^\s"'<>\\)]*/gi;
  let m;
  while ((m = re.exec(s))) out.add(m[0]);
  return [...out];
}

function deepStrings(v, out = [], depth = 0) {
  if (depth > 6 || out.length > 40) return out;
  if (typeof v === 'string') {
    if (/^https?:\/\//.test(v)) out.push(v);
  } else if (Array.isArray(v)) {
    for (const x of v) deepStrings(x, out, depth + 1);
  } else if (v && typeof v === 'object') {
    for (const k of Object.keys(v)) deepStrings(v[k], out, depth + 1);
  }
  return out;
}

function iframes(blob) {
  if (!blob) return [];
  const s = String(blob).replace(/\\\//g, '/');
  const out = new Set();
  const re = /(?:src|data-src|data-api|data-url)\s*=\s*["']([^"']+)["']/gi;
  let m;
  while ((m = re.exec(s))) { if (m[1].startsWith('http')) out.add(m[1]); }
  return [...out];
}

function duration(p) {
  if (!p || !p.includes('#EXTM3U')) return 0;
  let t = 0;
  const re = /#EXTINF:([\d.]+)/g;
  let m;
  while ((m = re.exec(p))) t += parseFloat(m[1]) || 0;
  return t;
}

const isMaster = (p) => p.includes('#EXT-X-STREAM-INF');

async function firstValid(cands, referer, steps) {
  const seen = new Set();
  const list = cands.filter((u) => u && !seen.has(u) && seen.add(u)).slice(0, MAX_CANDIDATES);

  for (let i = 0; i < list.length; i += CONCURRENCY) {
    if (budget <= 2) break;
    const got = await Promise.all(
      list.slice(i, i + CONCURRENCY).map(async (u) => {
        try {
          const r = await text(u, { referer, accept: '*/*', dest: 'empty', mode: 'cors' });
          if (!r.ok || !r.body.includes('#EXTM3U')) return null;
          if (isMaster(r.body)) { steps.push(`master ${u}`); return { url: u }; }
          const secs = duration(r.body);
          steps.push(`media ${Math.round(secs)}s ${u}`);
          return secs >= MIN_SECONDS ? { url: u } : null;
        } catch { return null; }
      })
    );
    const hit = got.find(Boolean);
    if (hit) return hit;
  }
  return null;
}

/* ------------------------------------------------------- page + JS mining */

function chunks(html, base) {
  const out = new Set();
  let m;
  const re = /["'(\s](\/_next\/static\/[A-Za-z0-9_\-\/]+\.js)/g;
  while ((m = re.exec(html))) out.add(abs(m[1], base));
  return [...out];
}

const KEY = /api|source|stream|playlist|manifest|watch|src/i;

function cleanRoutes(list) {
  const out = [];
  for (const r of list) {
    if (r.length < 5 || r.length > 160) continue;
    if (/\.(png|jpe?g|svg|css|woff2?|ico|webp|gif|js|json)$/i.test(r)) continue;
    if (!(r.startsWith('/') || r.startsWith('http'))) continue;
    if (!KEY.test(r) && !r.includes('${')) continue;
    out.push(r);
  }
  return [...new Set(out)];
}

function apiRoutes(js) {
  const raw = [];
  let m;
  const rePath = /["'`](\/[A-Za-z0-9_\-\/\.\$\{\}]*)/g;
  while ((m = rePath.exec(js))) raw.push(m[1]);
  const reUrl = /["'`](https?:\/\/[^"'`\s]+)["'`]/g;
  while ((m = reUrl.exec(js))) { if (m[1].length < 160) raw.push(m[1]); }
  const reFetch = /fetch\(\s*[`'"]([^`'"]+)[`'"]/g;
  while ((m = reFetch.exec(js))) raw.push(m[1]);
  return cleanRoutes(raw);
}

function expand(tpl, tmdb, imdb) {
  if (!tpl.includes('$')) return [tpl];
  const out = [];
  for (const filler of [tmdb, imdb].filter(Boolean)) {
    out.push(
      tpl.replace(/\$\{[^}]*\}/g, (tok) => {
        if (/imdb/i.test(tok)) return imdb || filler;
        if (/type|kind/i.test(tok)) return 'movie';
        return filler;
      })
    );
  }
  return out;
}

async function mine(entry, referer, steps, opt = {}) {
  const found = [];
  const apis = new Set();

  const page = await text(entry, { referer });
  steps.push(`page ${page.status} len=${page.body.length}${page.via ? ` (${page.via})` : ''}`);
  if (!page.ok) return { found };
  found.push(...m3u8s(page.body));

  const base = page.url || entry;
  for (const f of iframes(page.body).slice(0, 1)) {
    if (f === entry) continue;
    const p = await text(f, { referer: base });
    steps.push(`frame ${p.status} len=${p.body.length}${p.via ? ` (${p.via})` : ''}`);
    found.push(...m3u8s(p.body));
  }

  const js = chunks(page.body, base).slice(0, opt.maxChunks ?? MAX_CHUNKS);
  steps.push(`chunks ${js.length}`);
  await Promise.all(
    js.map(async (c) => {
      try {
        const r = await text(c, { referer: base, dest: 'script', mode: 'no-cors', accept: '*/*' });
        if (!r.ok) { steps.push(`chunk ${r.status}`); return; }
        found.push(...m3u8s(r.body));
        for (const a of apiRoutes(r.body)) apis.add(a);
      } catch {}
    })
  );

  const routeList = [...apis].filter((a) => !/\.js$/.test(a));
  steps.push(`routes ${routeList.length ? routeList.slice(0, 5).join(' ') : 'none'}`);

  const tried = new Set();
  for (const a of routeList.slice(0, MAX_APIS)) {
    if (budget <= 4) break;
    const url = a.startsWith('http') ? a : abs(a, base);
    for (const u of expand(url, opt.tmdb, opt.imdb)) {
      if (tried.has(u)) continue;
      tried.add(u);
      try {
        const r = await jsonFetch(u, { referer: base, origin: new URL(base).origin });
        steps.push(`api ${r.status} ${u.slice(-45)}`);
        found.push(...m3u8s(r.body));
      } catch {}
    }
  }

  return { found };
}

/* -------------------------------------------------------------- providers */

const ctx = (env, tmdb, imdb, steps) => ({ env, tmdb, imdb, steps });

async function vidlink(c) {
  const found = [];
  const ref = `https://vidlink.pro/movie/${c.tmdb}`;
  const origin = 'https://vidlink.pro';
  const page = await text(ref);
  c.steps.push(`page ${page.status} len=${page.body.length}`);
  found.push(...m3u8s(page.body));

  const shapes = [];
  for (const id of [c.tmdb, c.imdb].filter(Boolean)) {
    shapes.push(`/api/b/movie/${id}`);
    shapes.push(`/api/b/movie/${id}?type=movie`);
    shapes.push(`/api/b/movie/${id}?id=${id}&type=movie`);
  }
  shapes.push(`/api/b/movie?tmdb=${c.tmdb}`, `/api/b/${c.tmdb}`);

  for (const p of shapes) {
    if (budget <= 5) break;
    const u = abs(p, origin);
    const r = await jsonFetch(u, { referer: ref, origin });
    const nonNull = r.body.trim() !== 'null';
    c.steps.push(`get ${p} ${r.status} len=${r.body.length}${nonNull ? ' DATA' : ''}`);
    if (r.data) {
      const deep = deepStrings(r.data);
      if (deep.length) c.steps.push(`deep ${deep.length}`);
      found.push(...deep);
    }
    found.push(...m3u8s(r.body));
    if (nonNull) break;
  }

  const hit = await firstValid(found, ref, c.steps);
  if (!hit) throw new Error('no playlist');
  return hit.url;
}

async function vidsrc(c) {
  const sh = 'https://vidsrc.sh';
  const ref = `${sh}/`;
  const found = [];

  const meta = await jsonFetch(`https://data.vidsrc.sh/api.php?type=movie&tmdb=${c.tmdb}`, { referer: ref });
  c.steps.push(`meta ${meta.status}${meta.via ? ` (${meta.via})` : ''}`);
  const host = meta.data?.stream_urls_api_host;
  const file = meta.data?.file_name;
  if (host && file) {
    c.steps.push(`host ${host}`);
    const stem = file.split('/').pop().replace(/\.(mp4|mkv|avi|m4v)$/i, '');
    const dir = file.includes('/') ? file.split('/').slice(0, -1).join('/') : '';
    const push = (p) => found.push(`https://${host}/${enc(p)}`);
    for (const s of ['index.m3u8', 'playlist.m3u8']) push(`${file}/${s}`);
    push(`${file}.m3u8`); push(`${stem}.m3u8`);
    if (dir) push(`${dir}/${stem}/index.m3u8`);
  }

  const src = await jsonFetch(`${sh}/vs_src.php?type=movie&id=${c.tmdb}`, { referer: `${sh}/embed/movie/${c.tmdb}/` });
  c.steps.push(`src ${src.status}${src.via ? ` (${src.via})` : ''}`);
  const landing = src.data?.src;
  if (landing) {
    const page = await text(landing, { referer: `${sh}/embed/movie/${c.tmdb}/` });
    c.steps.push(`landing ${page.status} len=${page.body.length}${page.via ? ` (${page.via})` : ''}`);
    found.push(...m3u8s(page.body));
    const pu = page.body.match(/playerUrl\\?"\s*:\s*\\?"([^"\\]+)/)?.[1];
    if (pu) {
      const purl = pu.startsWith('http') ? pu : abs(pu, landing);
      const pp = await text(purl, { referer: landing });
      c.steps.push(`player ${pp.status} len=${pp.body.length}${pp.via ? ` (${pp.via})` : ''}`);
      found.push(...m3u8s(pp.body));
    }
  }

  const hit = await firstValid(found, ref, c.steps);
  if (!hit) throw new Error('no playlist');
  return hit.url;
}

async function vixsrc(c) {
  const ref = `https://vixsrc.to/movie/${c.tmdb}`;
  const found = [];
  const r = await jsonFetch(`https://vixsrc.to/api/movie/${c.tmdb}?lang=en`, { referer: ref });
  c.steps.push(`api ${r.status}${r.via ? ` (${r.via})` : ''} len=${r.body.length}`);
  if (typeof r.data?.src === 'string') found.push(r.data.src);
  found.push(...m3u8s(r.body));
  const hit = await firstValid(found, ref, c.steps);
  if (!hit) throw new Error('no playlist');
  return hit.url;
}

async function videm(c) {
  if (!c.imdb) throw new Error('no imdb id');
  const found = [];

  const targets = [
    `https://videm.cc/embed/movie/${c.imdb}?autoplay=true`,
    `https://videm.buzz/embed/movie/${c.imdb}?autoplay=true`,
  ];

  const mu = await text(`https://movieuniverse.skin/watch-movieuniverse-${c.tmdb}`);
  c.steps.push(`movieuniverse ${mu.status}`);
  found.push(...m3u8s(mu.body));
  for (const f of iframes(mu.body).filter((u) => /videm|2embed|player|vsr/i.test(u)).slice(0, 1)) {
    if (!targets.includes(f)) targets.unshift(f);
  }

  for (const t of targets.slice(0, 2)) {
    if (budget <= 6) break;
    const p = await proxied(t, { referer: 'https://movieuniverse.skin/' });
    c.steps.push(`embed ${p.status} len=${p.body.length}${p.via ? ' (proxy)' : ''}`);
    found.push(...m3u8s(p.body));
    for (const f of iframes(p.body).slice(0, 1)) {
      const q = await proxied(f, { referer: t });
      c.steps.push(`nest ${q.status} len=${q.body.length}`);
      found.push(...m3u8s(q.body));
    }
  }

  const hit = await firstValid(found, 'https://movieuniverse.skin/', c.steps);
  if (!hit) throw new Error('no playlist');
  return hit.url;
}

async function nxsha(c) {
  const base = 'https://web.nxsha.app';
  const found = [];
  const page = await text(`${base}/embed/movie/${c.tmdb}`, { referer: 'https://embedwave.cc/' });
  c.steps.push(`page ${page.status} len=${page.body.length}`);
  found.push(...m3u8s(page.body));
  for (const p of ['/api/stream/', '/api/source/', '/api/movie/']) {
    if (budget <= 6) break;
    const r = await jsonFetch(base + p + c.tmdb, { referer: `${base}/embed/movie/${c.tmdb}`, origin: base });
    c.steps.push(`${r.status} ${p}`);
    found.push(...m3u8s(r.body));
  }
  const hit = await firstValid(found, `${base}/`, c.steps);
  if (!hit) throw new Error('no playlist');
  return hit.url;
}

const PROVIDERS = [
  { name: 'vidlink', run: vidlink },
  { name: 'vidsrc', run: vidsrc },
  { name: 'videm', run: videm },
  { name: 'vixsrc', run: vixsrc },
  { name: 'nxsha', run: nxsha },
];

/* --------------------------------------------------------------- benching */

const bench = new Map();
const FAIL_LIMIT = 2;
const BENCH_MS = 10 * 60 * 1000;
const sick = (n) => { const b = bench.get(n); return !!b && b.fails >= FAIL_LIMIT && Date.now() < b.until; };
const markFail = (n) => { const b = bench.get(n) || { fails: 0, until: 0 }; b.fails++; b.until = Date.now() + BENCH_MS; bench.set(n, b); };
const markOk = (n) => bench.set(n, { fails: 0, until: 0 });

/* ---------------------------------------------------------------- routing */

async function imdbFor(env, tmdb, steps) {
  const key = (env.TMDB_KEY || '').trim();
  if (!key) { steps?.push('tmdb no key'); return null; }
  const auth = key.startsWith('eyJ')
    ? { headers: { authorization: `Bearer ${key}` } }
    : { q: `?api_key=${encodeURIComponent(key)}` };
  const suffix = auth.q || '';

  for (const path of [`/movie/${tmdb}/external_ids`, `/movie/${tmdb}`]) {
    try {
      const r = await jsonFetch(`https://api.themoviedb.org/3${path}${suffix}`, {
        accept: 'application/json',
        ...(auth.headers ? { headers: auth.headers } : {}),
      });
      steps?.push(`tmdb ${r.status} ${path}`);
      if (r.ok && r.data?.imdb_id) return r.data.imdb_id;
    } catch (e) { steps?.push(`tmdb err ${e.message}`); }
  }
  return null;
}

function keyShape(env) {
  const k = (env.TMDB_KEY || '').trim();
  return { present: !!k, len: k.length, head: k.slice(0, 6), isJwt: k.startsWith('eyJ') };
}

async function resolve(request, env) {
  budget = BUDGET;
  const url = new URL(request.url);
  const tmdb = url.searchParams.get('id');
  if (!tmdb || !/^\d+$/.test(tmdb)) return json({ error: 'bad id' }, 400);

  const boot = [];
  const imdb = await imdbFor(env, tmdb, boot);
  const order = [...PROVIDERS.filter((p) => !sick(p.name)), ...PROVIDERS.filter((p) => sick(p.name))];
  const tried = [];

  for (const p of order) {
    if (budget <= 6) { tried.push({ provider: p.name, error: 'budget exhausted' }); continue; }
    const steps = [...boot];
    try {
      const stream = await p.run(ctx(env, tmdb, imdb, steps));
      markOk(p.name);
      return json({ provider: p.name, url: `${url.origin}/hls?u=${encodeURIComponent(stream)}` });
    } catch (e) {
      markFail(p.name);
      tried.push({ provider: p.name, error: String(e.message || e), steps });
    }
  }
  return json({ error: 'no working source', tried }, 502);
}

async function probe(request, env) {
  budget = BUDGET;
  const url = new URL(request.url);
  const tmdb = url.searchParams.get('id');
  if (!tmdb) return json({ error: 'bad id' }, 400);

  const only = url.searchParams.get('p');
  const boot = [];
  const imdb = await imdbFor(env, tmdb, boot);
  const targets = only ? PROVIDERS.filter((x) => x.name === only) : PROVIDERS.slice(0, 1);
  const out = [];
  for (const p of targets) {
    const steps = [...boot];
    try {
      const stream = await p.run(ctx(env, tmdb, imdb, steps));
      out.push({ provider: p.name, ok: true, stream, steps, budget_left: left() });
    } catch (e) {
      out.push({ provider: p.name, ok: false, error: String(e.message || e), steps, budget_left: left() });
    }
  }
  return json({ imdb, ran: targets.map((t) => t.name), out });
}

async function raw(request, env) {
  budget = BUDGET;
  const url = new URL(request.url);
  const u = url.searchParams.get('u');
  if (!u) return json({ error: 'bad u' }, 400);

  const ref = url.searchParams.get('ref') || undefined;
  const o = { referer: ref, accept: '*/*' };
  if (ref) { try { o.origin = new URL(ref).origin; } catch {} }
  if (url.searchParams.get('auth')) {
    o.headers = { authorization: `Bearer ${(env.TMDB_KEY || '').trim()}` };
    o.accept = 'application/json';
  }
  if (url.searchParams.get('post')) {
    o.method = 'POST';
    o.headers = { ...(o.headers || {}), 'content-type': 'application/json' };
    o.body = url.searchParams.get('post') === '1' ? '{}' : url.searchParams.get('post');
  }

  const r = url.searchParams.get('via') === 'proxy' ? await proxied(u, o) : await text(u, o);
  return json({ status: r.status, via: r.via || 'direct', len: r.body.length, head: r.body.slice(0, 1400) });
}

async function scan(request) {
  budget = BUDGET;
  const url = new URL(request.url);
  const entry = url.searchParams.get('u') || `https://web.nxsha.app/embed/movie/${url.searchParams.get('id') || '49018'}`;
  const q = url.searchParams.get('q') || 'm3u8|manifest|playlist|\\/api\\/|\\.php|stream';

  const page = await text(entry, { referer: 'https://embedwave.cc/' });
  if (!page.ok) return json({ status: page.status, len: page.body.length }, 502);

  const base = page.url || entry;
  const list = chunks(page.body, base).slice(0, MAX_CHUNKS);
  const re = new RegExp(q, 'gi');

  const out = await Promise.all(
    list.map(async (c, i) => {
      try {
        const r = await text(c, { referer: base, dest: 'script', mode: 'no-cors', accept: '*/*' });
        if (!r.ok) return { i, url: c, status: r.status };
        const hits = [];
        let m;
        while ((m = re.exec(r.body)) && hits.length < 5) {
          hits.push(r.body.slice(Math.max(0, m.index - 70), m.index + 110).replace(/\s+/g, ' '));
        }
        return { i, url: c, len: r.body.length, m3u8: m3u8s(r.body).slice(0, 3), hits };
      } catch { return { i, url: c, err: true }; }
    })
  );

  return json({ entry, chunks: out, budget_left: left() });
}

async function grep(request) {
  budget = BUDGET;
  const url = new URL(request.url);
  const u = url.searchParams.get('u');
  const q = url.searchParams.get('q') || 'm3u8';
  if (!u) return json({ error: 'bad u' }, 400);

  const r = await text(u, { accept: '*/*', dest: 'script', mode: 'no-cors' });
  if (!r.ok) return json({ status: r.status, len: r.body.length }, 502);

  const re = new RegExp(q, 'gi');
  const hits = [];
  let m;
  while ((m = re.exec(r.body)) && hits.length < 30) {
    hits.push(r.body.slice(Math.max(0, m.index - 90), m.index + 130).replace(/\s+/g, ' '));
  }
  return json({ len: r.body.length, count: hits.length, hits });
}

/* ------------------------------------------------------------------ proxy */

const hostOk = (u) => {
  if (!ALLOWED_HOSTS.length) return true;
  try { const h = new URL(u).hostname; return ALLOWED_HOSTS.some((a) => h === a || h.endsWith(`.${a}`)); }
  catch { return false; }
};

function rewrite(playlist, base, origin) {
  const px = (u) => `${origin}/hls?u=${encodeURIComponent(abs(u, base))}`;
  return playlist
    .split('\n')
    .map((line) => {
      const t = line.trim();
      if (!t) return line;
      if (t.startsWith('#')) return line.replace(/URI="([^"]+)"/g, (_, u) => `URI="${px(u)}"`);
      return px(t);
    })
    .join('\n');
}

async function hls(request) {
  budget = BUDGET;
  const u = new URL(request.url).searchParams.get('u');
  if (!u) return new Response('missing u', { status: 400, headers: cors });
  if (!hostOk(u)) return new Response('host not allowed', { status: 403, headers: cors });

  let target;
  try { target = new URL(u); } catch { return new Response('bad u', { status: 400, headers: cors }); }

  const range = request.headers.get('range');
  const r = await req(u, {
    referer: `${target.protocol}//${target.host}/`,
    origin: `${target.protocol}//${target.host}`,
    accept: '*/*', dest: 'empty', mode: 'cors',
    headers: range ? { range } : {},
  });

  const type = r.headers.get('content-type') || '';
  const isPlaylist = type.includes('mpegurl') || u.includes('.m3u8') || (!range && !type.startsWith('video') && !type.includes('octet'));

  const headers = new Headers(cors);
  headers.set('access-control-expose-headers', 'content-length,content-range,accept-ranges');

  if (isPlaylist) {
    const body = rewrite(await r.text(), r.url || u, new URL(request.url).origin);
    headers.set('content-type', 'application/vnd.apple.mpegurl');
    headers.set('cache-control', 'no-store');
    return new Response(body, { status: r.status, headers });
  }

  for (const h of ['content-type', 'content-length', 'content-range', 'accept-ranges']) {
    const v = r.headers.get(h);
    if (v) headers.set(h, v);
  }
  return new Response(r.body, { status: r.status, headers });
}

/* ------------------------------------------------------------------ entry */

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    if (request.method === 'OPTIONS') return new Response(null, { headers: cors });
    budget = BUDGET;
    try {
      if (pathname === '/resolve') return await resolve(request, env);
      if (pathname === '/probe') return await probe(request, env);
      if (pathname === '/raw') return await raw(request, env);
      if (pathname === '/scan') return await scan(request, env);
      if (pathname === '/hls') return await hls(request);
      if (pathname === '/grep') return await grep(request);
      if (pathname === '/tmdb') {
        const steps = [];
        const imdb = await imdbFor(env, new URL(request.url).searchParams.get('id') || '49018', steps);
        return json({ key: keyShape(env), imdb, steps });
      }
      if (pathname === '/health')
        return json(Object.fromEntries(PROVIDERS.map((p) => [p.name, { benched: sick(p.name), ...(bench.get(p.name) || { fails: 0 }) }])));
      return json({ ok: true, routes: ['/resolve', '/probe', '/raw', '/scan', '/hls', '/health', '/tmdb', '/grep'] });
    } catch (e) {
      return json({ error: String(e.message || e) }, 500);
    }
  },
};