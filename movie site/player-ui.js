/* ============================================================================
   player-ui.js  -  the LOOK and the CONTROLS of the RUIN.TO player.

   Loaded after script.js (see watch.html). It only builds the interface. It never decides WHERE a stream
   comes from: resolveStreams(), playSource(), teardownPlayer(), restoreProgress() and saveProgress() all stay in
   script.js, exactly as you wrote them. This file re-declares a few functions (bindPlayerControls, playerKeys,
   buildSubtitleMenu, pToast ...). A later <script> that declares the same function name wins, which is how this
   file replaces the old controls without anyone editing script.js.

   It reads these globals from script.js: vid, pel, playerShell, fmtTime, hls, streamSources, sourceIndex,
   playerMovie, togglePlay, wakePlayer, saveProgress.
   ========================================================================== */

(function () {
    'use strict';

// ---- SETTINGS (edit these) --------------------------------------------------------------------------------------
    const PLAYER_UI = window.PLAYER_UI = {
        skipSeconds: 10,
        subsKey: 'wyzie-csmoxejnludklwa0im6d9g5rwbjn1e3r',
        subsEndpoint: 'https://sub.wyzie.io/search',
        supabaseUrl: 'https://eriewfiqaywpxkvpgcdo.supabase.co',
        supabaseKey: 'sb_publishable_ydTL5VTzMG_oVc2S9eZlHg_AujoCm8-',
        subLanguages: [
            ['ar', 'العربية (Arabic)'], ['en', 'English'], ['es', 'Spanish'], ['fr', 'French'], ['de', 'German'], ['it', 'Italian'],
            ['pt', 'Portuguese'], ['pt-br', 'Portuguese (Brazil)'], ['tr', 'Turkish'], ['ru', 'Russian'], ['ja', 'Japanese'], ['ko', 'Korean'],
            ['zh', 'Chinese'], ['hi', 'Hindi'], ['nl', 'Dutch'], ['pl', 'Polish'], ['sv', 'Swedish'], ['no', 'Norwegian'],
            ['da', 'Danish'], ['fi', 'Finnish'], ['el', 'Greek'], ['he', 'Hebrew'], ['fa', 'Persian'], ['ur', 'Urdu'],
            ['bn', 'Bengali'], ['id', 'Indonesian'], ['ms', 'Malay'], ['th', 'Thai'], ['vi', 'Vietnamese'], ['tl', 'Filipino'],
            ['cs', 'Czech'], ['sk', 'Slovenian'], ['hu', 'Hungarian'], ['ro', 'Romanian'], ['bg', 'Bulgarian'], ['uk', 'Ukrainian'],
            ['sr', 'Serbian'], ['hr', 'Croatian'], ['sl', 'Slovenian'], ['lt', 'Lithuanian'], ['lv', 'Latvian'], ['et', 'Estonian'],
            ['is', 'Icelandic'], ['ca', 'Catalan'], ['sq', 'Albanian'], ['mk', 'Macedonian'], ['ta', 'Tamil'], ['te', 'Telugu'],
            ['ml', 'Malayalam'], ['ne', 'Nepali'], ['si', 'Sinhala'], ['km', 'Khmer'], ['sw', 'Swahili'], ['af', 'Afrikaans'],
            ['ka', 'Georgian'], ['hy', 'Armenian'], ['az', 'Azerbaijani'], ['kk', 'Kazakh'],
        ],
        speeds: [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2],
    };

    const store = {
        get(k, fallback) {
            try {
                const v = localStorage.getItem('ruin.player.' + k);
                return v === null ? fallback : JSON.parse(v);
            } catch (e) {
                return fallback;
            }
        },
        set(k, v) {
            try {
                localStorage.setItem('ruin.player.' + k, JSON.stringify(v));
            } catch (e) { /* ignore */
            }
        },
    };

// The relay address. window.RUIN_RELAY wins, so a different port can be set from watch.html without touching
// script.js; otherwise the source's own origin, then script.js's STREAM_API, then the default port.
    function getRelayBase() {
        if (typeof window.RUIN_RELAY === 'string' && window.RUIN_RELAY.trim()) {
            return window.RUIN_RELAY.trim().replace(/\/+$/, '');
        }
        const activeUrl = streamSources?.[sourceIndex]?.url || '';
        if (/^https?:\/\//i.test(activeUrl) && activeUrl.includes('/hls?')) {
            try {
                return new URL(activeUrl).origin;
            } catch (e) { /* fall through */
            }
        }
        if (typeof STREAM_API !== 'undefined' && STREAM_API) {
            return String(STREAM_API).replace(/\/+$/, '');
        }
        return `http://${location.hostname}:8787`;
    }

// The acquisition daemon (grab.py). Same override rule.
    function getGrabBase() {
        if (typeof window.GRAB_API === 'string' && window.GRAB_API.trim()) {
            return window.GRAB_API.trim().replace(/\/+$/, '');
        }
        return `http://${location.hostname}:8789`;
    }

// Resolve IMDb ID + runtime even if script.js keeps detailsCache block-scoped.
    const resolvedMetaCache = new Map();

    async function resolveMovieMeta() {
        const id = playerMovie?.id;
        if (!id) return {imdb_id: '', runtime: 0};
        if (resolvedMetaCache.has(id)) return resolvedMetaCache.get(id);

        const dc = (typeof detailsCache !== 'undefined' ? detailsCache : window.detailsCache);
        const cached = dc?.get?.(id);
        if (cached?.imdb_id) {
            const meta = {imdb_id: cached.imdb_id, runtime: cached.runtime || playerMovie?.runtime || 0};
            resolvedMetaCache.set(id, meta);
            return meta;
        }

        if (playerMovie?.imdb_id) {
            const meta = {imdb_id: playerMovie.imdb_id, runtime: playerMovie.runtime || 0};
            resolvedMetaCache.set(id, meta);
            return meta;
        }

        const tmdbTok = (typeof API_KEY !== 'undefined' && API_KEY)
            || (typeof TMDB_KEY !== 'undefined' && TMDB_KEY)
            || window.TMDB_KEY || '';
        if (tmdbTok) {
            try {
                const isBearer = String(tmdbTok).length > 40;
                const url = isBearer
                    ? `https://api.themoviedb.org/3/movie/${id}`
                    : `https://api.themoviedb.org/3/movie/${id}?api_key=${encodeURIComponent(tmdbTok)}`;
                const res = await fetch(url, isBearer ? {headers: {Authorization: `Bearer ${tmdbTok}`}} : {});
                if (res.ok) {
                    const data = await res.json();
                    const meta = {imdb_id: data.imdb_id || '', runtime: data.runtime || playerMovie?.runtime || 0};
                    resolvedMetaCache.set(id, meta);
                    return meta;
                }
            } catch { /* ignore */
            }
        }

        const fallback = {imdb_id: '', runtime: cached?.runtime || playerMovie?.runtime || 0};
        resolvedMetaCache.set(id, fallback);
        return fallback;
    }

// ---- ICONS ----------------------------------------------------------------------------------------------------------
    const svg = (body, extra = '') => `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${body}</svg>`;
    const PI = {
        play: svg('<path d="M7 4.5v15l12-7.5z" fill="currentColor" stroke="none"/>'),
        pause: svg('<rect x="6" y="4.5" width="4.2" height="15" rx="1" fill="currentColor" stroke="none"/><rect x="13.8" y="4.5" width="4.2" height="15" rx="1" fill="currentColor" stroke="none"/>'),
        back: svg('<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1"/><path d="M3.5 4v4.6H8"/><text x="12" y="15.4" font-size="7.4" font-weight="700" text-anchor="middle" fill="currentColor" stroke="none" font-family="Montserrat,Arial,sans-serif">10</text>'),
        fwd: svg('<path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1"/><path d="M20.5 4v4.6H16"/><text x="12" y="15.4" font-size="7.4" font-weight="700" text-anchor="middle" fill="currentColor" stroke="none" font-family="Montserrat,Arial,sans-serif">10</text>'),
        volHigh: svg('<path d="M4 9.5v5h3.6L12.5 19V5L7.6 9.5z" fill="currentColor"/><path d="M16 8.6a5 5 0 0 1 0 6.8"/><path d="M18.8 6a9 9 0 0 1 0 12"/>'),
        volLow: svg('<path d="M4 9.5v5h3.6L12.5 19V5L7.6 9.5z" fill="currentColor"/><path d="M16 8.6a5 5 0 0 1 0 6.8"/>'),
        volMute: svg('<path d="M4 9.5v5h3.6L12.5 19V5L7.6 9.5z" fill="currentColor"/><path d="M16.5 9.5l5 5M21.5 9.5l-5 5"/>'),
        speed: svg('<path d="M12 4a9 9 0 1 0 9 9"/><path d="M12 13l5-5"/><circle cx="12" cy="13" r="1.4" fill="currentColor"/>'),
        cc: svg('<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M10.2 10.2a2.2 2.2 0 1 0 0 3.6M16.4 10.2a2.2 2.2 0 1 0 0 3.6"/>'),
        server: svg('<rect x="3" y="4" width="18" height="6" rx="2"/><rect x="3" y="14" width="18" height="6" rx="2"/><path d="M7 7h.01M7 17h.01"/>'),
        gear: svg('<circle cx="12" cy="12" r="3"/><path d="M19.4 14.5a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3h0a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5h0a1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8v0a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z"/>'),
        pip: svg('<rect x="3" y="5" width="18" height="14" rx="2.5"/><rect x="12" y="11.5" width="7" height="5" rx="1.2" fill="currentColor" stroke="none"/>'),
        full: svg('<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>'),
        exitFull: svg('<path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/>'),
    };

// ---- the control bar ------------------------------------------------------------------------------------------------
    function buildControls(box) {
        const bar = box.querySelector('.pl-controls');
        bar.innerHTML = `
    <div class="pl-seekwrap" id="pl-seekwrap">
      <div class="pl-preview" id="pl-preview" hidden>
        <div class="pl-thumb" id="pl-thumb">
          <video id="pl-thumb-video" muted playsinline preload="auto" tabindex="-1"></video>
          <canvas id="pl-thumb-canvas" width="288" height="162" hidden></canvas>
        </div>
        <span id="pl-preview-time">0:00</span>
      </div>
      <div class="pl-rail"><div class="pl-buf" id="pl-buf"></div><div class="pl-hover" id="pl-hoverfill"></div><div class="pl-played" id="pl-played"></div></div>
      <div class="pl-knob" id="pl-knob"></div>
      <input id="pl-seek" class="pl-seek" type="range" min="0" max="1000" step="1" value="0" aria-label="Seek">
    </div>
    <div class="pl-row">
      <div class="pl-left">
        <button id="pl-play" type="button" aria-label="Play (k)" title="Play / pause (k)">${PI.play}</button>
        <button id="pl-back10" type="button" aria-label="Back ${PLAYER_UI.skipSeconds} seconds" title="Back ${PLAYER_UI.skipSeconds}s (j)">${PI.back}</button>
        <button id="pl-fwd10" type="button" aria-label="Forward ${PLAYER_UI.skipSeconds} seconds" title="Forward ${PLAYER_UI.skipSeconds}s (l)">${PI.fwd}</button>
        <div class="pl-vol">
          <button id="pl-mute" type="button" aria-label="Mute (m)" title="Mute (m)">${PI.volHigh}</button>
          <input id="pl-volume" class="pl-volume" type="range" min="0" max="1" step="0.05" value="1" aria-label="Volume">
        </div>
        <span id="pl-time" class="pl-time">0:00 / 0:00</span>
      </div>
      <div class="pl-right">
        <button id="pl-server-btn" type="button" aria-label="Servers" title="Servers">${PI.server}</button>
        <button id="pl-speed-btn" type="button" class="pl-textbtn" aria-label="Speed" title="Speed (&lt; and &gt;)">1×</button>
        <button id="pl-subs-btn" type="button" aria-label="Subtitles" title="Subtitles (c)">${PI.cc}</button>
        <button id="pl-quality-btn" type="button" aria-label="Quality" title="Quality" hidden>${PI.gear}</button>
        <button id="pl-pip" type="button" aria-label="Picture in picture" title="Picture in picture (p)">${PI.pip}</button>
        <button id="pl-full" type="button" aria-label="Fullscreen" title="Fullscreen (f)">${PI.full}</button>
      </div>
    </div>`;

        if (!box.querySelector('#pl-spinner')) box.insertAdjacentHTML('beforeend', '<div id="pl-spinner" class="pl-spinner" aria-hidden="true"></div><div id="pl-osd" class="pl-osd" hidden></div><div class="pl-menu" id="pl-speed" hidden></div><div class="pl-menu" id="pl-servers" hidden></div>');
        const big = pel('pl-bigplay');
        if (big) big.innerHTML = PI.play;
    }

// ---- small helpers --------------------------------------------------------------------------------------------------
    let osdTimer = null;

    function osd(text) {
        const el = pel('pl-osd');
        if (!el) return;
        el.textContent = text;
        el.hidden = false;
        clearTimeout(osdTimer);
        osdTimer = setTimeout(() => el.hidden = true, 900);
    }

    let toastTimer = null;

    function pToast(msg) {
        const t = pel('pl-toast');
        if (!t) return;
        t.textContent = msg || '';
        t.hidden = !msg;
        clearTimeout(toastTimer);
        // a finished message (Resumed, Synced...) goes after 2.2 s; a "working…" message waits for its result but never longer than 8 s
        if (msg) toastTimer = setTimeout(() => t.hidden = true, /…$/.test(msg) ? 8000 : 2200);
    }

    function seekBy(seconds) {
        const v = vid();
        if (!v || !v.duration) return;
        v.currentTime = Math.min(v.duration, Math.max(0, v.currentTime + seconds));
        osd(`${seconds > 0 ? '+' : '−'}${Math.abs(seconds)}s`);
        wakePlayer();
    }

    function setVolume(x, announce = true) {
        const v = vid();
        v.volume = Math.min(1, Math.max(0, x));
        v.muted = v.volume === 0;
        store.set('volume', v.volume);
        store.set('muted', v.muted);
        paintVolume();
        if (announce) osd(v.muted ? 'Muted' : `Volume ${Math.round(v.volume * 100)}%`);
    }

    function toggleMute() {
        const v = vid();
        v.muted = !v.muted;
        if (!v.muted && v.volume === 0) v.volume = 0.5;
        store.set('muted', v.muted);
        paintVolume();
        osd(v.muted ? 'Muted' : `Volume ${Math.round(v.volume * 100)}%`);
    }

    function paintVolume() {
        const v = vid(), slider = pel('pl-volume'), btn = pel('pl-mute');
        if (!v || !slider || !btn) return;
        const level = v.muted ? 0 : v.volume;
        slider.value = level;
        slider.style.setProperty('--v', (level * 100) + '%');
        btn.innerHTML = level === 0 ? PI.volMute : level < 0.5 ? PI.volLow : PI.volHigh;
    }

    function setSpeed(rate, announce = true) {
        const v = vid();
        v.playbackRate = rate;
        store.set('speed', rate);
        const btn = pel('pl-speed-btn');
        if (btn) btn.textContent = `${rate}×`;
        pel('pl-speed')?.querySelectorAll('.pl-opt').forEach(b => b.classList.toggle('on', Number(b.dataset.rate) === rate));
        if (announce) osd(`Speed ${rate}×`);
    }

    function stepSpeed(dir) {
        const list = PLAYER_UI.speeds, now = vid().playbackRate;
        const i = list.findIndex(s => s >= now - 0.001);
        const next = list[Math.min(list.length - 1, Math.max(0, (i < 0 ? list.length - 1 : i) + dir))];
        setSpeed(next);
    }

    function buildSpeedMenu() {
        const menu = pel('pl-speed');
        menu.replaceChildren(...PLAYER_UI.speeds.map(rate => {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'pl-opt';
            b.dataset.rate = rate;
            b.textContent = rate === 1 ? 'Normal' : `${rate}×`;
            b.onclick = () => {
                setSpeed(rate);
                hidePlayerMenus();
            };
            return b;
        }));
    }

// ---- menus (one open at a time) -------------------------------------------------------------------------------------
    const MENU_IDS = ['pl-quality', 'pl-subs', 'pl-speed', 'pl-servers'];

    function togglePlayerMenu(id) {
        const m = pel(id);
        if (!m) return;
        const wasOpen = !m.hidden;
        hidePlayerMenus();
        m.hidden = wasOpen;
        if (!wasOpen) wakePlayer();
    }

    function hidePlayerMenus() {
        MENU_IDS.forEach(id => {
            const m = pel(id);
            if (m) m.hidden = true;
        });
    }

// ---- embed mode -----------------------------------------------------------------------------------------------------
// While the fallback iframe is on screen the bar is hidden (see player-ui.css): the embed has its own controls and
// ours sat on top of them, swallowing every click. Two things stay reachable in a corner chip, so the viewer is never
// stuck with no way out: the server list, and a way back to our own player.
    let embedChip = null;

    function inEmbed() {
        const box = playerShell();
        return !!box && box.classList.contains('embed');
    }

    function refreshEmbedUi() {
        const box = playerShell();
        if (!box) return;
        if (box.classList.contains('embed')) {
            if (embedChip) return;
            embedChip = document.createElement('div');
            embedChip.className = 'pl-embedbar';
            const servers = document.createElement('button');
            servers.type = 'button';
            servers.textContent = 'Servers';
            servers.onclick = e => {
                e.stopPropagation();
                buildServerMenu();
                togglePlayerMenu('pl-servers');
            };
            const back = document.createElement('button');
            back.type = 'button';
            back.textContent = 'Use our player';
            back.onclick = e => {
                e.stopPropagation();
                hidePlayerMenus();
                // no source at all? playSource retries the relay, which is what the viewer is asking for anyway
                window.ruinPlayer?.playSource(streamSources.length ? Math.min(sourceIndex, streamSources.length - 1) : 0);
            };
            embedChip.append(servers, back);
            box.appendChild(embedChip);
        } else if (embedChip) {
            embedChip.remove();
            embedChip = null;
            hidePlayerMenus();
        }
    }

// ---- hover preview on the seek bar (Browser Cache API -> Supabase -> the owning daemon) ----------------------------
    const TRICK_CACHE_NAME = 'ruin-trickplay-v1';

    const thumb = {
        hls: null, url: '', ready: false, loading: false, want: null,
        lastAim: 0, trail: null, timer: null, stopTimer: null, rvfc: 0, attempt: 0,
        failedAt: '', failedTime: 0, sprite: null, trickToken: 0, trickId: null,
    };

    function destroyThumb() {
        clearTimeout(thumb.timer);
        clearTimeout(thumb.trail);
        clearTimeout(thumb.stopTimer);
        thumb.attempt++;
        if (thumb.hls) {
            try {
                thumb.hls.destroy();
            } catch (e) { /* already gone */
            }
            thumb.hls = null;
        }
        thumb.loading = false;
        thumb.ready = false;
        thumb.url = '';
    }

    function resetPreview() {
        thumb.trickToken++;
        thumb.trickId = null;
        if (thumb.sprite?.vttBlobUrl) {
            URL.revokeObjectURL(thumb.sprite.vttBlobUrl);
        }
        if (thumb.sprite?.imgs) {
            thumb.sprite.imgs.forEach(entry => {
                if (entry?.blobUrl) URL.revokeObjectURL(entry.blobUrl);
            });
        }
        thumb.sprite = null;
        thumb.want = null;
        destroyThumb();

        const holder = pel('pl-thumb');
        if (holder) holder.style.removeProperty('aspect-ratio');
        const canvas = pel('pl-thumb-canvas');
        if (canvas) {
            canvas.hidden = true;
            const ctx = canvas.getContext('2d');
            if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
        }
        const tv = pel('pl-thumb-video');
        if (tv) tv.hidden = false;
    }

// ---- sheets ---------------------------------------------------------------------------------------------------------
    function parseSpriteVtt(text, baseUrl) {
        const cues = [];
        const re = /(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})[^\n]*\r?\n([^\r\n]+)/g;
        let m;
        while ((m = re.exec(text))) {
            const line = m[9].trim();
            const at = line.indexOf('#xywh=');
            if (at < 0) continue;
            const box = line.slice(at + 6).split(',').map(Number);
            if (box.length < 4 || box.some(n => !Number.isFinite(n))) continue;
            const rawRef = line.slice(0, at);
            const abs = /^https?:\/\//i.test(rawRef) ? rawRef : new URL(rawRef, baseUrl).href;
            cues.push({
                start: +m[1] * 3600 + +m[2] * 60 + +m[3] + +m[4] / 1000,
                end: +m[5] * 3600 + +m[6] * 60 + +m[7] + +m[8] / 1000,
                abs,
                x: box[0], y: box[1], w: box[2], h: box[3],
            });
        }
        return cues.sort((a, b) => a.start - b.start);
    }

    function cueAt(cues, t) {
        let lo = 0, hi = cues.length - 1, found = null;
        while (lo <= hi) {
            const mid = (lo + hi) >> 1;
            if (cues[mid].start <= t) {
                found = cues[mid];
                lo = mid + 1;
            } else hi = mid - 1;
        }
        return found;
    }

    function decodeBlobImage(blobUrl) {
        return new Promise(resolve => {
            const img = new Image();
            img.onload = () => resolve(img);
            img.onerror = () => resolve(null);
            img.src = blobUrl;
        });
    }

    async function fetchSheetBlobCached(sheetUrl) {
        const isCdn = /^https:\/\/lh3\.googleusercontent\.com\//i.test(sheetUrl);
        if (isCdn && 'caches' in window) {
            try {
                const cache = await caches.open(TRICK_CACHE_NAME);
                const hit = await cache.match(sheetUrl);
                if (hit) return await hit.blob();
                const res = await fetch(sheetUrl);
                if (!res.ok) return null;
                await cache.put(sheetUrl, res.clone());
                return await res.blob();
            } catch {
                /* fall back to direct fetch */
            }
        }
        const res = await fetch(sheetUrl);
        return res.ok ? await res.blob() : null;
    }

    function preloadSheet(sp, cue) {
        if (!cue) return Promise.resolve(null);
        const existing = sp.imgs.get(cue.abs);
        if (existing) return existing.promise;

        const entry = {blobUrl: null, img: null, promise: null};
        entry.promise = fetchSheetBlobCached(cue.abs)
            .then(async blob => {
                if (!blob) {
                    sp.imgs.delete(cue.abs);
                    return null;
                }
                const url = URL.createObjectURL(blob);
                if (thumb.sprite !== sp) {
                    URL.revokeObjectURL(url);
                    return null;
                }
                const decoded = await decodeBlobImage(url);
                if (!decoded || thumb.sprite !== sp) {
                    URL.revokeObjectURL(url);
                    sp.imgs.delete(cue.abs);
                    return null;
                }
                entry.blobUrl = url;
                entry.img = decoded;
                return entry;
            })
            .catch(() => {
                sp.imgs.delete(cue.abs);
                return null;
            });

        sp.imgs.set(cue.abs, entry);
        return entry.promise;
    }

    function preloadAround(sp, cue) {
        const i = sp.cues.indexOf(cue);
        if (i < 0) return;
        const step = (sp.cols || 10) * (sp.rows || 10);
        [i - step, i - 1, i + 1, i + step].forEach(n => preloadSheet(sp, sp.cues[n]));
    }

    function drawSpriteFrame(canvas, sp, cue, entry) {
        if (canvas.width !== sp.w || canvas.height !== sp.h) {
            canvas.width = sp.w;
            canvas.height = sp.h;
        }
        const holder = pel('pl-thumb');
        if (holder) holder.style.aspectRatio = `${sp.w} / ${sp.h}`;
        canvas.hidden = false;

        const img = entry?.img;
        if (!img || !img.naturalWidth) return;
        const sx = Math.max(0, Math.min(cue.x, img.naturalWidth - 1));
        const sy = Math.max(0, Math.min(cue.y, img.naturalHeight - 1));
        const sw = Math.min(cue.w, img.naturalWidth - sx);
        const sh = Math.min(cue.h, img.naturalHeight - sy);
        if (sw <= 0 || sh <= 0) return;

        const ctx = canvas.getContext('2d');
        if (ctx) ctx.drawImage(img, sx, sy, sw, sh, 0, 0, sp.w, sp.h);
    }

    function paintSprite(t) {
        const canvas = pel('pl-thumb-canvas');
        const sp = thumb.sprite;
        if (!canvas || !sp) return;
        const cue = cueAt(sp.cues, t);
        if (!cue) return;

        const entry = sp.imgs.get(cue.abs);
        if (entry?.img) {
            drawSpriteFrame(canvas, sp, cue, entry);
        } else {
            if (canvas.width !== sp.w || canvas.height !== sp.h) {
                canvas.width = sp.w;
                canvas.height = sp.h;
            }
            const holder = pel('pl-thumb');
            if (holder) holder.style.aspectRatio = `${sp.w} / ${sp.h}`;
            canvas.hidden = false;
            const ctx = canvas.getContext('2d');
            if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);

            preloadSheet(sp, cue).then(loaded => {
                if (!loaded || thumb.sprite !== sp || thumb.want == null) return;
                const wantedCue = cueAt(sp.cues, thumb.want);
                if (wantedCue?.abs === cue.abs) {
                    drawSpriteFrame(canvas, sp, wantedCue, loaded);
                }
            });
        }
        preloadAround(sp, cue);
    }

    function preloadSpriteSheets(sp, token) {
        (async () => {
            const uniqueCues = [];
            const seen = new Set();
            for (const c of sp.cues) {
                if (!seen.has(c.abs)) {
                    seen.add(c.abs);
                    uniqueCues.push(c);
                }
            }
            for (let i = 0; i < uniqueCues.length; i += 3) {
                if (token !== thumb.trickToken || thumb.sprite !== sp) break;
                await Promise.all(uniqueCues.slice(i, i + 3).map(c => preloadSheet(sp, c)));
            }
        })();
    }

    function mergeSpriteCues(vttText, baseUrl, meta, token) {
        const cues = parseSpriteVtt(vttText, baseUrl);
        if (!cues.length || token !== thumb.trickToken) return false;

        const existing = thumb.sprite;
        if (existing && existing.w === cues[0].w && existing.h === cues[0].h) {
            existing.cues = cues;
            existing.cols = meta.cols || existing.cols;
            existing.rows = meta.rows || existing.rows;
            if (thumb.want != null) paintSprite(thumb.want);
            preloadSpriteSheets(existing, token);
            return true;
        }

        if (existing?.vttBlobUrl) URL.revokeObjectURL(existing.vttBlobUrl);
        if (existing?.imgs) {
            existing.imgs.forEach(entry => {
                if (entry?.blobUrl) URL.revokeObjectURL(entry.blobUrl);
            });
        }

        const sp = {
            cues,
            cols: meta.cols || 10,
            rows: meta.rows || 10,
            w: cues[0].w,
            h: cues[0].h,
            imgs: new Map(),
            vttBlobUrl: null,
        };
        thumb.sprite = sp;
        destroyThumb();

        const tv = pel('pl-thumb-video');
        if (tv) {
            tv.pause();
            tv.removeAttribute('src');
            tv.hidden = true;
        }
        const canvas = pel('pl-thumb-canvas');
        if (canvas) canvas.hidden = false;

        if (thumb.want != null) paintSprite(thumb.want);
        preloadSpriteSheets(sp, token);
        return true;
    }

    // Which daemon owns the sprites: the relay builds them from a provider stream it already resolved, but a local
    // file has no relay job at all, so it asks the library - which cuts them from the file on disk.
    function trickOrigin(src) {
        if (src?.local) {
            try {
                return new URL(src.url).origin;
            } catch (e) { /* fall through */
            }
        }
        return getRelayBase();
    }

    // The library indexes files per title, not per source list position, so the index has to come out of the URL.
    function trickFileIndex(src) {
        const hit = /\/(?:file|stream)\/\d+\/(\d+)/.exec(src?.url || '');
        return hit ? hit[1] : String(sourceIndex);
    }

    async function startSheets() {
        const src = streamSources?.[sourceIndex];
        const movieId = playerMovie?.id;
        if (!src?.url || !movieId) return;
        if (thumb.trickId === movieId) return;
        thumb.trickId = movieId;

        const token = ++thumb.trickToken;
        const vttCacheKey = `https://ruin.local/trick-vtt/${movieId}.vtt`;

        // 1. Browser Cache API (instant on repeat visits, 0 network requests)
        if ('caches' in window) {
            try {
                const cache = await caches.open(TRICK_CACHE_NAME);
                const cachedVtt = await cache.match(vttCacheKey);
                if (cachedVtt) {
                    const vttText = await cachedVtt.text();
                    if (token !== thumb.trickToken) return;
                    const ok = mergeSpriteCues(vttText, vttCacheKey, {cols: 10, rows: 10}, token);
                    if (ok) return;
                }
            } catch {
                /* fall through to Supabase */
            }
        }

        // 2. Supabase permanent index -> Google Drive CDN (bypasses ffmpeg completely)
        const sbUrl = (typeof SUPABASE_URL !== 'undefined' && SUPABASE_URL) || PLAYER_UI.supabaseUrl;
        const sbKey = (typeof SUPABASE_KEY !== 'undefined' && SUPABASE_KEY) || PLAYER_UI.supabaseKey;
        if (sbUrl && sbKey) {
            try {
                const sbRes = await fetch(
                    `${sbUrl.replace(/\/+$/, '')}/rest/v1/trickplay?tmdb_id=eq.${encodeURIComponent(movieId)}&select=vtt_text,cols,rows,w,h`,
                    {
                        headers: {
                            apikey: sbKey,
                            Authorization: `Bearer ${sbKey}`,
                        },
                    }
                );
                if (sbRes.ok && token === thumb.trickToken) {
                    const rows = await sbRes.json();
                    const row = Array.isArray(rows) ? rows[0] : null;
                    if (row?.vtt_text) {
                        if ('caches' in window) {
                            caches.open(TRICK_CACHE_NAME)
                                .then(c => c.put(vttCacheKey, new Response(row.vtt_text, {headers: {'Content-Type': 'text/vtt'}})))
                                .catch(() => {
                                });
                        }
                        const ok = mergeSpriteCues(row.vtt_text, vttCacheKey, row, token);
                        if (ok) return;
                    }
                }
            } catch {
                /* fall through to the daemon */
            }
        }

        // 3. First time ever: the owning daemon cuts the sheets with ffmpeg
        const base = trickOrigin(src);
        const q = new URLSearchParams({
            id: movieId,
            i: trickFileIndex(src),
            secs: String(src.seconds || 0),
        });

        let lastFrames = 0;
        for (let attempt = 0; attempt < 180 && token === thumb.trickToken; attempt++) {
            let info;
            try {
                const res = await fetch(`${base}/trick?${q}`);
                if (!res.ok) {
                    // nothing to build from right now; let a later hover try again instead of latching the movie
                    thumb.trickId = null;
                    return;
                }
                info = await res.json();
            } catch {
                thumb.trickId = null;
                return;
            }
            if (token !== thumb.trickToken) return;

            if (info.state === 'ready') {
                const vttUrl = new URL(info.vtt, base + '/').href;
                if (info.frames !== lastFrames || !info.building) {
                    lastFrames = info.frames;
                    const bustUrl = `${vttUrl}${vttUrl.includes('?') ? '&' : '?'}_=${Date.now()}`;
                    const vttRes = await fetch(bustUrl).catch(() => null);
                    if (vttRes && vttRes.ok && token === thumb.trickToken) {
                        const vttText = await vttRes.text();
                        if (!info.building && 'caches' in window && vttText.includes('lh3.googleusercontent.com')) {
                            caches.open(TRICK_CACHE_NAME)
                                .then(c => c.put(vttCacheKey, new Response(vttText, {headers: {'Content-Type': 'text/vtt'}})))
                                .catch(() => {
                                });
                        }
                        mergeSpriteCues(vttText, vttUrl, info, token);
                    }
                }
                if (!info.building) return;
            } else if (info.state === 'failed') {
                thumb.trickId = null;
                return;
            }
            await new Promise(r => setTimeout(r, 2500));
        }
    }

// ---- the video fallback ---------------------------------------------------------------------------------------------
    function bufferedAt(tv, t) {
        for (let i = 0; i < tv.buffered.length; i++) {
            if (tv.buffered.start(i) <= t + 0.15 && tv.buffered.end(i) >= t - 0.15) return true;
        }
        return false;
    }

    function paintTarget() {
        const tv = pel('pl-thumb-video');
        if (!tv || thumb.want == null || thumb.sprite) return;
        let target = thumb.want;
        const ranges = tv.seekable;
        if (ranges && ranges.length) {
            const lo = ranges.start(0), hi = ranges.end(ranges.length - 1);
            if (target < lo) target = lo;
            else if (target > hi) target = hi;
        }
        if (Math.abs((tv.currentTime || 0) - target) > 0.2) {
            try {
                tv.currentTime = target;
            } catch (e) { /* ignore */
            }
        }
        watchForFrame(target);
    }

    function watchForFrame(target) {
        const tv = pel('pl-thumb-video');
        clearTimeout(thumb.timer);
        if (!tv) return;
        const attempt = ++thumb.attempt;
        const done = () => {
            if (attempt === thumb.attempt) thumb.lastFrame = performance.now();
        };
        thumb.lastFrame = thumb.lastFrame || 0;
        if (typeof tv.requestVideoFrameCallback === 'function') {
            if (thumb.rvfc) {
                try {
                    tv.cancelVideoFrameCallback(thumb.rvfc);
                } catch (e) { /* ignore */
                }
            }
            thumb.rvfc = tv.requestVideoFrameCallback(done);
        }
        thumb.timer = setTimeout(() => {
            if (attempt !== thumb.attempt) return;
            if (performance.now() - thumb.lastFrame < 900) return;
            if (bufferedAt(tv, target)) {
                watchForFrame(target);
                return;
            }
            if (thumb.hls) {
                thumb.loading = true;
                thumb.hls.startLoad(target);
            }
            watchForFrame(target);
        }, 900);
    }

    function startThumbLoad(t) {
        if (!thumb.hls || thumb.loading) return;
        thumb.loading = true;
        thumb.hls.startLoad(Math.max(0, t || 0));
    }

    function ensureThumb() {
        const src = streamSources?.[sourceIndex];
        const url = src?.url;
        const tv = pel('pl-thumb-video');
        if (!url || !tv || thumb.sprite) return false;
        clearTimeout(thumb.stopTimer);

        if (thumb.url === url) {
            if (thumb.hls && !thumb.loading) startThumbLoad(thumb.want || 0);
            return thumb.ready;
        }
        if (!thumb.url && thumb.failedAt === url && performance.now() - thumb.failedTime < 3000) return false;

        destroyThumb();
        thumb.url = url;

        if (src?.kind === 'mp4') {
            tv.src = url;
            thumb.ready = true;
            return true;
        }

        const native = tv.canPlayType('application/vnd.apple.mpegurl');
        if (!native && typeof Hls !== 'undefined' && Hls.isSupported()) {
            const h = new Hls({
                autoStartLoad: false,
                maxBufferLength: 24,
                maxMaxBufferLength: 60,
                backBufferLength: 45,
                maxBufferSize: 48 * 1000 * 1000,
                enableWorker: false,
                lowLatencyMode: false,
            });
            thumb.hls = h;
            h.loadSource(url);
            h.attachMedia(tv);
            h.on(Hls.Events.MANIFEST_PARSED, () => {
                let low = 0;
                h.levels.forEach((l, i) => {
                    if ((l.height || 1e9) < (h.levels[low].height || 1e9)) low = i;
                });
                h.currentLevel = low;
                thumb.ready = true;
                startThumbLoad(thumb.want || 0);
                paintTarget();
            });
            h.on(Hls.Events.ERROR, (_, d) => {
                if (!d.fatal) return;
                thumb.failedAt = url;
                thumb.failedTime = performance.now();
                destroyThumb();
            });
        } else {
            tv.src = url;
            thumb.ready = true;
        }
        return false;
    }

    function showPreview(clientX) {
        const v = vid(), wrap = pel('pl-seekwrap'), box = pel('pl-preview');
        if (!v?.duration || !wrap) return;
        const r = wrap.getBoundingClientRect();
        const frac = Math.min(1, Math.max(0, (clientX - r.left) / r.width));
        const t = frac * v.duration;
        box.hidden = false;
        pel('pl-preview-time').textContent = fmtTime(t);
        pel('pl-hoverfill').style.width = (frac * 100) + '%';
        const half = box.offsetWidth / 2;
        box.style.left = Math.min(r.width - half, Math.max(half, frac * r.width)) + 'px';

        thumb.want = t;
        startSheets();
        if (thumb.sprite) {
            paintSprite(t);
            return;
        }
        ensureThumb();
        const now = performance.now();
        if (now - thumb.lastAim > 80) {
            thumb.lastAim = now;
            paintTarget();
        } else {
            clearTimeout(thumb.trail);
            thumb.trail = setTimeout(() => {
                thumb.lastAim = performance.now();
                paintTarget();
            }, 90);
        }
    }

    function hidePreview() {
        const box = pel('pl-preview');
        if (box) box.hidden = true;
        const f = pel('pl-hoverfill');
        if (f) f.style.width = '0';
        clearTimeout(thumb.trail);
        clearTimeout(thumb.stopTimer);
        thumb.stopTimer = setTimeout(() => {
            if (thumb.hls && thumb.loading) {
                thumb.hls.stopLoad();
                thumb.loading = false;
            }
        }, 5000);
    }

// ---- subtitles ------------------------------------------------------------------------------------------------------
    let extSub = null;
    let extSubBlobUrl = null;
    let subsResults = [], subsLang = store.get('subLang', 'ar'), subsStatus = '', subsOpen = false;
    let subsLoadedForKey = '';
    let nativeSubIndex = -1;

    function handleServerSwitch() {
        syncToken++;
        extSub = null;
        nativeSubIndex = -1;
        subsLoadedForKey = '';
        clearExtTrack();
        if (hls) hls.subtitleTrack = -1;
        store.set('subsOn', false);
        paintSubsButton();
        buildSubtitleMenu();
    }

    function decodeSubtitleBuffer(buf) {
        let raw = new TextDecoder('utf-8').decode(buf);
        if (raw.includes('\uFFFD') && !/[\u0600-\u06FF]/.test(raw)) {
            raw = new TextDecoder('windows-1256').decode(buf);
        }
        return raw;
    }

    function srtToVtt(text) {
        const clean = String(text).replace(/^\uFEFF/, '').replace(/\r+/g, '').trim();
        const body = clean.replace(/^\d+\s*\n(?=\d{1,2}:\d{2}:\d{2}[,.]\d{3}\s*-->)/gm, '');
        const vtt = /^WEBVTT/.test(body)
            ? body
            : 'WEBVTT\n\n' + body.replace(/(\d{1,2}:\d{2}:\d{2}),(\d{3})/g, '$1.$2');
        return vtt.replace(
            /(?:^|\n\n)(?:\d+\n)?\d{1,2}:\d{2}:0[0-9]\.\d{3}\s*-->\s*\d{1,2}:\d{2}:0[0-9]\.\d{3}[^\n]*\n[\s\S]*?(?:sub\.wyzie\.io|free plan\. Unlock every source)[\s\S]*?(?=\n\n|$)/gi,
            ''
        );
    }

    function enforceSingleSubTrack() {
        const v = vid();
        if (!v) return;
        const own = v.querySelector('track[data-ext]')?.track || null;
        if (extSub) {
            if (hls && hls.subtitleTrack !== -1) hls.subtitleTrack = -1;
            [...v.textTracks].forEach(t => {
                if (t === own) {
                    if (t.mode !== 'showing') t.mode = 'showing';
                } else if (t.mode !== 'disabled') {
                    t.mode = 'disabled';
                }
            });
        }
    }

    function clearExtTrack() {
        const v = vid();
        if (v) {
            v.querySelectorAll('track[data-ext], track[data-ruin-ext]').forEach(t => t.remove());
        }
        if (extSubBlobUrl) {
            URL.revokeObjectURL(extSubBlobUrl);
            extSubBlobUrl = null;
        }
    }

    function placeCues(track) {
        [...(track.cues || [])].forEach(c => {
            if (c.snapToLines === false && c.line === 82) return;
            c.snapToLines = false;
            c.line = 82;
            c.align = 'center';
        });
    }

// ---- subtitle timing & whole-movie affine sync -------------------------------------------------------------------------
    const offKey = () => {
        const provider = streamSources?.[sourceIndex]?.provider || streamSources?.[sourceIndex]?.label || sourceIndex || 0;
        return `subSync.${playerMovie ? playerMovie.id : 0}.${provider}.${extSub ? extSub.key : ''}`;
    };
    let subOffset = 0;
    let subScale = 1.0;

    function transformVtt(vtt, scale, offsetSecs, isArabic = false) {
        let out = vtt;
        if (scale !== 1 || offsetSecs) {
            const fmt = t => {
                t = Math.max(0, t);
                const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), sec = t % 60;
                return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${sec.toFixed(3).padStart(6, '0')}`;
            };
            const num = (h, m, sec, ms) => Number(h) * 3600 + Number(m) * 60 + Number(sec) + Number(ms) / 1000;
            out = out.replace(/(?:(\d{1,2}):)?(\d{2}):(\d{2})\.(\d{3})/g, (_, h, m, sec, ms) => {
                const raw = num(h || 0, m, sec, ms);
                return fmt(raw * scale + offsetSecs);
            });
        }
        if (!isArabic) return out;
        return out.split('\n').map(line => {
            const trimmed = line.trim();
            if (!trimmed || trimmed === 'WEBVTT' || trimmed.includes('-->') || /^(NOTE|STYLE|REGION)\b/.test(trimmed)) {
                return line;
            }
            if (/[\u0600-\u06FF]/.test(line) && !line.startsWith('\u202B')) {
                return `\u202B${line}\u202C`;
            }
            return line;
        }).join('\n');
    }

    function vttStarts(vtt) {
        const out = [];
        const re = /(?:(\d{1,2}):)?(\d{2}):(\d{2})\.(\d{3})\s*-->/g;
        let m;
        while ((m = re.exec(vtt))) {
            out.push(Number(m[1] || 0) * 3600 + Number(m[2]) * 60 + Number(m[3]) + Number(m[4]) / 1000);
        }
        return out.sort((a, b) => a - b);
    }

    function solveAffineSync(refStarts, subStarts) {
        if (refStarts.length < 30 || subStarts.length < 25) return null;

        const near = (arr, t) => {
            let lo = 0, hi = arr.length - 1;
            while (lo < hi) {
                const mid = (lo + hi) >> 1;
                if (arr[mid] < t) lo = mid + 1; else hi = mid;
            }
            return Math.min(Math.abs(arr[lo] - t), lo ? Math.abs(arr[lo - 1] - t) : 1e9);
        };

        const subIsSparter = subStarts.length <= refStarts.length;
        const queryArr = subIsSparter ? subStarts : refStarts;
        const targetArr = subIsSparter ? refStarts : subStarts;

        const step = Math.max(1, Math.floor(queryArr.length / 260));
        const sample = queryArr.filter((_, idx) => idx % step === 0);

        const scales = [1.0, 24 / 23.976, 23.976 / 24, 25 / 23.976, 23.976 / 25];
        let best = {scale: 1.0, offset: 0, hits: 0, err: Infinity};
        let secondHits = 0;

        const gapAt = (q, scale, d) => subIsSparter
            ? near(targetArr, scale * q + d)
            : near(targetArr, (q - d) / scale);

        for (const scale of scales) {
            for (let d = -300; d <= 300.001; d += 0.2) {
                let hits = 0, err = 0;
                for (const q of sample) {
                    const gap = gapAt(q, scale, d);
                    if (gap <= 0.45) {
                        hits++;
                        err += gap;
                    }
                }
                if (hits > best.hits || (hits === best.hits && err < best.err)) {
                    if (Math.abs(d - best.offset) > 1.8 || scale !== best.scale) {
                        secondHits = Math.max(secondHits, best.hits);
                    }
                    best = {scale, offset: Math.round(d * 100) / 100, hits, err};
                } else if (Math.abs(d - best.offset) > 1.8 || scale !== best.scale) {
                    secondHits = Math.max(secondHits, hits);
                }
            }
        }

        let fine = {...best};
        for (let d = best.offset - 0.5; d <= best.offset + 0.501; d += 0.025) {
            let hits = 0, err = 0;
            for (const q of sample) {
                const gap = gapAt(q, best.scale, d);
                if (gap <= 0.30) {
                    hits++;
                    err += gap;
                }
            }
            if (hits > fine.hits || (hits === fine.hits && err < fine.err)) {
                fine = {scale: best.scale, offset: Math.round(d * 100) / 100, hits, err};
            }
        }

        const confident = fine.hits >= Math.max(8, sample.length * 0.22) && fine.hits >= secondHits * 1.35;
        return confident ? fine : null;
    }

    async function fetchFullReferenceVtt() {
        const src = streamSources?.[sourceIndex];
        const refPlaylistUrl = src?.meta?.refSubProxied
            || (hls?.subtitleTracks || []).find(t => /^en/i.test(t.lang || '') || /english/i.test(t.name || ''))?.url
            || hls?.subtitleTracks?.[0]?.url;

        let embeddedVtt = null;
        if (refPlaylistUrl) {
            try {
                const res = await fetch(refPlaylistUrl);
                if (res.ok) {
                    const body = await res.text();
                    if (!body.includes('#EXTM3U')) {
                        embeddedVtt = body;
                    } else {
                        const segs = body.split('\n').map(l => l.trim()).filter(l => l && !l.startsWith('#'));
                        if (segs.length) {
                            const fractions = [0, 0.12, 0.25, 0.4, 0.55, 0.7, 0.85, 0.96];
                            const picks = [...new Set(fractions.map(f => segs[Math.min(segs.length - 1, Math.floor(segs.length * f))]))];
                            const parts = await Promise.all(
                                picks.map(u => fetch(new URL(u, refPlaylistUrl).toString()).then(r => r.ok ? r.text() : '').catch(() => ''))
                            );
                            embeddedVtt = parts.filter(Boolean).join('\n\n');
                        }
                    }
                }
            } catch { /* fall through to external English anchor */
            }
        }

        if (embeddedVtt && vttStarts(embeddedVtt).length >= 30) {
            return embeddedVtt;
        }

        if (!playerMovie || /^en/i.test(extSub?.lang || '')) return null;
        try {
            const relayBase = getRelayBase();
            const meta = await resolveMovieMeta();
            const q = new URLSearchParams({
                id: playerMovie.id,
                lang: 'en',
                secs: String(src?.seconds || 0),
                runtime: String((meta.runtime || 0) * 60),
            });
            if (meta.imdb_id) q.set('imdb', meta.imdb_id);
            const listRes = await fetch(`${relayBase}/subs?${q}`);
            if (!listRes.ok) return null;
            const enList = await listRes.json();
            const bestEn = Array.isArray(enList) && enList.find(x => x.url);
            if (!bestEn) return null;
            const subRes = await fetch(bestEn.url);
            if (!subRes.ok) return null;
            return srtToVtt(decodeSubtitleBuffer(await subRes.arrayBuffer()));
        } catch {
            return null;
        }
    }

    let syncToken = 0;

    async function autoSync() {
        const token = ++syncToken, v = vid();
        if (!extSub) return false;

        let refStarts = [];
        const refVtt = await fetchFullReferenceVtt();
        if (token !== syncToken) {
            enforceSingleSubTrack();
            return false;
        }

        if (refVtt) {
            refStarts = vttStarts(refVtt);
        } else if (hls && hls.subtitleTracks?.length) {
            const tracks = hls.subtitleTracks;
            const ref = tracks.findIndex(t => /^en/i.test(t.lang || '') || /english/i.test(t.name || ''));
            hls.subtitleTrack = ref >= 0 ? ref : 0;
            for (let i = 0; i < 10 && token === syncToken; i++) {
                await new Promise(r => setTimeout(r, 800));
                const own = v.querySelector('track[data-ext]')?.track;
                const refs = [...v.textTracks].filter(x => x !== own);
                refs.forEach(x => x.mode = 'hidden');
                const tt = refs.sort((x, y) => (y.cues ? y.cues.length : 0) - (x.cues ? x.cues.length : 0))[0];
                if (!tt) continue;
                refStarts = [...(tt.cues || [])].map(c => c.startTime).sort((a, b) => a - b);
                if (refStarts.length >= 30) break;
            }
            if (hls) hls.subtitleTrack = -1;
            enforceSingleSubTrack();
            if (token !== syncToken) return false;
        }

        if (refStarts.length < 30) {
            applyExtSub();
            return false;
        }

        const subStarts = vttStarts(extSub.vtt);
        // solveAffineSync is the one place a typo can strand the whole flow: autoSync is async and every
        // caller chains .then without a catch, so a throw here left the toast up forever and no subtitle
        // applied. Fail into the "low confidence" path instead.
        let fit = null;
        try {
            fit = solveAffineSync(refStarts, subStarts);
        } catch (err) {
            console.warn('subsync solve:', err);
        }
        window.subsyncInfo = {refCues: refStarts.length, fileCues: subStarts.length, fit};
        console.info('[subsync]', window.subsyncInfo);

        if (!fit) {
            applyExtSub();
            pToast('Auto-sync: low confidence on this file. Try the ★ Best Match subtitle.');
            return null;
        }

        subScale = fit.scale;
        subOffset = fit.offset;
        store.set(offKey(), {scale: subScale, offset: subOffset});
        applyExtSub();
        buildSubtitleMenu();
        return true;
    }

    function setSubOffset(value, resetScale = false) {
        if (resetScale) subScale = 1.0;
        subOffset = Math.round(Math.max(-300, Math.min(300, value)) * 100) / 100;
        store.set(offKey(), {scale: subScale, offset: subOffset});
        if (extSub) applyExtSub();
        osd(`Subtitles ${subOffset === 0 ? 'in sync' : (subOffset > 0 ? 'delayed ' : 'earlier ') + Math.abs(subOffset).toFixed(1) + 's'}`);
        buildSubtitleMenu();
    }

    function applyExtSub() {
        const v = vid();
        clearExtTrack();
        nativeSubIndex = -1;
        if (!extSub) return;
        const isArabic = /^ar/i.test(extSub.lang || '');
        const t = document.createElement('track');
        t.kind = 'subtitles';
        t.label = extSub.label;
        t.srclang = extSub.lang || 'ar';
        t.dataset.ext = '1';
        extSubBlobUrl = URL.createObjectURL(new Blob([transformVtt(extSub.vtt, subScale, subOffset, isArabic)], {type: 'text/vtt;charset=utf-8'}));
        t.src = extSubBlobUrl;
        v.appendChild(t);
        t.track.mode = 'showing';
        t.addEventListener('load', () => {
            placeCues(t.track);
            enforceSingleSubTrack();
        });
        enforceSingleSubTrack();
    }

    function turnSubsOff() {
        const v = vid();
        syncToken++;
        extSub = null;
        nativeSubIndex = -1;
        clearExtTrack();
        if (hls) hls.subtitleTrack = -1;
        [...v.textTracks].forEach(x => x.mode = 'disabled');
        store.set('subsOn', false);
        paintSubsButton();
    }

    function subsActive() {
        const v = vid();
        return !!extSub || nativeSubIndex >= 0 || (hls && hls.subtitleTrack >= 0)
            || [...(v?.textTracks || [])].some(t => t.mode === 'showing');
    }

    function paintSubsButton() {
        pel('pl-subs-btn')?.classList.toggle('on', subsActive());
    }

    function selectEmbeddedSubtitle(index) {
        const v = vid();
        syncToken++;
        extSub = null;
        nativeSubIndex = -1;
        clearExtTrack();
        if (hls) hls.subtitleTrack = index;
        [...(v?.textTracks || [])].forEach((x, i) => {
            x.mode = i === index ? 'showing' : 'disabled';
        });
        paintSubsButton();
        hidePlayerMenus();
        buildSubtitleMenu();
    }

    function selectNativeSubtitle(index) {
        const v = vid();
        if (!v) return;
        syncToken++;
        extSub = null;
        clearExtTrack();
        if (hls) hls.subtitleTrack = -1;
        nativeSubIndex = index;
        [...v.textTracks].forEach((x, i) => {
            x.mode = i === index ? 'showing' : 'disabled';
        });
        paintSubsButton();
        hidePlayerMenus();
        buildSubtitleMenu();
    }

    function loadLocalSubtitleFile() {
        const inp = document.createElement('input');
        inp.type = 'file';
        inp.accept = '.srt,.vtt,text/plain';
        inp.onchange = async () => {
            const file = inp.files?.[0];
            if (!file) return;
            try {
                const raw = decodeSubtitleBuffer(await file.arrayBuffer());
                const vtt = srtToVtt(raw);
                const cuesCount = vttStarts(vtt).length;
                if (!cuesCount) {
                    pToast('No valid subtitle timestamps found in that file.');
                    return;
                }
                const isAr = /[\u0600-\u06FF]/.test(vtt);
                extSub = {
                    label: file.name.replace(/\.(srt|vtt|txt)$/i, ''),
                    lang: isAr ? 'ar' : subsLang,
                    vtt,
                    key: `local:${file.name}:${file.size}`,
                };
                const saved = store.get(offKey(), null);
                if (saved && typeof saved === 'object' && (saved.offset || Math.abs((saved.scale || 1) - 1) > 1e-5)) {
                    subScale = saved.scale || 1.0;
                    subOffset = saved.offset || 0;
                } else {
                    subScale = 1.0;
                    subOffset = (typeof saved === 'number' && saved !== 0) ? saved : 0;
                }
                applyExtSub();
                store.set('subsOn', true);
                subsStatus = '';
                hidePlayerMenus();
                paintSubsButton();
                buildSubtitleMenu();
                pToast(`Loaded (${cuesCount} cues): ${extSub.label}`);

                const hasRef = Boolean(
                    streamSources?.[sourceIndex]?.meta?.hasRefSubs
                    || (hls && hls.subtitleTracks?.length)
                    || !/^en/i.test(extSub.lang || '')
                );
                const hasNonZeroSaved = subOffset !== 0 || Math.abs(subScale - 1) > 1e-5;
                if (!hasNonZeroSaved && hasRef && cuesCount >= 25) {
                    pToast('Syncing local subtitle across full runtime…');
                    autoSync().then(ok => {
                        if (ok) {
                            const fpsNote = Math.abs(subScale - 1) > 1e-5 ? ` · FPS ×${subScale.toFixed(4)}` : '';
                            pToast(`Synced (${subOffset >= 0 ? '+' : ''}${subOffset.toFixed(2)}s${fpsNote})`);
                        } else if (ok === false) {
                            pToast(`Loaded: ${extSub.label}`);
                        }
                    });
                }
            } catch (err) {
                console.warn('local subtitle load:', err);
                pToast('Could not read that subtitle file.');
            }
        };
        inp.click();
    }

    async function searchSubtitles() {
        subsStatus = 'Matching subtitles to active source…';
        subsResults = [];
        buildSubtitleMenu();
        try {
            const activeSrc = streamSources?.[sourceIndex];
            const meta = await resolveMovieMeta();
            const relayBase = getRelayBase();
            const relTags = [
                ...(activeSrc?.meta?.tags || []),
                activeSrc?.direct || ''
            ].filter(Boolean).join(' ');
            const q = new URLSearchParams({
                id: playerMovie.id,
                lang: subsLang,
                secs: String(activeSrc?.seconds || 0),
                runtime: String((meta.runtime || 0) * 60),
            });
            if (relTags) q.set('rel', relTags);
            if (meta.imdb_id) q.set('imdb', meta.imdb_id);
            if (PLAYER_UI.subsKey) q.set('key', PLAYER_UI.subsKey);

            subsLoadedForKey = `${playerMovie.id}:${sourceIndex}:${subsLang}`;

            const ctl = new AbortController();
            const abortTimer = setTimeout(() => ctl.abort(), 90000);
            let r = await fetch(`${relayBase}/subs?${q}`, {signal: ctl.signal}).catch(() => null);
            clearTimeout(abortTimer);
            if ((!r || !r.ok) && PLAYER_UI.subsKey) {
                const directQ = new URLSearchParams({
                    id: meta.imdb_id || playerMovie.id,
                    language: subsLang,
                    format: 'srt',
                    source: 'all',
                    key: PLAYER_UI.subsKey,
                });
                r = await fetch(`${PLAYER_UI.subsEndpoint}?${directQ}`);
            }
            if (!r) throw new Error('Could not reach the subtitle service.');
            if (r.status === 429) throw new Error('The subtitle service is out of free requests for today.');
            if (r.status === 401 || r.status === 403) throw new Error('The subtitle key was refused. Check PLAYER_UI.subsKey.');
            if (!r.ok) throw new Error(r.status === 404 ? 'No subtitles found for this movie in that language.' : `Subtitle service error (${r.status}).`);

            const list = await r.json();
            subsResults = (Array.isArray(list) ? list : []).filter(s => s.url);
            subsStatus = subsResults.length ? '' : 'No subtitles found for this movie in that language.';
        } catch (err) {
            if (err.name === 'AbortError') {
                subsStatus = 'The subtitle search timed out. Try again, or pick a single language.';
            } else {
                console.warn('subtitle search:', err);
                subsStatus = err.message || 'Could not reach the subtitle service.';
            }
        }
        buildSubtitleMenu();
    }

    async function chooseSubtitle(s) {
        subsStatus = 'Loading & aligning subtitle…';
        buildSubtitleMenu();
        try {
            const r = await fetch(s.url);
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const vtt = srtToVtt(decodeSubtitleBuffer(await r.arrayBuffer()));
            if (/^ar/i.test(s.language || subsLang) && !/[\u0600-\u06FF]/.test(vtt)) {
                throw new Error('That file has no Arabic text in it. Try another result.');
            }
            extSub = {label: s.display || s.language || 'Subtitles', lang: s.language || subsLang, vtt, key: s.url};
            const saved = store.get(offKey(), null);
            if (saved && typeof saved === 'object' && (saved.offset || Math.abs((saved.scale || 1) - 1) > 1e-5)) {
                subScale = saved.scale || 1.0;
                subOffset = saved.offset || 0;
            } else {
                subScale = 1.0;
                subOffset = (typeof saved === 'number' && saved !== 0) ? saved : 0;
            }
            applyExtSub();
            store.set('subsOn', true);
            subsStatus = '';
            hidePlayerMenus();
            pToast(`Subtitles: ${extSub.label}`);

            const hasRef = Boolean(
                streamSources?.[sourceIndex]?.meta?.hasRefSubs
                || (hls && hls.subtitleTracks?.length)
                || !/^en/i.test(extSub.lang || '')
            );
            const hasNonZeroSaved = subOffset !== 0 || Math.abs(subScale - 1) > 1e-5;
            if (!hasNonZeroSaved && hasRef) {
                pToast('Syncing subtitles across full runtime…');
                autoSync().then(ok => {
                    if (ok) {
                        const fpsNote = Math.abs(subScale - 1) > 1e-5 ? ` · FPS ×${subScale.toFixed(4)}` : '';
                        pToast(`Synced (${subOffset >= 0 ? '+' : ''}${subOffset.toFixed(2)}s${fpsNote})`);
                    } else if (ok === false) {
                        pToast(`Subtitles: ${extSub.label}`);
                    }
                });
            }
        } catch (err) {
            console.warn('subtitle download:', err);
            subsStatus = err.message && err.message.startsWith('That file') ? err.message : 'That subtitle could not be loaded. Try another one.';
        }
        paintSubsButton();
        buildSubtitleMenu();
    }

    function buildSubtitleMenu() {
        const menu = pel('pl-subs'), btn = pel('pl-subs-btn');
        if (!menu) return;
        if (btn) btn.hidden = false;
        const el = (tag, cls, text) => {
            const e = document.createElement(tag);
            if (cls) e.className = cls;
            if (text) e.textContent = text;
            return e;
        };
        const opt = (label, on, fn) => {
            const b = el('button', 'pl-opt' + (on ? ' on' : ''), label);
            b.type = 'button';
            b.onclick = e => {
                e.stopPropagation();
                fn();
            };
            return b;
        };
        const parts = [];
        parts.push(opt('Off', !subsActive(), () => {
            turnSubsOff();
            hidePlayerMenus();
            buildSubtitleMenu();
        }));
        const native = streamSources?.[sourceIndex]?.subtitles || [];
        native.forEach((t, i) => parts.push(opt(t.label || t.lang || `Track ${i + 1}`, !extSub && nativeSubIndex === i, () => {
            selectNativeSubtitle(i);
        })));
        const tracks = hls ? hls.subtitleTracks : [];
        tracks.forEach((t, i) => parts.push(opt(t.name || t.lang || `Track ${i + 1}`, !extSub && hls.subtitleTrack === i, () => {
            selectEmbeddedSubtitle(i);
        })));
        if (extSub) {
            parts.push(opt(`✓ ${extSub.label}`, true, () => hidePlayerMenus()));
            const row = el('div', 'pl-sync');
            const fpsTag = Math.abs(subScale - 1) > 1e-5 ? ` · ×${subScale.toFixed(3)}` : '';
            row.appendChild(el('span', 'pl-sync-label', (subOffset ? `Sync ${subOffset > 0 ? '+' : ''}${subOffset.toFixed(1)}s` : 'Sync') + fpsTag));
            [['−5', -5], ['−0.5', -0.5], ['−0.1', -0.1], ['+0.1', 0.1], ['+0.5', 0.5], ['+5', 5]].forEach(([t, d]) => {
                const b = el('button', 'pl-step', t);
                b.type = 'button';
                b.title = d < 0 ? 'Show subtitles earlier' : 'Show subtitles later';
                b.onclick = e => {
                    e.stopPropagation();
                    setSubOffset(subOffset + d);
                };
                row.appendChild(b);
            });
            const resync = el('button', 'pl-step', 'Auto');
            resync.type = 'button';
            resync.title = 'Re-run full-movie auto-sync';
            resync.onclick = e => {
                e.stopPropagation();
                pToast('Syncing subtitles across full runtime…');
                autoSync().then(ok => {
                    if (ok) {
                        const fpsNote = Math.abs(subScale - 1) > 1e-5 ? ` · FPS ×${subScale.toFixed(4)}` : '';
                        pToast(`Synced (${subOffset >= 0 ? '+' : ''}${subOffset.toFixed(2)}s${fpsNote})`);
                    } else if (ok === false) {
                        pToast('No reference track available to auto-sync against.');
                    }
                });
            };
            row.appendChild(resync);
            const reset = el('button', 'pl-step', 'Reset');
            reset.type = 'button';
            reset.onclick = e => {
                e.stopPropagation();
                setSubOffset(0, true);
            };
            row.appendChild(reset);
            parts.push(row);
            parts.push(el('div', 'pl-note', 'Late subtitles? Press − (or G). Early? Press + (or H).'));
        }

        parts.push(el('div', 'pl-sep'));
        parts.push(opt('↑ Load subtitle file (.srt / .vtt)', false, () => loadLocalSubtitleFile()));
        parts.push(opt(subsOpen ? '▾ Find subtitles' : '▸ Find subtitles', false, () => {
            subsOpen = !subsOpen;
            const currentKey = `${playerMovie?.id}:${sourceIndex}:${subsLang}`;
            if (subsOpen && (!subsResults.length || subsLoadedForKey !== currentKey)) searchSubtitles();
            else buildSubtitleMenu();
        }));
        if (subsOpen) {
            const sel = el('select', 'pl-lang');
            sel.setAttribute('aria-label', 'Subtitle language');
            PLAYER_UI.subLanguages.forEach(([code, name]) => {
                const o = el('option', '', name);
                o.value = code;
                o.selected = code === subsLang;
                sel.appendChild(o);
            });
            sel.onclick = e => e.stopPropagation();
            sel.onchange = () => {
                subsLang = sel.value;
                store.set('subLang', subsLang);
                searchSubtitles();
            };
            parts.push(sel);
            if (subsStatus) parts.push(el('div', 'pl-note', subsStatus));
            const list = el('div', 'pl-sublist');
            subsResults.slice(0, 30).forEach(s => {
                const line = (s.bestMatch ? '★ ' : '')
                    + (s.release || s.fileName || s.display || 'Subtitle')
                    + (s.isHearingImpaired ? '  (HI)' : '');
                const b = opt(line, false, () => chooseSubtitle(s));
                b.title = line;
                if (s.downloadCount) b.dataset.count = `${Number(s.downloadCount).toLocaleString('en-US')} downloads`;
                list.appendChild(b);
            });
            parts.push(list);
        }
        menu.replaceChildren(...parts);
        paintSubsButton();
    }

// ---- marking a copy as a recording ----------------------------------------------------------------------------------
// relay.py keeps this per title + provider (cam_marks.json) and ranks a marked copy dead last. A CAM token in the URL
// can be read by a guess; whether a file is a phone pointed at a screen cannot. This is how the viewer says so, and how
// a wrong guess gets corrected. The relay's own guess arrives as meta.cam_guess and is shown with a question mark, so a
// guess is never mistaken for a certainty.
    const CAM_TOKENS = ['hdcam', 'camrip', 'hqcam', 'cam', 'telesync', 'telecine', 'hdts', 'dvdscr', 'screener', 'workprint', 'pdvd'];

    function looksCam(src) {
        const blob = `${src?.direct || ''} ${(src?.meta?.tags || []).join(' ')}`.toLowerCase();
        if (CAM_TOKENS.some(token => blob.includes(token))) return true;
        return /(?:^|[\s\-_.\[(])ts(?:[\s\-_.\])]|$)/.test(blob);
    }

    function firstDigitalIndex(except) {
        return streamSources.findIndex((s, i) => i !== except && !s.meta?.cam && !isLocal(s));
    }

    async function markSource(index, cam) {
        const src = streamSources?.[index], movieId = playerMovie?.id;
        if (!src || !movieId) return;
        const before = {cam: src.meta?.cam, mark: src.meta?.cam_mark};

        // the row changes at once; the relay is told next
        src.meta = src.meta || {};
        if (cam) {
            src.meta.cam = true;
            src.meta.cam_mark = true;
        } else {
            delete src.meta.cam_mark;
            delete src.meta.cam_guess;
            if (looksCam(src)) src.meta.cam = true; else delete src.meta.cam;
        }
        buildServerMenu();

        const q = new URLSearchParams({id: movieId, p: src.provider || '', cam: cam ? '1' : '0'});
        let ok = false;
        try {
            const res = await fetch(`${getRelayBase()}/mark?${q}`);
            ok = res.ok;
        } catch { /* relay unreachable */
        }

        if (!ok) {
            if (before.mark) src.meta.cam_mark = true; else delete src.meta.cam_mark;
            if (before.cam) src.meta.cam = true; else if (!src.meta.cam_mark) delete src.meta.cam;
            buildServerMenu();
            pToast('Could not save that mark. Is the relay running?');
            return;
        }

        if (!cam) {
            pToast(`${src.label} marked as digital.`);
            return;
        }
        pToast(`${src.label} marked as a recording.`);
        // the copy on screen is the one that was just called out: leave it if anything digital is left
        if (index === sourceIndex) {
            const better = firstDigitalIndex(index);
            if (better > -1) {
                pToast('Switching to a digital copy.');
                window.ruinPlayer?.playSource(better);
            }
        }
    }

// ---- grabbing a digital copy (grab.py) ------------------------------------------------------------------------------
// The last resort in the server menu: nothing that is playing is worth watching, so fetch a file. grab.py resolves the
// IMDb id to a YTS torrent and files the video into the library folder itself, which is why the sources are re-resolved
// on completion instead of the file being streamed from staging.
    let grabJob = null, grabTimer = null, grabText = 'Get a digital copy', grabBusy = false;

    function paintGrab(text, busy) {
        grabText = text;
        grabBusy = busy;
        const btn = pel('pl-grab-btn');
        if (!btn) return;
        btn.textContent = text;
        btn.disabled = busy;
    }

    async function startGrab() {
        const movieId = playerMovie?.id;
        if (!movieId || grabBusy) return;
        paintGrab('Looking for a torrent…', true);
        try {
            const res = await fetch(`${getGrabBase()}/grab`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({tmdb: Number(movieId)}),
            });
            const job = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(job.error || `HTTP ${res.status}`);
            grabJob = job;
            pollGrab();
        } catch (err) {
            paintGrab('Get a digital copy', false);
            pToast(`Grab: ${err.message || 'failed'}`);
        }
    }

    async function pollGrab() {
        clearTimeout(grabTimer);
        if (!grabJob?.id) return;
        let job = null;
        try {
            const res = await fetch(`${getGrabBase()}/queue`);
            const list = await res.json();
            job = (Array.isArray(list) ? list : []).find(j => j.id === grabJob.id) || null;
        } catch { /* grab not running */
        }
        if (!job) {
            grabTimer = setTimeout(pollGrab, 4000);
            return;
        }
        if (job.state === 'done') {
            paintGrab('Filed. Reloading sources…', false);
            pToast(`Filed: ${(job.path || 'done').split(/[\\/]/).pop()}`);
            grabJob = null;
            window.ruinPlayer?.resolveStreams?.();
            return;
        }
        if (job.state === 'failed' || job.state === 'cancelled') {
            paintGrab('Get a digital copy', false);
            pToast(`Grab ${job.state}${job.error ? ': ' + job.error : ''}`);
            grabJob = null;
            return;
        }
        paintGrab(job.state === 'downloading'
            ? `Downloading ${job.progress_pct}%${job.speed_h ? ' · ' + job.speed_h : ''}`
            : job.state === 'handed_off' ? 'Magnet handed over — it files itself'
                : 'Working…', true);
        grabTimer = setTimeout(pollGrab, 2500);
    }

// ---- servers (script.js drives pollMoreSources and calls buildServerMenu when new sources arrive) ------------------
    function isLocal(src) {
        return Boolean(src?.local) || src?.provider === 'library';
    }

    function buildServerMenu() {
        const menu = pel('pl-servers');
        if (!menu) return;
        const sel = pel('server-switcher');
        const parts = [];
        if (!streamSources.length) {
            const n = document.createElement('div');
            n.className = 'pl-note';
            n.textContent = 'No servers answered yet.';
            parts.push(n);
        }
        // Local files first, then digital, then recordings. The order is for the MENU only: sourceIndex and the hidden
        // select keep script.js's own order, so the row the viewer is playing never shifts under them.
        const rankOf = src => isLocal(src) ? 0 : src.meta?.cam ? 2 : 1;
        const order = streamSources.map((_, i) => i).sort((a, b) =>
            (rankOf(streamSources[a]) - rankOf(streamSources[b])) || (a - b));

        order.forEach(i => {
            const src = streamSources[i];
            const local = isLocal(src);
            const row = document.createElement('div');
            row.className = 'pl-server-row';

            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'pl-opt' + (i === sourceIndex ? ' on' : '');
            // a cam recording is spelled out: 1080p CAM reads worse than 480p digital, so the height alone misleads
            const tag = local ? 'LOCAL · '
                : src.meta?.cam_mark ? 'CAM (marked) · '
                    : src.meta?.cam_guess ? 'CAM? · '
                        : src.meta?.cam ? 'CAM · ' : '';
            const res = src.meta?.height ? `${src.meta.height}p · ` : '';
            const kind = src.kind === 'mp4' ? 'MP4 · ' : '';
            b.textContent = `${src.label} · ${tag}${res}${kind}${fmtTime(src.seconds)}`;
            b.classList.toggle('is-cam', !local && !!src.meta?.cam);
            if (local) b.style.color = '#8fd6a0';
            b.onclick = e => {
                e.stopPropagation();
                hidePlayerMenus();
                handleServerSwitch();
                if (i === sourceIndex || !sel) return;
                sel.value = String(i);
                sel.onchange && sel.onchange();
            };
            row.appendChild(b);

            // a file on this machine is digital by definition, so only network sources take the chip
            if (!local) {
                const mark = document.createElement('button');
                mark.type = 'button';
                mark.className = 'pl-mark' + (src.meta?.cam_mark ? ' on' : '');
                mark.textContent = src.meta?.cam_mark ? '✓' : 'CAM';
                mark.title = src.meta?.cam_mark
                    ? 'Marked as a recording — tap to clear'
                    : 'Mark this copy as a recording of a cinema screen';
                mark.setAttribute('aria-label', mark.title);
                mark.setAttribute('aria-pressed', String(!!src.meta?.cam_mark));
                mark.onclick = e => {
                    e.stopPropagation();
                    markSource(i, !src.meta?.cam_mark);
                };
                row.appendChild(mark);
            }
            parts.push(row);
        });

        if (playerMovie?.id) {
            const grab = document.createElement('div');
            grab.style.cssText = 'display:flex;padding:6px 2px 2px';
            const gbtn = document.createElement('button');
            gbtn.id = 'pl-grab-btn';
            gbtn.type = 'button';
            gbtn.textContent = grabText;
            gbtn.disabled = grabBusy;
            gbtn.style.cssText = 'flex:1 1 auto;padding:7px 10px;border-radius:8px;background:#151515;'
                + 'border:1px solid rgba(255,255,255,0.16);color:#ddd;font:700 11px Montserrat,sans-serif;'
                + 'cursor:pointer;text-align:left';
            gbtn.onclick = e => {
                e.stopPropagation();
                startGrab();
            };
            grab.appendChild(gbtn);
            parts.push(grab);
        }

        const note = document.createElement('div');
        note.className = 'pl-note';
        note.textContent = 'CAM = recorded off a cinema screen. Tap CAM to mark a copy, so it sinks below the digital ones.';
        parts.push(note);

        menu.replaceChildren(...parts);
    }

// ---- quality (hls.js levels of the source that is playing, not the source list) -------------------------------------
    // hls.js only fills level.height/width when the variant playlist carries a RESOLUTION attribute. Several
    // sources leave it out, which is exactly where the old "?p" came from. Read the attribute directly instead.
    function levelHeight(level) {
        if (!level) return 0;
        const fromAttrs = Number((level.attrs?.RESOLUTION || '').split('x')[1]) || 0;
        return level.height || fromAttrs || 0;
    }

    // Never print a bare "?": resolution first, then width, then bitrate, then the track number.
    function levelLabel(level, index) {
        const h = levelHeight(level);
        if (h) return `${h}p`;
        const w = level.width || Number((level.attrs?.RESOLUTION || '').split('x')[0]) || 0;
        if (w) return `${w}w`;
        const kbps = Math.round((level.bitrate || 0) / 1000);
        if (kbps > 0) return kbps >= 1000 ? `${(kbps / 1000).toFixed(1)} Mbps` : `${kbps} kbps`;
        return `Track ${index + 1}`;
    }

    // A rendition is audio-only only when it is provably so: it declares an audio codec and no video codec.
    // A master with no CODECS or RESOLUTION attributes leaves both empty, and those levels are real video,
    // so they have to survive. Calling them audio-only is what made the gear vanish on some sources.
    function isAudioLevel(level) {
        if (!level) return true;
        if (level.videoCodec) return false;
        if (level.width || levelHeight(level)) return false;
        return Boolean(level.audioCodec);
    }

    // The gear keeps its icon; this only ever fills the small readout beside it.
    function setQualityButtonText(text) {
        const btn = pel('pl-quality-btn');
        if (!btn) return;
        let label = btn.querySelector('.pl-quality-label');
        if (!label) {
            label = document.createElement('span');
            label.className = 'pl-quality-label';
            btn.appendChild(label);
        }
        label.textContent = text;
        btn.title = `Quality: ${text}`;
    }

    // On Auto the readout names the quality actually in use, and it follows every downgrade or upgrade live
    // ("Auto · 1080p" becomes "Auto · 720p" the moment the switcher drops). Picking a level shows that level alone.
    function activeQualityText() {
        const level = hls && hls.currentLevel >= 0 ? hls.levels[hls.currentLevel] : null;
        if (hls?.autoLevelEnabled) return level ? `Auto · ${levelLabel(level, hls.currentLevel)}` : 'Auto';
        return level ? levelLabel(level, hls.currentLevel) : 'Auto';
    }

    // Keeps the gear and the tick marks in step with what is actually playing, including automatic switches.
    function updateQualityUI() {
        const menu = pel('pl-quality');
        if (!hls) return;
        setQualityButtonText(activeQualityText());
        if (!menu) return;
        const active = hls.autoLevelEnabled ? -1 : hls.currentLevel;
        menu.querySelectorAll('.pl-opt').forEach(b => b.classList.toggle('on', Number(b.dataset.level) === active));
    }

    function buildQualityMenu() {
        const menu = pel('pl-quality'), btn = pel('pl-quality-btn');
        if (!menu) return;
        // highest first, and only renditions that really carry picture
        const indices = [];
        if (hls) {
            for (let i = hls.levels.length - 1; i >= 0; i--) if (!isAudioLevel(hls.levels[i])) indices.push(i);
            // a master with no CODECS/RESOLUTION makes every level look audio-only: keep them all rather than hide the gear
            if (!indices.length) for (let i = hls.levels.length - 1; i >= 0; i--) indices.push(i);
        }
        // one rendition and nothing to choose: a gear labelled "Track 1" is just clutter
        if (!hls || indices.length < 2) {
            if (btn) {
                btn.hidden = true;
                btn.querySelector('.pl-quality-label')?.remove();
            }
            menu.replaceChildren();
            return;
        }
        if (btn) btn.hidden = false;

        const opt = (label, level) => {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'pl-opt';
            b.dataset.level = String(level);
            b.textContent = label;
            b.onclick = () => {
                if (hls) hls.currentLevel = level;
                updateQualityUI();
                hidePlayerMenus();
            };
            return b;
        };

        // the real level index rides on the button so updateQualityUI can mark the right one
        menu.replaceChildren(opt('Auto', -1), ...indices.map(i => opt(levelLabel(hls.levels[i], i), i)));
        updateQualityUI();
    }

// ---- keyboard -------------------------------------------------------------------------------------------------------
    function playerKeys(e) {
        if (e.ctrlKey || e.metaKey || e.altKey) return;
        if (/^(input|textarea|select)$/i.test(document.activeElement?.tagName) && document.activeElement.id !== 'pl-seek') return;
        if (document.activeElement?.isContentEditable) return;
        // In an embed the picture belongs to someone else's player: our shortcuts would act on a <video> with no source
        // and quietly do nothing visible. Escape stays, so a menu can still be dismissed.
        if (inEmbed()) {
            if (e.key === 'Escape') hidePlayerMenus();
            return;
        }
        const v = vid();
        if (!v) return;
        const key = e.key;
        let handled = true;
        switch (key) {
            case ' ':
            case 'k':
            case 'K':
                if (document.activeElement?.tagName === 'BUTTON' && key === ' ') return;
                togglePlay();
                osd(v.paused ? 'Paused' : 'Play');
                break;
            case 'ArrowLeft':
                seekBy(-5);
                break;
            case 'ArrowRight':
                seekBy(5);
                break;
            case 'j':
            case 'J':
                seekBy(-PLAYER_UI.skipSeconds);
                break;
            case 'l':
            case 'L':
                seekBy(PLAYER_UI.skipSeconds);
                break;
            case 'ArrowUp':
                setVolume((v.muted ? 0 : v.volume) + 0.05);
                break;
            case 'ArrowDown':
                setVolume((v.muted ? 0 : v.volume) - 0.05);
                break;
            case 'm':
            case 'M':
                toggleMute();
                break;
            case 'f':
            case 'F':
                toggleFullscreen();
                break;
            case 'p':
            case 'P':
                togglePip();
                break;
            case 'g':
                if (extSub) setSubOffset(subOffset - 0.5);
                break;
            case 'h':
                if (extSub) setSubOffset(subOffset + 0.5);
                break;
            case 'c':
            case 'C':
                buildSubtitleMenu();
                togglePlayerMenu('pl-subs');
                break;
            case '<':
                stepSpeed(-1);
                break;
            case '>':
                stepSpeed(1);
                break;
            case 'Home':
                v.currentTime = 0;
                break;
            case 'End':
                if (v.duration) v.currentTime = Math.max(0, v.duration - 1);
                break;
            case 'Escape':
                hidePlayerMenus();
                handled = false;
                break;
            default:
                if (/^[0-9]$/.test(key) && v.duration) v.currentTime = (Number(key) / 10) * v.duration; else handled = false;
        }
        if (handled) {
            e.preventDefault();
            wakePlayer();
        }
    }

    function toggleFullscreen() {
        const box = playerShell(), v = vid();
        if (document.fullscreenElement) document.exitFullscreen();
        else if (box?.requestFullscreen) box.requestFullscreen().catch(() => {
        });
        else if (v?.webkitEnterFullscreen) v.webkitEnterFullscreen();
    }

    function togglePip() {
        const v = vid();
        if (!v) return;
        if (!document.pictureInPictureEnabled || v.disablePictureInPicture) return pToast('Picture-in-picture is not available here.');
        if (document.pictureInPictureElement) document.exitPictureInPicture().catch(() => {
        });
        else v.requestPictureInPicture().catch(() => {
        });
    }

// ---- wiring ---------------------------------------------------------------------------------------------------------
    let uiBound = false;

    function bindPlayerControls() {
        const v = vid(), box = playerShell();
        if (!v || !box || uiBound) return;
        uiBound = true;
        buildControls(box);
        buildSpeedMenu();

        if (!v.crossOrigin) {
            try {
                v.crossOrigin = 'anonymous';
            } catch (e) { /* already loaded; harmless */
            }
        }

        const on = (id, fn) => {
            const el = pel(id);
            if (el) el.onclick = fn;
        };

        on('pl-play', togglePlay);
        on('pl-bigplay', togglePlay);
        on('pl-back10', () => seekBy(-PLAYER_UI.skipSeconds));
        on('pl-fwd10', () => seekBy(PLAYER_UI.skipSeconds));
        on('pl-pip', togglePip);
        on('pl-full', toggleFullscreen);
        on('pl-mute', toggleMute);
        on('pl-volume', e => setVolume(Number(e.target.value), false));
        on('pl-quality-btn', e => {
            e.stopPropagation();
            togglePlayerMenu('pl-quality');
        });
        on('pl-subs-btn', e => {
            e.stopPropagation();
            buildSubtitleMenu();
            togglePlayerMenu('pl-subs');
        });
        on('pl-server-btn', e => {
            e.stopPropagation();
            buildServerMenu();
            togglePlayerMenu('pl-servers');
        });
        on('pl-speed-btn', e => {
            e.stopPropagation();
            togglePlayerMenu('pl-speed');
        });
        MENU_IDS.forEach(id => pel(id)?.addEventListener('click', e => e.stopPropagation()));

        v.volume = store.get('volume', 1);
        v.muted = store.get('muted', false);
        paintVolume();
        setSpeed(store.get('speed', 1), false);
        buildSubtitleMenu();

        const seek = pel('pl-seek'), wrap = pel('pl-seekwrap');
        seek.addEventListener('input', () => {
            if (v.duration) v.currentTime = (Number(seek.value) / 1000) * v.duration;
            paintTime();
        });
        wrap.addEventListener('pointermove', e => showPreview(e.clientX));
        wrap.addEventListener('pointerleave', hidePreview);
        wrap.addEventListener('pointerdown', e => showPreview(e.clientX));
        wrap.addEventListener('pointerup', e => {
            if (e.pointerType !== 'mouse') setTimeout(hidePreview, 600);
        });

        const thumbVideo = pel('pl-thumb-video');
        ['loadeddata', 'progress', 'canplay', 'durationchange', 'seeked'].forEach(ev => thumbVideo?.addEventListener(ev, () => {
            if (thumb.want != null) paintTarget();
        }));

        const paintTime = () => {
            const d = v.duration || 0, t = v.currentTime || 0;
            const played = d ? (t / d) * 100 : 0;
            let buffered = 0;
            for (let i = 0; i < v.buffered.length; i++) if (v.buffered.start(i) <= t + 0.5 && v.buffered.end(i) >= t) buffered = d ? (v.buffered.end(i) / d) * 100 : 0;
            if (document.activeElement !== seek || !seek.matches(':active')) seek.value = d ? Math.round((t / d) * 1000) : 0;
            pel('pl-played').style.width = played + '%';
            pel('pl-knob').style.left = played + '%';
            pel('pl-buf').style.width = Math.max(played, buffered) + '%';
            pel('pl-time').textContent = `${fmtTime(t)} / ${fmtTime(d)}`;
            seek.setAttribute('aria-valuetext', `${fmtTime(t)} of ${fmtTime(d)}`);
        };
        v.addEventListener('timeupdate', paintTime);
        v.addEventListener('progress', paintTime);
        v.addEventListener('durationchange', paintTime);

        v.addEventListener('play', () => {
            pel('pl-play').innerHTML = PI.pause;
            pel('pl-bigplay').innerHTML = PI.play;
            box.classList.add('playing');
            wakePlayer();
        });
        v.addEventListener('pause', () => {
            pel('pl-play').innerHTML = PI.play;
            box.classList.remove('playing', 'idle');
        });
        v.addEventListener('ended', () => {
            box.classList.remove('playing', 'idle');
        });
        v.addEventListener('waiting', () => box.classList.add('buffering'));
        ['playing', 'canplay', 'pause', 'emptied'].forEach(ev => v.addEventListener(ev, () => box.classList.remove('buffering')));
        v.addEventListener('emptied', () => {
            resetPreview();
            handleServerSwitch();
        });
        v.addEventListener('volumechange', paintVolume);
        v.addEventListener('ratechange', () => {
            const btn = pel('pl-speed-btn');
            if (btn) btn.textContent = `${v.playbackRate}×`;
        });
        v.textTracks.addEventListener('addtrack', e => {
            e.track.addEventListener('cuechange', () => placeCues(e.track));
            enforceSingleSubTrack();
        });
        v.textTracks.addEventListener('change', enforceSingleSubTrack);
        v.addEventListener('loadedmetadata', () => {
            v.playbackRate = store.get('speed', 1);
            ensureThumb();
            startSheets();
            if (extSub) {
                const saved = store.get(offKey(), null);
                if (saved && typeof saved === 'object' && (saved.offset || Math.abs((saved.scale || 1) - 1) > 1e-5)) {
                    subScale = saved.scale || 1.0;
                    subOffset = saved.offset || 0;
                    applyExtSub();
                } else {
                    subScale = 1.0;
                    subOffset = (typeof saved === 'number' && saved !== 0) ? saved : 0;
                    applyExtSub();
                    if (!subOffset) autoSync();
                }
            }
            buildSubtitleMenu();
            buildServerMenu();
            paintTime();
        });
        let seekSave = null;
        v.addEventListener('seeked', () => {
            clearTimeout(seekSave);
            seekSave = setTimeout(saveProgress, 1500);
            paintSubsButton();
        });

        let clickTimer = null;
        v.addEventListener('click', e => {
            if (!hidePlayerMenusIfOpen()) {
                clearTimeout(clickTimer);
                clickTimer = setTimeout(() => {
                    if (matchMedia('(hover: none)').matches && box.classList.contains('idle')) wakePlayer(); else togglePlay();
                }, 230);
            }
        });
        v.addEventListener('dblclick', e => {
            clearTimeout(clickTimer);
            const r = v.getBoundingClientRect(), x = (e.clientX - r.left) / r.width;
            if (x < 0.33) seekBy(-PLAYER_UI.skipSeconds); else if (x > 0.67) seekBy(PLAYER_UI.skipSeconds); else toggleFullscreen();
        });
        box.onmousemove = wakePlayer;
        box.onmouseleave = () => {
            if (!box.querySelector('.pl-menu:not([hidden])') && !v.paused) box.classList.add('idle');
        };
        box.addEventListener('touchstart', wakePlayer, {passive: true});
        document.addEventListener('fullscreenchange', () => {
            const btn = pel('pl-full');
            if (btn) btn.innerHTML = document.fullscreenElement ? PI.exitFull : PI.full;
            box.classList.toggle('is-full', !!document.fullscreenElement);
        });

        // script.js only flips the "embed" class; this file follows it instead of script.js having to know about the UI
        new MutationObserver(refreshEmbedUi).observe(box, {attributes: true, attributeFilter: ['class']});
        refreshEmbedUi();

        document.addEventListener('keydown', playerKeys);
        document.addEventListener('click', hidePlayerMenus);
    }

    function hidePlayerMenusIfOpen() {
        const open = MENU_IDS.some(id => pel(id) && !pel(id).hidden);
        if (open) hidePlayerMenus();
        return open;
    }

    Object.assign(window, {bindPlayerControls, playerKeys, pToast, togglePlayerMenu, hidePlayerMenus, buildServerMenu});
})();