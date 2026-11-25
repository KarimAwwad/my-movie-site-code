// =====================================================================
//  RUIN.TO  -  script.js   (the logic every page shares)
//  Each page is its own .html file (index.html, login.html, horror.html ...).
//  The <body data-page="..."> attribute tells this file which page it is running on.
//
//  PLAYBACK ORDER (watch page)
//    1. the local library daemon (8788) - your own file, nothing can break it
//    2. nothing there? the grab daemon is asked for a copy straight away, behind a loading state
//    3. the buttons (providers, rescan) only appear if the fetch fails
// =====================================================================

// --- SUPABASE BACKEND SYSTEM ---
const SUPABASE_URL = 'https://eriewfiqaywpxkvpgcdo.supabase.co';
const SUPABASE_KEY = 'sb_publishable_ydTL5VTzMG_oVc2S9eZlHg_AujoCm8-';
const supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_KEY);

// LITE MODE: smart TVs and other weak devices get a plain, fast version (no decorative animation, no particles, no hero trailer).
// It switches on by itself for TV browsers; ?lite=1 forces it on, ?lite=0 forces it off (the choice is remembered on that device).
const isLite = (() => {
    try {
        const q = new URLSearchParams(location.search);
        if (q.has('lite')) localStorage.setItem('ruin.lite', q.get('lite') === '0' ? '0' : '1');
        const saved = localStorage.getItem('ruin.lite');
        const tv = /Tizen|SMART-?TV|SmartTV|Web0S|webOS|NetCast|HbbTV|BRAVIA|AFTM|AFTB|AFTT|CrKey|Roku/i.test(navigator.userAgent || '');
        const lite = saved !== null ? saved === '1' : tv;
        document.documentElement.classList.toggle('lite', lite);
        return lite;
    } catch (e) {
        return false;
    }
})();

const API_KEY = 'c8b3444f786125dd2b69a88d34202de4';
// Lite mode (TV) downloads and decodes smaller pictures: far less memory and CPU while scrolling.
const IMAGE_BASE_URL = isLite ? 'https://image.tmdb.org/t/p/w342' : 'https://image.tmdb.org/t/p/w500';
const BACKDROP_BASE_URL = isLite ? 'https://image.tmdb.org/t/p/w1280' : 'https://image.tmdb.org/t/p/original';

const endpoints = {
    trending: `https://api.themoviedb.org/3/trending/movie/week?api_key=${API_KEY}`,
    topRated: `https://api.themoviedb.org/3/movie/top_rated?api_key=${API_KEY}`
};

// Every category page (horror.html, netflix.html ...) is just a set of default filters + a title.
const categoryConfig = {
    // streaming services (ids live in the NETWORKS table in components.js, so there is only one place to edit)
    netflix: {title: 'BLOODLINE (NETFLIX)', network: 'netflix'},
    disney: {title: 'MAGIC (DISNEY+)', network: 'disney'},
    hulu: {title: 'SLUDGE (HULU)', network: 'hulu'},
    crunchyroll: {title: 'ANIME (CRUNCHYROLL)', network: 'crunchyroll'},
    max: {title: 'ABYSS (MAX)', network: 'max'},
    prime: {title: 'RELICS (PRIME VIDEO)', network: 'prime'},
    appletv: {title: 'ORCHARD (APPLE TV+)', network: 'appletv'},
    paramount: {title: 'SUMMIT (PARAMOUNT+)', network: 'paramount'},
    peacock: {title: 'PLUMAGE (PEACOCK)', network: 'peacock'},
    starz: {title: 'STARFALL (STARZ)', network: 'starz'},
    marvel: {title: 'HEROES (MARVEL)', network: 'marvel'},
    dc: {title: 'GOTHAM (DC)', network: 'dc'},
    action: {title: 'CARNAGE (ACTION)', genre: 'action'},
    horror: {title: 'NIGHTMARES (HORROR)', genre: 'horror'},
    scifi: {title: 'COSMOS (SCI-FI)', genre: 'scifi'},
    comedy: {title: 'HYSTERIA (COMEDY)', genre: 'comedy'},
    animation: {title: 'ILLUSIONS (ANIMATION)', genre: 'animation'},
    crime: {title: 'GUILT (CRIME)', genre: 'crime'},
    adventure: {title: 'EXPEDITIONS (ADVENTURE)', genre: 'adventure'},
    documentary: {title: 'TRUTHS (DOCUMENTARY)', genre: 'documentary'},
    drama: {title: 'TRAGEDIES (DRAMA)', genre: 'drama'},
    family: {title: 'HEARTH (FAMILY)', genre: 'family'},
    fantasy: {title: 'SORCERY (FANTASY)', genre: 'fantasy'},
    history: {title: 'CHRONICLES (HISTORY)', genre: 'history'},
    music: {title: 'ECHOES (MUSIC)', genre: 'music'},
    mystery: {title: 'SHADOWS (MYSTERY)', genre: 'mystery'},
    romance: {title: 'DEVOTION (ROMANCE)', genre: 'romance'},
    thriller: {title: 'DREAD (THRILLER)', genre: 'thriller'},
    war: {title: 'BATTLEFIELDS (WAR)', genre: 'war'},
    western: {title: 'DUST (WESTERN)', genre: 'western'},
    tvmovie: {title: 'BROADCASTS (TV MOVIES)', genre: 'tvmovie'},
    // special pages from the top bar
    //  trending = TMDB's own trending list (no filters apply); sort/country/minVotes/released = starting filters
    trending: {title: 'TRENDING THIS WEEK', trending: true},
    toprated: {title: 'REVERED (TOP RATED)', sort: 'rating', minVotes: 300},
    new: {title: 'FRESH BLOOD (NEW RELEASES)', sort: 'newest', minVotes: 10},
    anime: {title: 'ANIME UNIVERSE', genre: 'animation', country: 'JP'},
    tv: {title: 'SERIES (ALL SHOWS)', type: 'tv', sort: 'popular'}
};

const DEFAULT_METADATA = {
    name: 'Summoner', about: 'The abyss welcomes you.',
    avatar: '',   // empty = show the letter picture (see initialAvatar below)
    banner: ''    // empty = show the dark red gradient (see .dash-banner in style.css)
};

// The picture to show for the current user: their own upload, or the letter picture.
function avatarSrc() {
    const own = userMetadata.avatar;
    if (own && !own.includes('i.imgur.com/6Xz2eW0')) return own;         // that old default link is dead
    return initialAvatar(userMetadata.name || userProfile?.username || currentUser?.email || '');
}

// --- WHICH PAGE AM I ON, AND HOW DO PAGES LINK TO EACH OTHER? ---
const PAGE = document.body.dataset.page;   // home | category | search | login | register | dashboard

// Locally (PyCharm's server) a link has to be "profile.html". On a real host (GitHub Pages, Netlify,
// Cloudflare Pages...) "profile" works and the address bar shows /profile.
// If your host does NOT serve /profile from profile.html, change the next line to:  const CLEAN_URLS = false;
// A local address on a special port (PyCharm's 63342, python -m http.server 8000 ...) cannot do clean URLs. A local address on the
// normal port 80 means your own server.py, which does, so it gets clean URLs too.
const IS_LOCAL = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname) && location.port !== '';
const CLEAN_URLS = !IS_LOCAL;

// The folder the site lives in: "/" on a custom domain, "/my-repo/" on a GitHub Project page.
// We read it from where this very script was loaded, so nothing is hard-coded.
const APP_BASE = new URL('.', document.currentScript.src).pathname;

function pageUrl(name = '') {
    if (name === '') name = 'home';          // the home page is shown as /home (home.html and index.html are the same page)
    return APP_BASE + name + (CLEAN_URLS ? '' : '.html');
}

// If someone lands on /profile.html on a clean-URL host, tidy the address bar to /profile.
function tidyAddressBar() {
    if (!CLEAN_URLS) return;
    let clean = location.pathname.replace(/\.html$/, '');
    // the bare address (/) and /index both show as /home. (Both files exist, so a refresh on /home works everywhere.)
    if (PAGE === 'home' && (clean === APP_BASE || clean === APP_BASE + 'index' || clean === APP_BASE.replace(/\/$/, ''))) clean = APP_BASE + 'home';
    if (clean !== location.pathname) history.replaceState(null, '', clean + location.search + location.hash);
}

// The dashboard pages are protected: which page name does each tab belong to?
const DASH_PAGE_NAME = {
    overview: 'profile',
    history: 'watchhistory',
    liked: 'liked',
    watchlist: 'watchlist',
    settings: 'settings'
};
const PROTECTED_PAGE_NAMES = Object.values(DASH_PAGE_NAME);

// After logging in, we may send the person back to the page they wanted.  Only known page names are allowed
// (otherwise "?next=https://evil.site" would be an open redirect).
function nextUrl() {
    const wanted = new URLSearchParams(location.search).get('next');
    return PROTECTED_PAGE_NAMES.includes(wanted) ? pageUrl(wanted) : '';
}

// --- TAKEDOWN LIST ---
// If a movie must be taken down (for example after a complaint), put its TMDB id here and it disappears from every list and search.
// The title then disappears from every row, grid and hero, and can no longer be played.   Example: [603, 27205]
const BLOCKED_MOVIE_IDS = [];
const isBlocked = m => m.media_type !== 'tv' && BLOCKED_MOVIE_IDS.includes(m.id);   // the block list holds MOVIE ids; a series can share a number

// --- STATE ---
let currentMovie = null, heroMovie = null, currentUser = null, authToken = null;
let userMetadata = {...DEFAULT_METADATA};
let userProfile = {username: ''};   // comes from the "profiles" table (see schema.sql)
let authReady = false;                // true once Supabase has told us whether someone is logged in
let historyList = [];                 // watch history kept in memory so the UI can update instantly
let progressKnown = false;          // false until the progress lookup worked; then the Continue watching strip can show only unfinished movies
let progressMap = new Map();          // movie id -> {seconds, duration}: where the player stopped, shown on the Continue watching cards
let historyTimes = new Map();         // history key -> when it was last watched (needed to put a removed title back in place)

// A movie and a series can share the same TMDB number, so history is keyed by type + id in memory ("movie:603", "tv:76669").
// In the database the series row is stored under the NEGATIVE id (-76669): the table's key is (user_id, movie_id), so the two can
// never overwrite each other, and no table change is needed. movie_data always holds the real id and media_type.
const hkey = m => `${m.media_type === 'tv' ? 'tv' : 'movie'}:${m.id}`;
const dbId = m => m.media_type === 'tv' ? -m.id : m.id;
const isSeries = m => m.media_type === 'tv';
let historyReadyResolve = () => {};
const historyReady = new Promise(r => historyReadyResolve = r);    // resolves once the history is known (or the viewer is a guest)
// Liked (heart) and Watchlist (bookmark). Each is a Map: "movie:123" -> a slimmed-down copy of the movie.
// Maps remember insertion order, and we insert newest first, so they are already in display order.
let savedLists = {liked: new Map(), watchlist: new Map()};
const pendingSaves = new Set();       // keys being saved right now, so a double-click cannot send two requests
let renderToken = 0;                  // lets us ignore stale network responses (race conditions)

// --- SMALL HELPERS ---
// fetch() does NOT throw on HTTP errors (401, 404, 500...). We have to check res.ok ourselves.
async function tmdb(url) {
    if (url.includes('ruin_all=1')) return tmdbAllRegions(url);   // "All regions" = our own multi-country query (see below)
    const res = await fetch(url);
    if (!res.ok) throw new Error(`TMDB request failed (${res.status})`);
    return res.json();
}

// --- "CAM" BADGE: which titles are cinema-only right now? ---
// TMDB has no video-quality field, so this is an ESTIMATE built from its release dates:
//   theatrical = released in cinemas in the last 45 days
//   home       = got a digital/physical release in that same window
// "Cinema-only" = theatrical but not yet home. Those are the titles where only cinema-recorded copies are likely to exist.
// Everything else gets no badge, because we do not know its quality.
let cinemaSets = {theatrical: new Set(), home: new Set()};
let cinemaPromise = null;

function cinemaUrl(releaseTypes, page) {
    const p = new URLSearchParams({
        api_key: API_KEY, region: 'US', with_release_type: releaseTypes, sort_by: 'popularity.desc', page,
        'release_date.gte': isoDate(-45), 'release_date.lte': isoDate(0)
    });
    return `https://api.themoviedb.org/3/discover/movie?${p}`;
}

// Runs once per page load (and is cached for the rest of the day in sessionStorage). If it fails, we simply
// show no badges: a missing badge is harmless, a wrong one is not.
function loadCinemaSets() {
    if (cinemaPromise) return cinemaPromise;
    cinemaPromise = (async () => {
        const cacheKey = 'ruin_cinema_' + isoDate(0);
        try {
            const cached = JSON.parse(sessionStorage.getItem(cacheKey));
            if (cached) {
                cinemaSets = {theatrical: new Set(cached.theatrical), home: new Set(cached.home)};
                return cinemaSets;
            }
        } catch (e) { /* no storage: just fetch */
        }
        try {
            const results = await Promise.all([
                tmdb(cinemaUrl('3', 1)), tmdb(cinemaUrl('3', 2)), tmdb(cinemaUrl('4|5', 1)), tmdb(cinemaUrl('4|5', 2))
            ]);
            const ids = (a, b) => [...a.results, ...b.results].map(m => m.id);
            cinemaSets = {theatrical: new Set(ids(results[0], results[1])), home: new Set(ids(results[2], results[3]))};
            try {
                sessionStorage.setItem(cacheKey, JSON.stringify({
                    theatrical: [...cinemaSets.theatrical],
                    home: [...cinemaSets.home]
                }));
            } catch (e) { /* storage unavailable: fine */
            }
        } catch (err) {
            console.error('Could not load cinema releases (no CAM badges will be shown):', err);
        }
        return cinemaSets;
    })();
    return cinemaPromise;
}

// media_type check: a TV show's id can equal a movie's id, and TV has no cinema release types.
function isCinemaOnly(movie) {
    return movie.media_type !== 'tv' && cinemaSets.theatrical.has(movie.id) && !cinemaSets.home.has(movie.id);
}

// Gives up on the featured banner (error or nothing to show): hides it and removes its loading ghost.
function hideHero() {
    endHeroSkeleton();
    const banner = document.getElementById('hero-banner');
    if (banner) banner.style.display = 'none';
}

// Designed "nothing here" / "something went wrong" blocks. One builder for every case so they all look alike.
// kind 'error' gets a Try again button (a reload is the safest retry: it re-runs every fetch from scratch).
const STATE_ICONS = {
    error: '<svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.5l9.5 16.5h-19z"/><path d="M12 10v4.5M12 17.2v.01"/></svg>',
    empty: '<svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M5 21V11a7 7 0 0 1 14 0v10l-2.3-2-2.4 2-2.3-2-2.3 2-2.4-2z"/><path d="M9.5 11v.01M14.5 11v.01"/></svg>'
};

function stateBlock(text, compact, onRetry) {
    const isError = /refused|could not|try again|went wrong|failed/i.test(text);
    const box = document.createElement('div');
    box.className = 'state-block' + (compact ? ' compact' : '') + (isError ? ' is-error' : '');
    box.setAttribute('role', isError ? 'alert' : 'status');
    const ico = document.createElement('i');
    ico.className = 'state-ico';
    ico.setAttribute('aria-hidden', 'true');
    ico.innerHTML = isError ? STATE_ICONS.error : STATE_ICONS.empty;   // fixed markup from this file
    const body = document.createElement('div');
    body.className = 'state-body';
    const p = document.createElement('p');
    p.className = 'state-text';
    p.textContent = text;                                              // textContent never interprets HTML
    body.appendChild(p);
    if (isError) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'state-retry';
        b.textContent = 'Try again';
        b.addEventListener('click', onRetry || (() => location.reload()));
        body.appendChild(b);
    }
    box.append(ico, body);
    return box;
}

// A short note in place of a poster row's ghost cards (a plain note is better than a shimmer that never ends).
function rowMessage(id, text) {
    const el = document.getElementById(id);
    if (el) el.replaceChildren(stateBlock(text, true));
}

function showGridMessage(text) {
    const grid = document.getElementById('movie-grid');
    if (!grid) return;
    grid.innerHTML = '';
    const wrap = document.createElement('div');
    wrap.className = 'grid-message';
    wrap.appendChild(stateBlock(text, false));
    grid.appendChild(wrap);
}

// A small message at the bottom of the screen. Optional action = { label, onClick }, shown as a button (e.g. "Undo").
// It slides in, shows a thin countdown line, and leaves by itself FAST: 2 s for a plain note, 5 s when there is an Undo,
// 4 s for an error. Tap it to dismiss at once; hover (mouse) pauses it so you can reach Undo without racing the clock.
const TOAST_ICONS = {
    ok: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    err: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8v5M12 16.5v.01"/><circle cx="12" cy="12" r="9"/></svg>'
};

function showToast(text, action) {
    document.querySelectorAll('.toast').forEach(t => t._close ? t._close(true) : t.remove());   // one message at a time
    const isError = /could not|couldn't|failed|no longer|not available|error/i.test(text);
    const total = isError ? 4000 : (action ? 5000 : 2000);
    const toast = document.createElement('div');
    toast.className = 'toast' + (isError ? ' toast-error' : '');
    toast.setAttribute('role', isError ? 'alert' : 'status');
    const ico = document.createElement('i');
    ico.className = 'toast-ico';
    ico.setAttribute('aria-hidden', 'true');
    ico.innerHTML = isError ? TOAST_ICONS.err : TOAST_ICONS.ok;      // fixed markup from this file, never user text
    const span = document.createElement('span');
    span.className = 'toast-text';
    span.textContent = text;                                         // textContent never interprets HTML
    toast.append(ico, span);

    let timer = 0, left = total, startedAt = 0, gone = false;
    const close = instant => {
        if (gone) return;
        gone = true;
        clearTimeout(timer);
        if (instant || reducedMotion()) toast.remove();
        else {
            toast.classList.add('out');
            setTimeout(() => toast.remove(), 220);
        }
    };
    toast._close = close;
    const run = () => {
        startedAt = Date.now();
        timer = setTimeout(close, left);
    };
    if (action) {
        const btn = document.createElement('button');
        btn.className = 'toast-action';
        btn.textContent = action.label;
        btn.addEventListener('click', e => {
            e.stopPropagation();
            close(true);
            action.onClick();
        });
        toast.appendChild(btn);
    }
    const bar = document.createElement('b');
    bar.className = 'toast-bar';
    bar.style.animationDuration = total + 'ms';
    toast.appendChild(bar);
    toast.addEventListener('click', () => close());
    toast.addEventListener('mouseenter', () => {
        clearTimeout(timer);
        left = Math.max(1200, left - (Date.now() - startedAt));
        toast.classList.add('paused');
    });
    toast.addEventListener('mouseleave', () => {
        toast.classList.remove('paused');
        run();
    });
    document.body.appendChild(toast);
    run();
}

function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.innerText = text;
}

function setValue(id, value) {
    const el = document.getElementById(id);
    if (el) el.value = value;
}

// --- AUTHENTICATION STATE ---
supabaseClient.auth.onAuthStateChange((event, session) => {
    authToken = session ? session.access_token : null;     // kept so the position can be saved while the page is closing
    const newUser = session?.user || null;
    const userChanged = newUser?.id !== currentUser?.id;
    const firstCheck = !authReady;

    currentUser = newUser;
    // Rebuild from defaults every time, so a previous user's avatar/banner can never leak into the next session.
    userMetadata = {...DEFAULT_METADATA, ...(newUser?.user_metadata || {})};
    if (userChanged) userProfile = {username: ''};
    authReady = true;

    // Supabase warns against calling other supabase methods directly inside this callback
    // (it can deadlock), so the work is deferred to the next tick.
    setTimeout(async () => {
        if (userChanged || firstCheck || event === 'USER_UPDATED') await checkAuthUI();
        if (firstCheck) onFirstAuth();
    }, 0);
});

// Runs once per page load, as soon as we know whether someone is logged in.
function onFirstAuth() {
    if (PAGE === 'watch') recordWatchOnce();
    if (PAGE === 'series') recordSeriesOnce();
    if (PAGE === 'dashboard') {
        if (!currentUser) {   // replace() so the Back button does not bounce the person straight back
            location.replace(pageUrl('login') + '?next=' + DASH_PAGE_NAME[document.body.dataset.tab]);
            return;
        }
        hydrateUserDashboard();
    }
    if ((PAGE === 'login' || PAGE === 'register') && currentUser) {
        location.replace(nextUrl() || pageUrl(''));
    }
}

async function checkAuthUI() {
    const guest = document.getElementById('guest-account');
    const userProfileEl = document.getElementById('user-profile');
    if (!guest || !userProfileEl) return;

    const tab = document.getElementById('bar-profile');
    if (tab) {
        tab.href = pageUrl(currentUser ? 'profile' : 'login');
        const label = document.getElementById('bar-profile-label');
        if (label) label.textContent = currentUser ? 'Profile' : 'Sign in';
    }
    // Captured here: the person can sign out while these are still in flight, and the loaders dereference the id.
    const uid = currentUser?.id;
    if (uid) {
        guest.style.display = 'none';
        userProfileEl.style.display = 'flex';
        const navAvatar = document.getElementById('nav-avatar');
        if (navAvatar) navAvatar.src = avatarSrc();
        await Promise.all([loadProfile(uid), loadHistory(uid), loadSavedLists(uid)]);
        if (currentUser?.id !== uid) return;          // signed out meanwhile: nothing more to paint
        if (PAGE === 'dashboard') hydrateUserDashboard();
    } else {
        guest.style.display = '';
        userProfileEl.style.display = 'none';
        historyList = [];
        historyTimes = new Map();
        savedLists = {liked: new Map(), watchlist: new Map()};
        renderHistory();
        refreshSavedUI();
        historyReadyResolve();                         // a guest has no history to wait for
    }
}

function toggleAccountMenu(event) {
    event.stopPropagation();
    document.getElementById('account-menu')?.classList.toggle('open');
}

async function handleLogout() {
    await supabaseClient.auth.signOut();
    location.href = pageUrl('');
}

// --- USERNAMES (stored in the "profiles" table; run schema.sql once in Supabase) ---
const USERNAME_MIN = 2, USERNAME_MAX = 24;
const USERNAME_HELP = '2-24 characters. Letters, emoji, symbols, spaces: anything goes.';
// The only things refused: control characters and INVISIBLE characters (zero-width spaces, text-direction overrides,
// blank filler letters, odd spaces). They make names that look empty or flip nearby text around.
// (Emoji joiners U+200D and U+FE0F are allowed, otherwise many emoji would break.)
const INVISIBLE_RE = /[\u0000-\u001F\u007F-\u009F\u00A0\u034F\u061C\u115F\u1160\u180E\u2000-\u200C\u200E-\u200F\u2028-\u202F\u205F-\u206F\u3000\u3164\uFEFF\uFFA0\uFFF9-\uFFFB]/;

// What the person typed, tidied: normal Unicode form, no spaces at the ends, one space between words. Case and styling are kept.
const cleanUsername = raw => String(raw).normalize('NFC').trim().replace(/ {2,}/g, ' ');

// Length as a human counts it: an emoji or a stylized letter is ONE character, even when it is stored as several.
function charCount(text) {
    try {
        return [...new Intl.Segmenter(undefined, {granularity: 'grapheme'}).segment(text)].length;
    } catch (e) {
        return [...text].length;
    }
}

function validateUsername(username) {
    if (INVISIBLE_RE.test(username)) return 'That name has invisible or control characters in it. Please remove them.';
    if (!username.replace(/[\s\u200D\uFE0F_.\-]/g, '')) return 'Please use at least one visible character.';
    const n = charCount(username);
    if (n < USERNAME_MIN || n > USERNAME_MAX) return `Use ${USERNAME_MIN}-${USERNAME_MAX} characters (you used ${n}).`;
    return '';
}

// true = free, false = taken/not allowed, null = we could not ask (database not set up yet)
async function isUsernameFree(username) {
    const {data, error} = await supabaseClient.rpc('username_available', {p_username: username});
    if (error) {
        console.error('username_available failed:', error.message);
        return null;
    }
    return data === true;
}

async function loadProfile(uid = currentUser?.id) {
    if (!uid) return;
    const {
        data,
        error
    } = await supabaseClient.from('profiles').select('username').eq('id', uid).maybeSingle();
    if (error) {
        console.warn('Could not read profiles (did you run schema.sql?):', error.message);
        return;
    }
    userProfile = {username: data?.username || ''};
}

// Live "is it free?" hint under the username box. Debounced: we wait until the person stops typing
// for 400ms, otherwise we would hit the database on every keystroke.
let usernameTimer = null, usernameCheckId = 0;

function onUsernameInput(input, hintId = 'username-hint') {
    const hint = document.getElementById(hintId);
    if (!hint) return;
    const value = cleanUsername(input.value);
    clearTimeout(usernameTimer);
    const myCheck = ++usernameCheckId;

    if (value === '') {
        hint.className = 'field-hint';
        hint.textContent = USERNAME_HELP;
        return;
    }
    const problem = validateUsername(value);
    if (problem) {
        hint.className = 'field-hint bad';
        hint.textContent = problem;
        return;
    }

    hint.className = 'field-hint';
    hint.textContent = 'Checking...';
    usernameTimer = setTimeout(async () => {
        const free = await isUsernameFree(value);
        if (myCheck !== usernameCheckId) return;   // the person kept typing, this answer is already outdated
        if (free === null) {
            hint.className = 'field-hint bad';
            hint.textContent = 'Could not check right now. Try again in a moment.';
        } else if (free) {
            hint.className = 'field-hint ok';
            hint.textContent = `✓ ${value} is available`;
        } else {
            hint.className = 'field-hint bad';
            hint.textContent = `✗ ${value} is taken, too similar to an existing name, or not allowed`;
        }
    }, 400);
}

// --- LOGIN / REGISTER PAGES ---
function setAuthMessage(text, kind = 'bad') {
    const el = document.getElementById('auth-msg');
    if (!el) return;
    el.textContent = text;
    el.className = 'auth-msg ' + (text ? kind : '');
}

function setAuthBusy(busy, idleLabel) {
    const btn = document.getElementById('auth-submit');
    if (!btn) return;
    btn.disabled = busy;
    btn.textContent = busy ? 'Summoning...' : idleLabel;
}

function togglePassword(button) {
    const input = button.parentElement.querySelector('input');
    if (!input) return;
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    button.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
    button.classList.toggle('on', show);
}

// The email address a confirmation mail was sent to (kept for the "Resend" button)
let pendingEmail = '';

function showCheckInbox(email) {
    pendingEmail = email;
    document.getElementById('auth-form').style.display = 'none';
    document.getElementById('auth-success-email').textContent = email;
    document.getElementById('auth-success').style.display = 'block';
}

async function resendConfirmation() {
    const msg = document.getElementById('resend-msg'), btn = document.getElementById('resend-btn');
    if (!msg || !btn) return;
    btn.disabled = true;
    msg.className = 'auth-msg';
    msg.textContent = 'Sending...';
    const {error} = await supabaseClient.auth.resend({
        type: 'signup', email: pendingEmail,
        options: {emailRedirectTo: location.origin + pageUrl('login')}
    });
    msg.className = 'auth-msg ' + (error ? 'bad' : 'ok');
    msg.textContent = error ? error.message : 'Sent! Check your inbox (and spam folder).';
    setTimeout(() => {
        btn.disabled = false;
    }, 30000);   // gentle rate limit on our side too
}

async function handleRegister(event) {
    event.preventDefault();
    const name = document.getElementById('reg-name').value.trim();
    const username = cleanUsername(document.getElementById('reg-username').value);
    const email = document.getElementById('auth-email').value.trim();
    const password = document.getElementById('auth-password').value;

    if (!name) return setAuthMessage('Please enter your name.');
    const usernameProblem = validateUsername(username);
    if (usernameProblem) return setAuthMessage(usernameProblem);
    if (!/^\S+@\S+\.\S+$/.test(email)) return setAuthMessage('Please enter a valid email address.');
    if (password.length < 8) return setAuthMessage('Your password needs at least 8 characters.');

    setAuthMessage('');
    setAuthBusy(true, 'Sign up');
    try {
        // Ask first so the person gets a clear message. The database's UNIQUE index is still the real guard.
        const free = await isUsernameFree(username);
        if (free === null) return setAuthMessage('Sign-up is not ready yet: the database setup (schema.sql) has not been run.');
        if (!free) return setAuthMessage('That username is taken or too similar to an existing one. Pick another one.');

        const {data, error} = await supabaseClient.auth.signUp({
            email, password,
            options: {data: {name, username}, emailRedirectTo: location.origin + pageUrl('login')}
        });
        if (error) return setAuthMessage(/registered|exists/i.test(error.message) ? 'An account with this email already exists. Try signing in.' : error.message);

        // With "Confirm email" ON, Supabase answers an already-used email with a user that has NO identities.
        if (data.user && Array.isArray(data.user.identities) && data.user.identities.length === 0) {
            return setAuthMessage('An account with this email already exists. Try signing in.');
        }
        if (data.session) {
            location.href = pageUrl('');
            return;
        }   // (confirmation turned off)
        showCheckInbox(email);
    } finally {
        setAuthBusy(false, 'Sign up');
    }
}

async function handleLogin(event) {
    event.preventDefault();
    const email = document.getElementById('auth-email').value.trim();
    const password = document.getElementById('auth-password').value;
    if (!email || !password) return setAuthMessage('Enter your email and password.');

    setAuthMessage('');
    setAuthBusy(true, 'Sign in');
    const {error} = await supabaseClient.auth.signInWithPassword({email, password});
    if (!error) {
        location.href = nextUrl() || pageUrl('');
        return;
    }

    setAuthBusy(false, 'Sign in');
    if (/not confirmed/i.test(error.message)) showCheckInbox(email);   // lets them resend the mail
    else if (/invalid login/i.test(error.message)) setAuthMessage('Wrong email or password.');
    else setAuthMessage(error.message);
}

// --- WATCH HISTORY ---
async function loadHistory(uid = currentUser?.id) {
    if (!uid) return;
    const {data, error} = await supabaseClient
        .from('watch_history').select('movie_data, updated_at')
        .eq('user_id', uid)
        .order('updated_at', {ascending: false}).limit(15);
    if (error) {
        console.error('Could not load history:', error.message);
        return;
    }
    historyList = data.map(row => row.movie_data);
    historyTimes = new Map(data.map(row => [hkey(row.movie_data), row.updated_at]));
    await loadProgress(uid);
    if (currentUser?.id !== uid) return;      // signed out while the progress was loading
    renderHistory();
    historyReadyResolve();
}

// Where did the player stop in each of these movies? (watch_progress is written by the player every 15 seconds and on pause.)
// A failed lookup is not an error: the cards simply have no progress bar.
// A film counts as watched ONLY when playback has reached its exact end (the 'ended' event, i.e. the seek bar is full). Not a
// second earlier: stop at 2:16:16 of 2:16:17 and it is still in Continue watching, still resumable.
const isFinished = (seconds, duration) => !!duration && seconds >= duration;

async function loadProgress(uid) {
    progressMap = new Map();
    progressKnown = false;
    const ids = historyList.filter(m => !isSeries(m)).map(m => m.id);      // only movies have a saved position
    if (!ids.length) return;
    try {
        const {data, error} = await supabaseClient.from('watch_progress')
            .select('movie_id, seconds, duration').eq('user_id', uid).in('movie_id', ids);
        if (error) throw error;
        (data || []).forEach(r => {
            if (r.seconds >= 5) progressMap.set(r.movie_id, r);
        });
        progressKnown = true;
    } catch (err) {
        console.warn('Could not load watch progress:', err.message || err);
    }
}

// History cards are drawn as soon as the history loads, which may be before the cinema lists arrive.
if (['home', 'category', 'search', 'dashboard'].includes(PAGE)) {
    loadCinemaSets().then(() => {
        if (historyList.length) renderHistory();
    });
}

function renderHistory() {
    // Continue watching = the movies you stopped part-way. Finished ones (progress deleted) stay on the Watch history page only.
    // If the progress lookup failed we cannot tell, so then the strip shows everything, as it did before.
    const resumable = historyList.filter(m => !isSeries(m) && (!progressKnown || progressMap.has(m.id)));   // series have no saved position: Watch history only
    const section = document.getElementById('continue-watching-section');
    if (section) section.style.display = resumable.length > 0 ? 'block' : 'none';
    renderRow(resumable, 'home-history-row', {removable: true});
    ['overview-history-row', 'full-history-row'].forEach(id => renderRow(historyList, id, {removable: true}));
    const wrap = document.getElementById('clear-history-wrap');
    if (wrap) {
        wrap.style.display = historyList.length ? '' : 'none';
        setClearHistoryUI('idle');
    }
    const empty = document.getElementById('history-empty');
    if (empty) empty.style.display = historyList.length ? 'none' : '';
}

// Forget where you stopped in a movie (you removed it from Continue watching, or you finished it).
// A delete that Row Level Security blocks does not raise an error, so we ask for the deleted rows back and warn when none came.
async function clearProgress(movieId, expectRow = false) {
    progressMap.delete(movieId);
    if (!currentUser) return;
    try {
        const {data, error} = await supabaseClient.from('watch_progress').delete()
            .eq('user_id', currentUser.id).eq('movie_id', movieId).select('movie_id');
        if (error) console.warn('Could not clear watch progress:', error.message);
        else if (expectRow && (!data || data.length === 0)) console.warn('watch_progress: nothing was deleted. Is the DELETE policy set up? (see watch_progress_delete.sql)');
    } catch (err) {
        console.warn('Could not clear watch progress:', err.message || err);
    }
}

// Remove one movie. The screen updates first (instant), then the database is asked. A blocked delete does NOT raise an
// error in Supabase (the row is simply invisible to you), so we check that a row really came back from the delete.
async function removeFromHistory(movie) {
    if (!currentUser) return;
    const index = historyList.findIndex(m => hkey(m) === hkey(movie));
    if (index === -1) return;
    const removed = historyList[index];
    const when = historyTimes.get(hkey(removed)) || new Date().toISOString();
    const savedProgress = isSeries(removed) ? null : (progressMap.get(removed.id) || null);     // kept for "Undo"
    historyList.splice(index, 1);
    renderHistory();

    const {data, error} = await supabaseClient.from('watch_history').delete()
        .eq('user_id', currentUser.id).eq('movie_id', dbId(removed)).select('movie_id');
    if (error || !data || data.length === 0) {
        console.error('Could not remove from history:', error ? error.message : 'no row was deleted (is the delete permission set up? see lists.sql)');
        historyList.splice(index, 0, removed);   // put it back, the database still has it
        renderHistory();
        showToast('Could not remove it. Please try again.');
        return;
    }
    if (savedProgress) await clearProgress(removed.id, true);      // removed from Continue watching: the saved position goes too
    showToast(`Removed "${removed.title || removed.name || (isSeries(removed) ? 'series' : 'movie')}" from your history.`,
        {label: 'Undo', onClick: () => undoHistoryRemoval(removed, when, savedProgress)});
}

async function undoHistoryRemoval(movie, when, savedProgress = null) {
    if (!currentUser || historyList.some(m => hkey(m) === hkey(movie))) return;
    historyTimes.set(hkey(movie), when);
    historyList = [...historyList, movie]
        .sort((a, b) => Date.parse(historyTimes.get(hkey(b))) - Date.parse(historyTimes.get(hkey(a)))).slice(0, 15);
    if (savedProgress) progressMap.set(movie.id, savedProgress);
    renderHistory();
    if (savedProgress) {
        supabaseClient.from('watch_progress').upsert({
            user_id: currentUser.id, movie_id: movie.id, seconds: savedProgress.seconds, duration: savedProgress.duration,
            updated_at: new Date().toISOString()
        }, {onConflict: 'user_id,movie_id'}).then(({error}) => {
            if (error) console.warn('Could not restore watch progress:', error.message);
        });
    }
    const {error} = await supabaseClient.from('watch_history').upsert(
        {user_id: currentUser.id, movie_id: dbId(movie), movie_data: movie, updated_at: when},
        {onConflict: 'user_id,movie_id'});
    if (error) {
        console.error('Could not restore history:', error.message);
        showToast('Could not restore it.');
    }
}

// "Clear all history" asks for a second click right where the button is, instead of a pop-up.
function setClearHistoryUI(mode) {
    const wrap = document.getElementById('clear-history-wrap');
    if (!wrap) return;
    const button = (label, className, onClick) => {
        const b = document.createElement('button');
        b.className = className;
        b.textContent = label;
        b.addEventListener('click', onClick);
        return b;
    };
    if (mode === 'confirm') {
        const q = document.createElement('span');
        q.className = 'confirm-text';
        q.textContent = 'Clear your whole watch history?';
        wrap.replaceChildren(q, button('Yes, clear it', 'pane-action-btn danger', clearHistory),
            button('Cancel', 'pane-action-btn', () => setClearHistoryUI('idle')));
    } else {
        wrap.replaceChildren(button('Clear all history', 'pane-action-btn', askClearHistory));
    }
}

function askClearHistory() {
    setClearHistoryUI('confirm');
}

async function clearHistory() {
    if (!currentUser) return;
    const before = historyList, beforeTimes = historyTimes;
    historyList = [];
    historyTimes = new Map();
    renderHistory();
    const {data, error} = await supabaseClient.from('watch_history').delete()
        .eq('user_id', currentUser.id).select('movie_id');
    if (error || (before.length > 0 && (!data || data.length === 0))) {
        console.error('Could not clear history:', error ? error.message : 'no rows were deleted (see lists.sql)');
        historyList = before;
        historyTimes = beforeTimes;
        renderHistory();
        showToast('Could not clear your history. Please try again.');
        return;
    }
    progressMap = new Map();
    renderHistory();
    try {
        await supabaseClient.from('watch_progress').delete().eq('user_id', currentUser.id);   // no history, nothing to continue
    } catch (err) {
        console.warn('Could not clear watch progress:', err.message || err);
    }
    showToast('Watch history cleared.');
}

// --- LIKED (heart) + WATCHLIST (bookmark) ---
// Only the fields a card needs are stored, not TMDB's whole answer.
function slimMovie(m) {
    return {
        id: m.id, title: m.title || null, name: m.name || null, poster_path: m.poster_path || null,
        backdrop_path: m.backdrop_path || null, vote_average: m.vote_average || 0,
        release_date: m.release_date || m.first_air_date || null,
        original_language: m.original_language || null, origin_country: m.origin_country || null,
        media_type: m.media_type === 'tv' ? 'tv' : 'movie'
    };
}

// media_type is part of the key because a TV show can have the same TMDB id as a movie
const savedKey = m => `${m.media_type === 'tv' ? 'tv' : 'movie'}:${m.id}`;

async function loadSavedLists(uid = currentUser?.id) {
    if (!uid) return;
    const {data, error} = await supabaseClient.from('movie_lists')
        .select('list, media_type, movie_id, movie_data')
        .eq('user_id', uid).order('created_at', {ascending: false});
    if (error) {
        console.error('Could not load liked/watchlist (has lists.sql been run?):', error.message);
        return;
    }
    savedLists = {liked: new Map(), watchlist: new Map()};
    for (const row of data) {
        if (savedLists[row.list]) savedLists[row.list].set(`${row.media_type}:${row.movie_id}`, row.movie_data);
    }
    refreshSavedUI();
}

function setSaveButtonState(btn, active) {
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-pressed', String(active));
    const liked = btn.dataset.list === 'liked';
    btn.title = active ? (liked ? 'Remove from Liked' : 'Remove from Watchlist') : (liked ? 'Like' : 'Watch later');
}

// Re-colours every heart / bookmark on the page (cards and the player bar) from savedLists.
function refreshSavedUI() {
    document.querySelectorAll('[data-list][data-key]').forEach(btn => {
        setSaveButtonState(btn, savedLists[btn.dataset.list].has(btn.dataset.key));
    });
    document.querySelectorAll('.player-save-btn').forEach(btn => {
        setSaveButtonState(btn, !!currentMovie && savedLists[btn.dataset.list].has(savedKey(currentMovie)));
    });
    renderSavedPanes();
}

function renderSavedPanes() {
    for (const list of ['liked', 'watchlist']) {
        const grid = document.getElementById(list + '-grid');
        if (!grid) continue;
        const cards = [...savedLists[list].values()].map(m => createMovieCard(m)).filter(Boolean);
        grid.replaceChildren(...cards);
        const empty = document.getElementById(list + '-empty');
        if (empty) empty.style.display = cards.length ? 'none' : '';
    }
}

async function toggleSaved(list, movie) {
    if (!currentUser) {
        showToast('Sign in to save movies to your profile.', {
            label: 'Sign in', onClick: () => {
                location.href = pageUrl('login');
            }
        });
        return;
    }
    const key = savedKey(movie);
    if (pendingSaves.has(key + list)) return;
    pendingSaves.add(key + list);

    const wasSaved = savedLists[list].has(key);
    const slim = slimMovie(movie);
    // the screen changes at once; the database follows
    if (wasSaved) savedLists[list].delete(key);
    else savedLists[list] = new Map([[key, slim], ...savedLists[list]]);   // newest first
    refreshSavedUI();

    const mediaType = slim.media_type;
    let failed = false, detail = '';
    if (wasSaved) {
        const {data, error} = await supabaseClient.from('movie_lists').delete()
            .eq('user_id', currentUser.id).eq('list', list).eq('media_type', mediaType).eq('movie_id', movie.id).select('movie_id');
        if (error || !data || data.length === 0) {
            failed = true;
            detail = error ? error.message : 'no row was deleted (see lists.sql)';
        }
    } else {
        const {error} = await supabaseClient.from('movie_lists').insert(
            {user_id: currentUser.id, list, media_type: mediaType, movie_id: movie.id, movie_data: slim});
        if (error && error.code !== '23505') {
            failed = true;
            detail = error.message;
        }   // 23505 = already saved (another tab): fine
    }
    pendingSaves.delete(key + list);

    if (failed) {
        console.error('Could not update', list, '-', detail);
        // Undo only this key. A whole-list snapshot would wipe any other save that landed meanwhile.
        if (wasSaved) savedLists[list].set(key, slim);
        else savedLists[list].delete(key);
        refreshSavedUI();
        showToast('Could not save that change. Please try again.');
        return;
    }
    const label = list === 'watchlist' ? 'your watchlist' : 'your liked movies';
    showToast(wasSaved ? `Removed from ${label}` : `Added to ${label}`);
}

function togglePlayerSave(list) {
    if (currentMovie) toggleSaved(list, currentMovie);
}

async function addToHistory(movie) {
    if (!currentUser) return;
    // Optimistic update: change the UI immediately, then save in the background.
    const now = new Date().toISOString();
    historyList = [movie, ...historyList.filter(m => hkey(m) !== hkey(movie))].slice(0, 15);
    historyTimes.set(hkey(movie), now);
    renderHistory();
    const {error} = await supabaseClient.from('watch_history').upsert(
        {user_id: currentUser.id, movie_id: dbId(movie), movie_data: movie, updated_at: now},
        {onConflict: 'user_id,movie_id'}   // no space after the comma, it must match the constraint's column list
    );
    if (error) console.error('Could not save history:', error.message);
}

// --- PROFILE / SETTINGS PAGES ---
function hydrateUserDashboard() {
    if (!document.getElementById('user-dashboard')) return;
    document.getElementById('dash-avatar').src = avatarSrc();
    const bannerEl = document.getElementById('dash-banner');
    bannerEl.style.backgroundImage = userMetadata.banner ? `url('${userMetadata.banner}')` : '';   // '' lets the CSS gradient show
    bannerEl.classList.toggle('is-empty', !userMetadata.banner);
    const bannerText = document.getElementById('banner-overlay-text');
    if (bannerText) bannerText.textContent = userMetadata.banner ? 'Change banner' : 'Add a banner';
    setText('dash-display-name', userMetadata.name || 'Summoner');
    setText('dash-display-username', userProfile.username ? '@' + userProfile.username : '');
    setText('dash-display-about', userMetadata.about || 'The abyss welcomes you.');
    setValue('set-name', userMetadata.name || '');
    setValue('set-username', userProfile.username || '');
    setValue('set-about', userMetadata.about || '');
    setValue('set-email', currentUser?.email || '');
}

// --- PROFILE PICTURES ---
// Pictures are shrunk in the browser first (a 4 MB phone photo becomes ~50 KB), then uploaded to a Supabase Storage
// bucket. Only the short public URL is saved in the profile, so the login token stays tiny and the old
// "Request body too large" error cannot happen any more.
const IMAGE_BUCKET = 'profile-images';
const IMAGE_SPECS = {avatar: {w: 256, h: 256}, banner: {w: 1200, h: 400}};   // exact output sizes
const MAX_INPUT_BYTES = 20 * 1024 * 1024;   // refuse absurd files before even trying to read them

// Reads a file, crops it to the target shape (like CSS object-fit: cover) and returns a small JPEG Blob.
function shrinkImage(file, {w, h}) {
    return new Promise((resolve, reject) => {
        const url = URL.createObjectURL(file);
        const img = new Image();
        img.onload = () => {
            URL.revokeObjectURL(url);
            const scale = Math.max(w / img.width, h / img.height);          // cover: fill the box, crop the overflow
            const sw = w / scale, sh = h / scale;                             // the part of the source we keep
            const canvas = document.createElement('canvas');
            canvas.width = w;
            canvas.height = h;
            const ctx = canvas.getContext('2d');
            ctx.fillStyle = '#000';
            ctx.fillRect(0, 0, w, h);                 // JPEG has no transparency
            ctx.drawImage(img, (img.width - sw) / 2, (img.height - sh) / 2, sw, sh, 0, 0, w, h);
            canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Could not process that image.')), 'image/jpeg', 0.85);
        };
        img.onerror = () => {
            URL.revokeObjectURL(url);
            reject(new Error('We could not read that picture. Try a JPG or PNG.'));
        };
        img.src = url;
    });
}

let stagedAvatar = null, stagedBanner = null;     // small Blobs waiting for "Save change"
let imageWork = Promise.resolve();                 // lets Save wait for a picture that is still being shrunk
function handleFileSelect(event, type) {
    const input = event.target, file = input.files[0];
    if (file) imageWork = imageWork.then(() => processPicked(file, type, input));
    else input.value = '';
}

async function processPicked(file, type, input) {
    const msg = document.getElementById('settings-msg');
    try {
        if (msg) {
            msg.innerText = 'Preparing picture...';
            msg.style.color = '#888';
        }
        if (!file.type.startsWith('image/')) throw new Error('Please choose an image file (JPG, PNG or WebP).');
        if (file.size > MAX_INPUT_BYTES) throw new Error('That picture is too big. Please choose one under 20 MB.');
        const blob = await shrinkImage(file, IMAGE_SPECS[type === 'banner' ? 'banner' : 'avatar']);
        const preview = URL.createObjectURL(blob);                          // instant preview, nothing is uploaded yet
        if (type === 'banner') {
            stagedBanner = blob;
            const b = document.getElementById('dash-banner');
            b.style.backgroundImage = `url('${preview}')`;
            b.classList.remove('is-empty');
        } else {
            stagedAvatar = blob;
            document.getElementById('dash-avatar').src = preview;
        }
        if (msg) {
            msg.innerText = 'Unsaved visual changes ready.';
            msg.style.color = '#888';
        }
    } catch (err) {
        if (msg) {
            msg.innerText = err.message;
            msg.style.color = 'var(--blood-red)';
        }
    } finally {
        input.value = '';                                                    // lets the user pick the same file again
    }
}

// Uploads one Blob to the user's own folder and returns its public URL. A new file name each time means
// browsers and the CDN can never show an old cached picture.
async function uploadProfileImage(blob, kind) {
    const path = `${currentUser.id}/${kind}-${Date.now()}.jpg`;
    const {error} = await supabaseClient.storage.from(IMAGE_BUCKET).upload(path, blob, {
        contentType: 'image/jpeg',
        cacheControl: '31536000'
    });
    if (error) throw new Error('Could not upload your picture: ' + error.message);
    const {data} = supabaseClient.storage.from(IMAGE_BUCKET).getPublicUrl(path);
    return data.publicUrl;
}

// Best-effort cleanup of the previous picture so the bucket does not fill up with old files.
function removeOldImage(oldUrl) {
    const marker = `/${IMAGE_BUCKET}/`, at = oldUrl ? oldUrl.indexOf(marker) : -1;
    if (at === -1) return;                                                  // an old base64 / imgur picture: nothing to delete
    supabaseClient.storage.from(IMAGE_BUCKET).remove([decodeURIComponent(oldUrl.slice(at + marker.length).split('?')[0])]).catch(() => {
    });
}

async function saveSettings() {
    const msgEl = document.getElementById('settings-msg'), btn = document.getElementById('save-settings-btn');
    const updatedName = document.getElementById('set-name').value.trim();
    const updatedUsername = cleanUsername(document.getElementById('set-username').value);
    const updatedAbout = document.getElementById('set-about').value;
    const currentPassword = document.getElementById('set-current-password').value;
    const newPassword = document.getElementById('set-new-password').value;
    btn.innerText = 'Saving...';
    msgEl.innerText = '';
    try {
        await imageWork;                                    // a picture picked a moment ago may still be shrinking
        // 1) Username lives in the "profiles" table, where the UNIQUE index protects it.
        if (updatedUsername && updatedUsername !== userProfile.username) {
            const problem = validateUsername(updatedUsername);
            if (problem) throw new Error(problem);
            const {error: nameError} = await supabaseClient.from('profiles').upsert({
                id: currentUser.id,
                username: updatedUsername
            });
            if (nameError) throw new Error(nameError.code === '23505' ? 'That username is taken or too similar to an existing one.' : nameError.message);
            userProfile.username = updatedUsername;
        }

        // 2) Password: Supabase's updateUser() never checks the old password, so we verify it ourselves
        //    by trying to sign in with it before allowing a change.
        if (newPassword) {
            if (newPassword.length < 8) throw new Error('Your new password needs at least 8 characters.');
            if (!currentPassword) throw new Error('Enter your current password to set a new one.');
            const {error: reauthError} = await supabaseClient.auth.signInWithPassword({
                email: currentUser.email,
                password: currentPassword
            });
            if (reauthError) throw new Error('Current password is incorrect.');
        }

        // 3) Everything else (still stored as user metadata for now)
        let authUpdates = {data: {}};
        const oldAvatar = userMetadata.avatar, oldBanner = userMetadata.banner;
        // Upload both pictures at the same time; each returns just a URL.
        const [avatarUrl, bannerUrl] = await Promise.all([
            stagedAvatar ? uploadProfileImage(stagedAvatar, 'avatar') : null,
            stagedBanner ? uploadProfileImage(stagedBanner, 'banner') : null
        ]);
        if (avatarUrl) authUpdates.data.avatar = avatarUrl;
        if (bannerUrl) authUpdates.data.banner = bannerUrl;
        if (updatedName !== userMetadata.name) authUpdates.data.name = updatedName;
        if (updatedAbout !== userMetadata.about) authUpdates.data.about = updatedAbout;
        if (newPassword) authUpdates.password = newPassword;
        if (Object.keys(authUpdates.data).length > 0 || authUpdates.password) {
            const {error} = await supabaseClient.auth.updateUser(authUpdates);
            if (error) throw error;
            Object.assign(userMetadata, authUpdates.data);
            if (avatarUrl) removeOldImage(oldAvatar);
            if (bannerUrl) removeOldImage(oldBanner);
        }

        msgEl.innerText = 'Changes Saved!';
        msgEl.style.color = '#1cb569';
        hydrateUserDashboard();
        document.getElementById('nav-avatar').src = avatarSrc();
        stagedAvatar = null;
        stagedBanner = null;
        setValue('set-current-password', '');
        setValue('set-new-password', '');
        setTimeout(() => {
            msgEl.innerText = '';
        }, 3000);
    } catch (err) {
        msgEl.innerText = err.message;
        msgEl.style.color = 'var(--blood-red)';
    } finally {
        btn.innerText = 'Save change';
    }
}

// --- FILTER ENGINE (category pages) ---
// A function (not a constant object) so every reset gets a FRESH genre array. If we copied a shared object,
// `genre` would be the same array each time and selected genres would leak into "Clear All".
function newFilters() {
    return {
        type: 'movie',
        genre: [],
        year: '',
        rating: '',
        country: '',
        quality: '',
        provider: '',
        company: '',
        region: '',
        network: '',
        sort: 'newest',
        minVotes: 0
    };
}

let activeFilters = newFilters();
let activeCategory = null;

// TMDB uses different sort keys for movies and TV, so one UI choice is translated into the right key.
const SORT_OPTIONS = {
    newest: {label: 'Newest', movie: 'primary_release_date.desc', tv: 'first_air_date.desc'},
    popular: {label: 'Most viewed', movie: 'popularity.desc', tv: 'popularity.desc'},
    release: {label: 'Release date', movie: 'primary_release_date.asc', tv: 'first_air_date.asc'},
    rating: {label: 'Top rated', movie: 'vote_average.desc', tv: 'vote_average.desc'},
    name: {label: 'Name A-Z', movie: 'original_title.asc', tv: 'original_name.asc'},
    votes: {label: 'Most voted', movie: 'vote_count.desc', tv: 'vote_count.desc'}
};

// NOTE: this is NOT called togglePopover on purpose. Browsers have a built-in element method with that
// name, and inline onclick="..." handlers find the element's own method first, so it silently hijacked ours.
function toggleFilterPopover(event, popoverId) {
    event.stopPropagation();   // stop the window click handler below from instantly closing it
    const target = document.getElementById(popoverId);
    if (!target) return;
    const wasOpen = target.classList.contains('active');
    closeFilterPopovers();
    if (!wasOpen) {
        target.classList.add('active');
        keepOnScreen(target);
    }
}

// Wide popovers (Genre, Country) can stick out past the window edge on smaller screens.
// After opening, measure where it landed and slide it back inside with a small horizontal shift.
function keepOnScreen(el) {
    el.style.transform = '';
    const r = el.getBoundingClientRect(), margin = 16;
    let shift = 0;
    if (r.right > window.innerWidth - margin) shift = window.innerWidth - margin - r.right;
    if (r.left + shift < margin) shift = margin - r.left;
    if (shift) el.style.transform = `translateX(${shift}px)`;
}

function closeFilterPopovers() {
    document.querySelectorAll('.filter-popover').forEach(p => p.classList.remove('active'));
}

window.addEventListener('click', function (e) {
    if (!e.target.closest('.filter-wrapper')) closeFilterPopovers();
    if (!e.target.closest('.account-wrapper')) document.getElementById('account-menu')?.classList.remove('open');
});

// Redraws every pill, badge and label from the activeFilters object, so the UI always matches the data.
function syncFilterUI() {
    const toolbar = document.getElementById('filter-toolbar');
    if (!toolbar) return;
    const isTv = activeFilters.type === 'tv';
    toolbar.classList.toggle('tv-mode', isTv);   // CSS hides .movie-only items and shows .tv-only items
    toolbar.classList.toggle('has-provider', !!activeFilters.provider);                       // the Region filter only makes sense with a service
    toolbar.classList.toggle('no-filters', !!categoryConfig[activeCategory]?.trending);       // the Trending page has nothing to filter

    document.querySelectorAll('.filter-pill').forEach(pill => {
        const {key, value} = pill.dataset;
        const on = key === 'genre' ? activeFilters.genre.includes(value) : activeFilters[key] === value;
        pill.classList.toggle('active', on);
        // a few genres are named differently for TV (e.g. "Action" becomes "Action & Adventure")
        if (pill.dataset.tvLabel) pill.textContent = isTv ? pill.dataset.tvLabel : pill.dataset.label;
    });
    document.querySelectorAll('.sort-item').forEach(item => {
        item.classList.toggle('active', item.dataset.sort === activeFilters.sort);
    });
    const sortTrigger = document.getElementById('sort-trigger');
    if (sortTrigger) sortTrigger.innerHTML = `${SORT_OPTIONS[activeFilters.sort].label} ${UI.sort}`;

    // Count badge + highlighted label for every filter that is switched on (like Movish's Genre "1")
    const regionBadge = document.getElementById('badge-region');
    if (regionBadge) {
        regionBadge.textContent = activeFilters.region || 'ALL';   // always shown: the catalogue you see depends on it
        document.getElementById('trigger-region')?.classList.add('has-value');
    }
    for (const key of ['genre', 'country', 'year', 'rating', 'quality']) {
        const count = key === 'genre' ? activeFilters.genre.length : (activeFilters[key] ? 1 : 0);
        const badge = document.getElementById('badge-' + key);
        if (badge) badge.textContent = count || '';
        document.getElementById('trigger-' + key)?.classList.toggle('has-value', count > 0);
    }
}

function selectPill(filterKey, value) {
    const f = activeFilters, def = FILTER_DEFS[filterKey];
    if (filterKey === 'genre') {
        f.genre = f.genre.includes(value) ? f.genre.filter(k => k !== value) : [...f.genre, value];
    } else if (def.toggle && f[filterKey] === value) {
        f[filterKey] = '';                       // clicking an active pill again switches it off
    } else {
        f[filterKey] = value;
    }
    if (filterKey === 'type') {
        // keep only the genres that exist for the newly chosen type, and drop Quality (movies only)
        const slot = value === 'tv' ? 3 : 2;
        f.genre = f.genre.filter(k => GENRE_BY_KEY[k][slot]);
        if (value === 'tv') f.quality = '';
    }
    syncFilterUI();
}

function selectSort(sortKey) {
    activeFilters.sort = sortKey;
    syncFilterUI();
    closeFilterPopovers();
    applyFilters();
}

function isoDate(daysFromToday) {
    return new Date(Date.now() + daysFromToday * 86400000).toISOString().slice(0, 10);
}

// Fewest votes a title needs to be listed. 1 keeps almost everything TMDB has; a "Top rated" sort needs a real floor,
// otherwise a film with one 10/10 vote would sit at the very top.
function voteFloor(f) {
    return f.sort === 'rating' ? Math.max(f.minVotes, 100) : Math.max(f.minVotes, 1);
}

function buildDiscoverUrl(page = 1) {
    const f = activeFilters, isTv = f.type === 'tv';
    if (categoryConfig[activeCategory]?.trending) {              // the Trending page is TMDB's own list: no filters, just pages
        return `https://api.themoviedb.org/3/trending/${activeFilters.type === 'tv' ? 'tv' : 'movie'}/week?api_key=${API_KEY}${page > 1 ? '&page=' + page : ''}`;
    }
    const params = new URLSearchParams({
        api_key: API_KEY,
        'vote_count.gte': voteFloor(f),
        sort_by: SORT_OPTIONS[f.sort][f.type]
    });
    // Films that are not out yet only clutter the lists, so (unless a year or Quality filter says otherwise) nothing after today.
    if (!f.year && !(!isTv && f.quality)) params.set(isTv ? 'first_air_date.lte' : 'primary_release_date.lte', isoDate(0));

    // Genres: our keys -> the right TMDB ids for movie or tv. A comma means AND (must be ALL the chosen genres).
    const genreIds = [...new Set(f.genre.map(k => GENRE_BY_KEY[k][isTv ? 3 : 2]).filter(Boolean))];
    if (genreIds.length) params.set('with_genres', genreIds.join(','));

    if (f.year === 'older') {
        // "Older" = everything before the oldest year shown as a pill
        params.set(isTv ? 'first_air_date.lte' : 'primary_release_date.lte', `${THIS_YEAR - 5}-12-31`);
    } else if (f.year) {
        params.set(isTv ? 'first_air_date_year' : 'primary_release_year', f.year);
    }

    if (f.rating) params.set('vote_average.gte', f.rating === '10' ? '9.5' : f.rating);   // nothing scores a flat 10
    if (f.country) params.set('with_origin_country', f.country);

    // TMDB knows nothing about video quality, but it does know RELEASE TYPES. We use them as an honest stand-in:
    //  HD  = has a digital/physical (home) release, so good copies exist
    //  CAM = in cinemas in the last 45 days, which is when only cinema-recorded copies exist
    // (4K and SD cannot be derived from TMDB, so they are not offered.)
    if (!isTv && f.quality) {
        params.set('region', 'US');
        params.set('release_date.lte', isoDate(0));
        if (f.quality === 'hd') {
            params.set('with_release_type', '4|5');
        } else {
            params.set('with_release_type', '3');
            params.set('release_date.gte', isoDate(-45));
            params.set('vote_count.gte', 5);   // brand-new films have hardly any votes yet
        }
    }

    if (f.provider) {
        const net = NETWORKS.find(n => n.key === f.network);
        params.set('with_watch_monetization_types', STREAM_TYPES);
        if (f.region) {
            params.set('with_watch_providers', net ? providerIds(net, f.region) : f.provider);
            params.set('watch_region', f.region);
        } else {                                   // All regions: tmdbAllRegions() fills in the country part per request
            params.set('with_watch_providers', f.provider);
            params.set('watch_region', 'US');
            params.set('ruin_all', '1');
            params.set('ruin_net', f.network);
        }
    }
    if (f.company) params.set('with_companies', f.company);   // Marvel / DC pages: films made by that studio
    if (page > 1) params.set('page', page);
    return `https://api.themoviedb.org/3/discover/${f.type}?${params}`;
}

// Starts from the category's defaults (e.g. Horror = the 'horror' genre); the toolbar filters build on top.
// The filters a category page starts with (horror = genre horror, netflix = provider Netflix ...).
function categoryFilters(name) {
    const f = newFilters(), cfg = categoryConfig[name];
    if (cfg?.genre) f.genre = [cfg.genre];
    if (cfg?.sort) f.sort = cfg.sort;
    if (cfg?.type) f.type = cfg.type;
    if (cfg?.country) f.country = cfg.country;
    if (cfg?.minVotes) f.minVotes = cfg.minVotes;
    const net = cfg?.network && NETWORKS.find(n => n.key === cfg.network);
    if (net?.provider) {
        f.provider = net.provider;
        f.network = net.key;
    }
    if (net?.company) f.company = net.company;
    return f;
}

function resetFiltersToCategory(name) {
    activeFilters = categoryFilters(name);
}

// ---------------------------------------------------------------------------------------------
// FILTERS IN THE ADDRESS BAR   e.g.  /horror?genre=horror,thriller&country=KR&year=2024&sort=rating
// Only what DIFFERS from the page's own starting filters is written, so /horror stays just /horror.
// The address is the single source of truth you can share, bookmark or refresh. Everything read from it
// is checked against our own lists first, so a made-up or broken link can never put junk into a TMDB request.
// ---------------------------------------------------------------------------------------------
function filtersFromUrl() {
    const q = new URLSearchParams(location.search), f = activeFilters;
    if (categoryConfig[activeCategory]?.trending) {         // no filters here, but ?type=tv (the "See all" of the home series row) shows trending SERIES
        if (q.get('type') === 'tv') f.type = 'tv';
        return;
    }
    const pick = (key, allowed) => {
        if (q.has(key)) {
            const v = q.get(key);
            if (allowed(v)) f[key] = v;
        }
    };
    pick('type', v => v === 'movie' || v === 'tv');
    if (q.has('genre')) {                                           // several genres, comma separated
        const slot = f.type === 'tv' ? 3 : 2;
        const raw = q.get('genre');
        const valid = [...new Set(raw.split(','))].filter(k => Object.hasOwn(GENRE_BY_KEY, k) && GENRE_BY_KEY[k][slot]);
        if (raw === '') f.genre = [];                       // "genre=" on purpose = no genre at all
        else if (valid.length) f.genre = valid;             // otherwise only accept it if something in it was real
    }
    pick('country', v => v === '' || COUNTRIES.some(c => c[0] === v));
    pick('year', v => v === '' || v === 'older' || /^(19|20)\d\d$/.test(v));
    pick('rating', v => v === '' || /^([4-9]|10)$/.test(v));
    pick('sort', v => Object.hasOwn(SORT_OPTIONS, v));
    if (f.type !== 'tv') pick('quality', v => v === '' || v === 'hd' || v === 'cam');
    if (f.provider) pick('region', v => REGIONS.some(r => r[0] === v));
}

function syncUrl() {
    if (!activeCategory || categoryConfig[activeCategory]?.trending) return;
    const base = categoryFilters(activeCategory), f = activeFilters, parts = [];
    const add = (key, value, baseValue) => {
        if (value !== baseValue) parts.push(key + '=' + encodeURIComponent(value).replace(/%2C/g, ','));
    };
    add('type', f.type, base.type);
    add('genre', f.genre.join(','), base.genre.join(','));
    add('country', f.country, base.country);
    add('year', f.year, base.year);
    add('rating', f.rating, base.rating);
    if (f.type !== 'tv') add('quality', f.quality, base.quality);
    add('sort', f.sort, base.sort);
    if (f.provider) add('region', f.region, base.region);
    const url = location.pathname + (parts.length ? '?' + parts.join('&') : '') + location.hash;
    // replaceState = change the address WITHOUT adding a Back-button step for every click on a filter
    if (url !== location.pathname + location.search + location.hash) history.replaceState(null, '', url);
}

function categoryTitle() {
    const cfg = categoryConfig[activeCategory];
    if (!cfg) return 'CUSTOM ARCHIVES';
    // If the person changed the genre away from the category's own genre, the category name would be misleading.
    if (cfg.genre && !(activeFilters.genre.length === 1 && activeFilters.genre[0] === cfg.genre)) return 'CUSTOM ARCHIVES';
    if (cfg.type && activeFilters.type !== cfg.type) return 'CUSTOM ARCHIVES';
    return cfg.title;
}

async function applyFilters() {
    closeFilterPopovers();
    const token = ++renderToken;
    resetPager();                          // new filters = start the endless scroll from page 1 again
    SK.fill('movie-grid', 18);             // ghost cards until the real ones arrive
    const titleEl = document.getElementById('category-title');
    if (titleEl) titleEl.innerText = categoryTitle();
    syncFilterUI();
    syncUrl();

    try {
        if (activeFilters.network && activeFilters.region) await loadProviderList(activeFilters.region);   // need the region's service list to build the query
        const [data] = await Promise.all([tmdb(buildDiscoverUrl()), loadCinemaSets()]);
        if (token !== renderToken) return;   // a newer request was started meanwhile, drop this response
        const type = activeFilters.type, cam = activeFilters.quality === 'cam';
        // The CAM filter asks TMDB for "in cinemas recently"; titles that already got a home release are removed here.
        const prepare = list => {
            // TMDB already filtered by the Country filter, so we can truthfully tag each card with that country
            const out = list.map(m => ({
                ...m,
                media_type: type, ...(activeFilters.country && !m.origin_country ? {origin_country: [activeFilters.country]} : {})
            }));
            return cam ? out.filter(m => !cinemaSets.home.has(m.id)) : out;
        };
        const results = prepare(data.results);
        showResults(results);
        startPager(n => buildDiscoverUrl(n), data, results, prepare);
    } catch (err) {
        if (token !== renderToken) return;
        console.error(err);
        showGridMessage('The void refused to answer. Please try again in a moment.');
        hideHero();
    }
}

function clearFilters() {
    resetFiltersToCategory(activeCategory);
    applyFilters();
}

// Picks a hero (first result that has a backdrop) and puts the rest in the grid.
function showResults(results) {
    if (results.length === 0) {
        showGridMessage('No souls match these exact parameters in the void.');
        hideHero();
        return;
    }
    results = results.filter(m => !isBlocked(m));
    if (!results.length) {
        showGridMessage('No souls match these exact parameters in the void.');
        hideHero();
        return;
    }
    const hero = results.find(m => m.backdrop_path) || results[0];
    setHeroBanner(hero);
    renderGrid(results.filter(m => m !== hero));
}

// --- PAGE INITIALISERS ---
async function initHomepage() {
    const token = ++renderToken;
    // ghost cards first, so every section already has its final height (the lower ones load later, as you scroll)
    for (const id of ['trending-row', 'top-rated-row', 'network-row', 'award-row']) SK.fill(id, 8);
    for (const id of ['latest-grid', 'anime-grid']) SK.fill(id, 16);
    try {
        const [trendData, topData] = await Promise.all([tmdb(endpoints.trending), tmdb(endpoints.topRated), loadCinemaSets()]);
        if (token !== renderToken) return;
        if (trendData.results.length > 0) {
            const featured = trendData.results.filter(m => m.backdrop_path && m.poster_path && !isBlocked(m)).slice(0, 9);
            if (featured.length) startHero(featured);
            renderRow(trendData.results, 'trending-row');
        } else rowMessage('trending-row', 'Nothing is stirring in the inferno right now.');
        renderRow(topData.results, 'top-rated-row');
    } catch (err) {
        console.error(err);
        rowMessage('trending-row', 'The void refused to answer. Refresh to try again.');
        rowMessage('top-rated-row', 'The void refused to answer. Refresh to try again.');
    } finally {
        if (token === renderToken) endHeroSkeleton();   // success already removed it; this covers errors and empty lists
    }
    // The sections below the fold load only when you scroll near them: a visitor who never scrolls costs us no requests.
    whenVisible('genre-grid', loadGenreCards);
    whenVisible('network-grid', loadNetworkCards);
    whenVisible('network-row', () => selectNetworkTab(NETWORKS[0].key));
    whenVisible('collection-grid', loadCollections);
    whenVisible('latest-grid', loadLatest);
    whenVisible('anime-grid', loadAnime);
    whenVisible('award-row', loadAward);
    whenVisible('series-row', () => loadSeriesRow('series-row', 'series-pop', 'trending/tv/week'));
    whenVisible('series-top-row', () => loadSeriesRow('series-top-row', 'series-top', 'tv/top_rated'));
}

// A home row of series (popular this week / all-time best rated).
async function loadSeriesRow(rowId, cacheKey, path) {
    SK.fill(rowId, 8);
    try {
        const list = await cached(cacheKey, async () => {
            const data = await tmdb(`https://api.themoviedb.org/3/${path}?api_key=${API_KEY}`);
            return data.results.filter(m => m.poster_path).map(slimTv);
        });
        if (list.length) renderRow(list, rowId);
        else rowMessage(rowId, 'No series answered the summoning.');
    } catch (err) {
        console.error(rowId + ':', err.message);
        rowMessage(rowId, 'The void refused to answer. Refresh to try again.');
    }
}

// --- HOME: Latest movies, Anime universe, Award-worthy ---
// Shared: fetch a discover query once (cached), keep only titles with a poster, slim them down.
async function discoverList(cacheKey, params) {
    return cached(cacheKey, async () => {
        const q = new URLSearchParams({api_key: API_KEY, ...params});
        const data = await tmdb(`https://api.themoviedb.org/3/discover/movie?${q}`);
        return {total: data.total_results, movies: data.results.filter(m => m.poster_path).map(slimResult)};
    });
}

function fillGrid(id, movies, limit = 16) {
    const grid = document.getElementById(id);
    if (!grid) return;
    grid.replaceChildren(...movies.filter(m => !isBlocked(m)).slice(0, limit).map(m => createMovieCard(m)).filter(Boolean));
}

async function loadLatest() {
    try {
        // newest first, but only films that are already out and have a few votes (otherwise the list is full of unreleased blanks)
        const info = await discoverList('latest', {
            sort_by: 'primary_release_date.desc',
            'primary_release_date.lte': isoDate(0),
            'vote_count.gte': 20,
            region: 'US'
        });
        fillGrid('latest-grid', info.movies);
    } catch (err) {
        console.error('latest:', err.message);
        const grid = document.getElementById('latest-grid');
        if (grid) grid.replaceChildren(stateBlock('The void refused to answer.', true));
    }
}

async function loadAnime() {
    try {
        const info = await discoverList('anime', {
            with_genres: 16,
            with_origin_country: 'JP',
            sort_by: 'popularity.desc',
            'vote_count.gte': 50
        });
        fillGrid('anime-grid', info.movies);
        setText('anime-count', `アニメ · ${fmtCount(info.total)} titles`);
    } catch (err) {
        console.error('anime:', err.message);
        const grid = document.getElementById('anime-grid');
        if (grid) grid.replaceChildren(stateBlock('The void refused to answer.', true));
    }
}

async function loadAward() {
    try {
        // "award-worthy" here means: rated 7.8+ by thousands of people, biggest box-office first. It is an estimate, not a list of award winners.
        const info = await discoverList('award', {
            sort_by: 'revenue.desc',
            'vote_average.gte': 7.8,
            'vote_count.gte': 5000
        });
        renderRow(info.movies, 'award-row');
    } catch (err) {
        console.error('award:', err.message);
        rowMessage('award-row', 'The void refused to answer.');
    }
}

// --- HOME PAGE: small helpers ---
// Runs fn once when the element gets within 400px of the screen. Without IntersectionObserver it just runs at once.
function whenVisible(id, fn) {
    const node = document.getElementById(id);
    if (!node) return;
    if (!('IntersectionObserver' in window)) {
        fn();
        return;
    }
    const io = new IntersectionObserver(entries => {
        if (entries.some(e => e.isIntersecting)) {
            io.disconnect();
            fn();
        }
    }, {rootMargin: '400px'});
    io.observe(node);
}

// A tiny cache in sessionStorage (it lives until the tab closes). Counts and posters do not change by the minute,
// so reloading the home page should not repeat 30 requests. Storage can be blocked, so everything is in try/catch.
const HOME_CACHE_MS = 6 * 3600 * 1000;

async function cached(key, loader) {
    try {
        const hit = JSON.parse(sessionStorage.getItem('ruin:' + key));
        if (hit && Date.now() - hit.t < HOME_CACHE_MS) return hit.v;
    } catch (e) { /* no cache, just load */
    }
    const value = await loader();
    try {
        sessionStorage.setItem('ruin:' + key, JSON.stringify({t: Date.now(), v: value}));
    } catch (e) { /* storage full or blocked */
    }
    return value;
}

const SMALL_IMG = 'https://image.tmdb.org/t/p/w185';
const fmtCount = n => Number(n).toLocaleString('en-US');

// --- HOME: Browse by genre (a title count and a few posters per genre) ---
async function loadGenreCards(keys = GENRE_CARDS.slice(0, GENRE_VISIBLE).map(g => g[0])) {
    await Promise.all(keys.map(async key => {
        const card = document.querySelector(`.genre-card[data-genre="${key}"]`);
        if (!card) return;
        try {
            // the same filters the genre page uses, so the number matches what you will find there
            const info = await cached('genre:' + key, async () => {
                const data = await tmdb(`https://api.themoviedb.org/3/discover/movie?api_key=${API_KEY}&with_genres=${GENRE_BY_KEY[key][2]}&vote_count.gte=1&primary_release_date.lte=${isoDate(0)}&sort_by=popularity.desc`);
                return {
                    total: data.total_results,
                    posters: data.results.filter(m => m.poster_path).slice(0, 4).map(m => m.poster_path)
                };
            });
            card.querySelector('.gc-count').textContent = `${fmtCount(info.total)} titles`;
            card.querySelector('.gc-collage').replaceChildren(...info.posters.map(p => {
                const img = document.createElement('img');
                img.src = SMALL_IMG + p;
                img.alt = '';
                img.loading = 'lazy';
                return img;
            }));
        } catch (err) {
            console.error(`genre card ${key}:`, err.message);
            const count = card.querySelector('.gc-count');
            if (count) count.textContent = '';
        } finally {
            card.removeAttribute('data-loading');
        }   // stops the shimmer, success or not
    }));
}

// "Show all genres" button on the home page: reveals the extra cards, and loads their counts the first time.
let extraGenresLoaded = false;

function toggleAllGenres() {
    const grid = document.getElementById('genre-grid'), btn = document.getElementById('genre-more');
    if (!grid || !btn) return;
    const open = grid.classList.toggle('show-all');
    btn.setAttribute('aria-expanded', String(open));
    btn.textContent = open ? 'Show fewer genres' : `Show all ${GENRE_CARDS.length} genres`;
    if (open && !extraGenresLoaded) {
        extraGenresLoaded = true;
        loadGenreCards(GENRE_CARDS.slice(GENRE_VISIBLE).map(g => g[0]));
    }
}

// --- HOME: streaming services (logo + title count) ---
// A streaming service is NOT one id on TMDB: Paramount+ is "Paramount+", "Paramount Plus Premium", "Paramount+ Amazon Channel" ...
// and a film is often listed under only one of them. So we ask TMDB for the full list of services in the region, take every
// one whose name matches (n.match), and ask for films on ANY of them ("|" means "or"). The ids typed in NETWORKS are the fallback.
const providerLists = {};      // region code -> [{ id, name, logo }]
async function loadProviderList(region = 'US') {
    if (providerLists[region]) return providerLists[region];
    try {
        providerLists[region] = await cached('providers:' + region, async () =>
            (await tmdb(`https://api.themoviedb.org/3/watch/providers/movie?api_key=${API_KEY}&watch_region=${region}`)).results
                .map(p => ({id: String(p.provider_id), name: p.provider_name || '', logo: p.logo_path})));
    } catch (err) {
        console.error('provider list:', err.message);
        providerLists[region] = [];
    }
    return providerLists[region];
}

function providerIds(n, region = 'US') {
    const found = n.match ? (providerLists[region] || []).filter(p => n.match.test(p.name)).map(p => p.id) : [];
    return [...new Set([...String(n.provider).split('|'), ...found])].join('|');
}

// "on this service" = included in the subscription, or free (with ads). Renting and buying are not counted.
const STREAM_TYPES = 'flatrate|free|ads';

// ALL REGIONS. TMDB can only answer "which films are on Netflix" for ONE country at a time, so for the whole world we ask
// the biggest countries at the same time, merge the answers, drop duplicates and sort them the way the page asked.
// Why these countries: they carry most of the world's catalogue, and every extra country is one more request per page.
const ALL_REGION_CODES = ['US', 'GB', 'CA', 'AU', 'DE', 'FR', 'ES', 'IT', 'JP', 'KR', 'IN', 'BR', 'MX'];

async function tmdbAllRegions(url) {
    const u = new URL(url), net = NETWORKS.find(n => n.key === u.searchParams.get('ruin_net'));
    u.searchParams.delete('ruin_all');
    u.searchParams.delete('ruin_net');
    await Promise.all(ALL_REGION_CODES.map(r => loadProviderList(r)));     // each country has its own variants of a service
    const answers = (await Promise.allSettled(ALL_REGION_CODES.map(r => {
        const x = new URL(u);
        x.searchParams.set('watch_region', r);
        if (net) x.searchParams.set('with_watch_providers', providerIds(net, r));
        return tmdb(x.toString());
    }))).filter(a => a.status === 'fulfilled').map(a => a.value);
    if (!answers.length) throw new Error('TMDB request failed (all regions)');
    const byId = new Map();
    for (const a of answers) for (const m of a.results) if (!byId.has(m.id)) byId.set(m.id, m);
    const [field, dir] = (u.searchParams.get('sort_by') || 'popularity.desc').split('.');
    const key = m => field === 'primary_release_date' ? (m.release_date || '') : (m[field] ?? 0);
    const merged = [...byId.values()].sort((a, b) => (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0) * (dir === 'asc' ? 1 : -1));
    return {
        results: merged,
        total_results: Math.max(...answers.map(a => a.total_results || 0)),     // the biggest single country: a safe lower bound
        total_pages: Math.max(...answers.map(a => a.total_pages || 1)),
    };
}

function networkQuery(n, extra = {}) {
    const p = new URLSearchParams({api_key: API_KEY, sort_by: 'popularity.desc', 'vote_count.gte': 1, ...extra});
    if (n.provider) {
        p.set('with_watch_providers', n.provider);
        p.set('watch_region', 'US');
        p.set('with_watch_monetization_types', STREAM_TYPES);
        p.set('ruin_all', '1');
        p.set('ruin_net', n.key);
    }
    if (n.company) p.set('with_companies', n.company);
    return `https://api.themoviedb.org/3/discover/movie?${p}`;
}

async function loadNetworkCards() {
    const LOGO = 'https://image.tmdb.org/t/p/w154';
    // Logos come from TMDB itself (same host as the posters). One request gives every streaming service's logo;
    // studios (Marvel/DC) need one request each.
    const providerLogos = Object.fromEntries((await loadProviderList('US')).map(p => [p.id, p.logo]));

    await Promise.all(NETWORKS.map(async n => {
        const card = document.querySelector(`.network-card[data-network="${n.key}"]`);
        if (!card) return;
        const setLogo = path => {
            if (!path) return;   // keep the text name
            const img = document.createElement('img');
            img.alt = n.name;
            img.loading = 'lazy';
            img.src = LOGO + path;
            img.onerror = () => card.querySelector('.nc-logo').replaceChildren(Object.assign(document.createElement('span'), {
                className: 'network-fallback',
                textContent: n.name
            }));
            const box = card.querySelector('.nc-logo');
            box.classList.toggle('company', !!n.company);
            box.replaceChildren(img);
        };
        try {
            if (n.company) setLogo(await cached('company-logo:' + n.logoId, async () => (await tmdb(`https://api.themoviedb.org/3/company/${n.logoId}?api_key=${API_KEY}`)).logo_path));
            else setLogo(providerLogos[n.logoId]);
        } catch (err) {
            console.error(`logo ${n.key}:`, err.message);
        }
        try {
            const total = await cached('network-count3:' + n.key, async () => (await tmdb(networkQuery(n))).total_results);
            card.querySelector('.nc-count').textContent = `${fmtCount(total)} titles`;
        } catch (err) {
            console.error(`count ${n.key}:`, err.message);
            const count = card.querySelector('.nc-count');
            if (count) count.textContent = '';
        } finally {
            card.removeAttribute('data-loading');
        }
    }));
}

// --- HOME: "Trending on [network]" tabs ---
let networkTabToken = 0;

async function selectNetworkTab(key) {
    const n = NETWORKS.find(x => x.key === key);
    if (!n) return;
    const token = ++networkTabToken;   // if you click another tab quickly, the slower answer is ignored
    document.querySelectorAll('.network-tab').forEach(t => {
        const on = t.dataset.network === key;
        t.classList.toggle('active', on);
        t.setAttribute('aria-selected', String(on));
    });
    setText('network-tab-title', `TRENDING ON ${n.name}`);
    const seeAll = document.getElementById('network-see-all');
    if (seeAll) seeAll.href = pageUrl(n.key);
    const row = document.getElementById('network-row');
    if (!row) return;
    row.classList.add('loading');
    try {
        await loadProviderList('US');
        const movies = await cached('network-row3:' + key, async () => (await tmdb(networkQuery(n))).results.filter(m => m.poster_path).map(slimResult));
        if (token !== networkTabToken) return;
        renderRow(movies, 'network-row');
        row.scrollLeft = 0;
    } catch (err) {
        if (token !== networkTabToken) return;
        console.error(err);
        row.replaceChildren(Object.assign(document.createElement('p'), {
            className: 'empty-note',
            textContent: 'The void refused to answer. Try another tab.'
        }));
    } finally {
        if (token === networkTabToken) row.classList.remove('loading');
    }
}

// A series from TMDB, shaped like a movie so the same poster card can show it (name -> title, first_air_date -> release_date).
const slimTv = m => ({
    id: m.id, title: m.name || m.title, name: m.name || m.title, poster_path: m.poster_path, backdrop_path: m.backdrop_path,
    vote_average: m.vote_average, release_date: m.first_air_date || m.release_date || null, genre_ids: m.genre_ids, overview: m.overview,
    media_type: 'tv', original_language: m.original_language, origin_country: m.origin_country
});

// What a poster card needs, nothing more (keeps the cached copy small).
const slimResult = m => ({
    id: m.id, title: m.title, poster_path: m.poster_path, backdrop_path: m.backdrop_path, vote_average: m.vote_average,
    release_date: m.release_date, genre_ids: m.genre_ids, overview: m.overview, media_type: 'movie',
    original_language: m.original_language, origin_country: m.origin_country
});

// --- HOME: Ever epic series (sagas) ---
const sagaData = {};   // key -> { movies, count }
async function loadCollections() {
    await Promise.all(COLLECTIONS.map(async c => {
        const card = document.querySelector(`.collection-card[data-collection="${c.key}"]`);
        if (!card) return;
        try {
            const saga = await cached('saga:' + c.key, async () => {
                let movies = [], count = 0;
                if (c.collections) {
                    // a saga can be several TMDB collections (Tolkien = Lord of the Rings + The Hobbit); one failing must not lose the rest
                    const parts = await Promise.all(c.collections.map(id => tmdb(`https://api.themoviedb.org/3/collection/${id}?api_key=${API_KEY}`).then(d => d.parts).catch(() => [])));
                    const seen = new Set();
                    movies = parts.flat().filter(m => m.poster_path && !seen.has(m.id) && seen.add(m.id));
                    movies.sort((a, b) => (a.release_date || '9999').localeCompare(b.release_date || '9999'));
                    count = movies.length;
                } else {
                    const base = networkQuery({company: c.company}, {sort_by: 'primary_release_date.asc'});
                    const pages = await Promise.all([1, 2].map(p => tmdb(`${base}&page=${p}`).catch(() => ({
                        results: [],
                        total_results: 0
                    }))));
                    movies = pages.flatMap(p => p.results).filter(m => m.poster_path);
                    count = pages[0].total_results;
                }
                return {movies: movies.map(slimResult), count};
            });
            if (!saga.movies.length) throw new Error('no films returned');
            sagaData[c.key] = saga;
            card.querySelector('.cc-count').textContent = `${fmtCount(saga.count)} movies`;
            card.querySelector('.cc-stack').replaceChildren(...saga.movies.slice(0, 4).map(m => {
                const img = document.createElement('img');
                img.src = SMALL_IMG + m.poster_path;
                img.alt = '';
                img.loading = 'lazy';
                return img;
            }));
            card.disabled = false;
        } catch (err) {
            console.error(`saga ${c.key}:`, err.message);
            card.hidden = true;
        } finally {
            card.removeAttribute('data-loading');
        }
    }));
}

function openCollection(key) {
    const c = COLLECTIONS.find(x => x.key === key), saga = sagaData[key];
    if (!c || !saga) return;
    const box = mk('div', 'saga');
    const title = mk('h2', '', c.name);
    title.id = 'modal-title';
    const note = saga.count > saga.movies.length ? `Showing ${saga.movies.length} of ${fmtCount(saga.count)} movies` : `${saga.movies.length} movies`;
    const grid = mk('div', 'movie-grid saga-grid');
    saga.movies.forEach(m => {
        const card = createMovieCard(m);
        if (card) grid.appendChild(card);
    });
    box.append(title, mk('p', 'details-facts', note), grid);
    openModal(box);
}

function initCategory() {
    activeCategory = document.body.dataset.category;
    resetFiltersToCategory(activeCategory);
    filtersFromUrl();                                   // a shared / bookmarked / refreshed link restores its filters
    document.title = `${categoryConfig[activeCategory]?.title || 'Archives'} | RUIN.TO`;
    applyFilters();
}

function handleSearch(event) {
    if (event.key !== 'Enter') return;
    const query = event.target.value.trim();
    if (!query) return;
    location.href = pageUrl('search') + '?q=' + encodeURIComponent(query);
}

async function initSearch() {
    const query = (new URLSearchParams(location.search).get('q') || '').trim();
    document.getElementById('search-input').value = query;
    if (!query) {
        const t = document.getElementById('category-title');
        if (t) t.innerText = 'SUMMON A TITLE';
        return;
    }
    document.title = `${query} | RUIN.TO`;
    const titleEl = document.getElementById('category-title');
    if (titleEl) titleEl.innerText = `SUMMONED: ${query.toUpperCase()}`;
    SK.fill('movie-grid', 18);
    try {
        // search/multi finds movies AND series (and people, which are dropped here). Each result keeps its own type, so a series
        // card says SERIES and opens the series page, a movie card opens the player.
        const only = list => list.filter(m => (m.media_type === 'movie' || m.media_type === 'tv') && m.poster_path)
            .map(m => m.media_type === 'tv' ? slimTv(m) : {...m, media_type: 'movie'});
        const [data] = await Promise.all([tmdb(`https://api.themoviedb.org/3/search/multi?api_key=${API_KEY}&query=${encodeURIComponent(query)}`), loadCinemaSets()]);
        const first = only(data.results);
        if (first.length === 0) showGridMessage('Nothing answered the summoning.');
        else {
            renderGrid(first);
            startPager(n => `https://api.themoviedb.org/3/search/multi?api_key=${API_KEY}&query=${encodeURIComponent(query)}&page=${n}`,
                data, first, only);
        }
    } catch (err) {
        console.error(err);
        showGridMessage('The void refused to answer. Please try again in a moment.');
    }
}

// --- DOM INJECTION ---
// Built with createElement/textContent instead of innerHTML strings: a title containing a quote
// or "<" can no longer break the markup (or inject code).
function makeSaveButton(list, movie) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `card-btn card-btn-${list}`;
    btn.dataset.list = list;
    btn.dataset.key = savedKey(movie);
    btn.innerHTML = list === 'liked' ? ICONS.heart : ICONS.bookmark;   // trusted constant, not user data
    btn.setAttribute('aria-label', list === 'liked' ? 'Like' : 'Watch later');
    setSaveButtonState(btn, savedLists[list].has(btn.dataset.key));
    // stopPropagation: the whole card is a "play" button, a click on the heart must not start the movie
    btn.addEventListener('click', e => {
        e.stopPropagation();
        toggleSaved(list, movie);
    });
    return btn;
}

// opts.removable adds the small cross used on watch-history cards
// Full names instead of codes: "South Korea", or "Korean" when only the language is known. (Intl.DisplayNames is built into the browser.)
const SHORT_NAMES = {'United States': 'USA', 'United Kingdom': 'UK', 'United Arab Emirates': 'UAE'};
let regionNames = null, languageNames = null;
try {
    regionNames = new Intl.DisplayNames(['en'], {type: 'region'});
    languageNames = new Intl.DisplayNames(['en'], {type: 'language'});
} catch (e) { /* very old browser: fall back to codes */
}

function originName(m) {
    const cc = m.origin_country && m.origin_country[0];
    if (cc) {
        const n = (typeof COUNTRIES !== 'undefined' && COUNTRIES.find(c => c[0] === cc)?.[1]) || regionNames?.of(cc) || cc;
        return SHORT_NAMES[n] || n;
    }
    const lang = m.original_language;
    if (lang && lang !== 'xx' && lang !== 'cn') {
        try {
            return languageNames?.of(lang) || lang.toUpperCase();
        } catch (e) {
            return lang.toUpperCase();
        }
    }
    return '';
}

// --- KIND LABELS: YouTube-only / short / AI-generated titles ---------------------------------------------------------------
// TMDB lists some titles that only exist on YouTube, are shorts, or are AI-generated. We keep them but say what they are.
// TMDB has no "kind" field, so this is a best guess from its own data (one request per title, remembered for 14 days):
//   SHORT   = runtime of 40 minutes or less (the Academy's own definition of a short) or the keyword "short film"
//   AI      = a keyword that says the film is AI-generated (NOT the "artificial intelligence" theme, which is about robots in the story)
//   YOUTUBE = the title's official website is a youtube.com / youtu.be link, or a keyword that says it is a YouTube video
// Wrong guess? Add the TMDB id to LABEL_OVERRIDES below. Values: 'ai', 'youtube', 'short', combined with '/', or 'none' to clear all labels.
const LABEL_OVERRIDES = {
    // 123456: 'youtube/short',
    // 654321: 'none',
};
const KIND_SHORT = 1, KIND_AI = 2, KIND_YT = 4;
const KIND_AI_RE = /^(ai[- ]generated( (film|movie|video|content))?|generative ai|ai[- ]made|ai film|made with ai)$/i;
const KIND_YT_RE = /^(youtube|youtube video|youtube movie|youtube short|youtube film|youtube original)$/i;
const KIND_CACHE_KEY = 'ruin.cls', KIND_TTL = 14 * 864e5;
const GENRE_NAMES = {
    28: 'Action', 12: 'Adventure', 16: 'Animation', 35: 'Comedy', 80: 'Crime', 99: 'Documentary', 18: 'Drama',
    10751: 'Family', 14: 'Fantasy', 36: 'History', 27: 'Horror', 10402: 'Music', 9648: 'Mystery',
    10749: 'Romance', 878: 'Sci-Fi', 10770: 'TV Movie', 53: 'Thriller', 10752: 'War', 37: 'Western',
    // series use a few ids of their own
    10759: 'Action & Adventure', 10762: 'Kids', 10763: 'News', 10764: 'Reality', 10765: 'Sci-Fi & Fantasy',
    10766: 'Soap', 10767: 'Talk', 10768: 'War & Politics'
};
const genreNames = m => (m.genre_ids || []).map(id => GENRE_NAMES[id]).filter(Boolean);

let kindStore = {};
try {
    const raw = JSON.parse(localStorage.getItem(KIND_CACHE_KEY) || '{}');
    const now = Date.now();
    for (const id in raw) if (Array.isArray(raw[id]) && now - raw[id][1] < KIND_TTL) kindStore[id] = raw[id];
} catch (e) {
    kindStore = {};
}
let kindSaveTimer = null;
function persistKinds() {
    clearTimeout(kindSaveTimer);
    kindSaveTimer = setTimeout(() => {
        try {
            const ids = Object.keys(kindStore);
            if (ids.length > 3000) ids.sort((a, b) => kindStore[a][1] - kindStore[b][1]).slice(0, ids.length - 3000).forEach(i => delete kindStore[i]);
            localStorage.setItem(KIND_CACHE_KEY, JSON.stringify(kindStore));
        } catch (e) { /* storage full or blocked: labels just get looked up again next visit */ }
    }, 1000);
}

function classifyDetails(d) {
    const words = ((d.keywords && (d.keywords.keywords || d.keywords.results)) || []).map(k => String(k.name || '').trim());
    let host = '';
    try { host = new URL(d.homepage).hostname.replace(/^www\./, '').toLowerCase(); } catch (e) { /* no website listed */ }
    const short = (d.runtime > 0 && d.runtime <= 40) || words.some(w => /^short film$/i.test(w));
    const ai = words.some(w => KIND_AI_RE.test(w));
    const yt = /(^|\.)(youtube\.com|youtu\.be)$/.test(host) || words.some(w => KIND_YT_RE.test(w));
    return (short ? KIND_SHORT : 0) | (ai ? KIND_AI : 0) | (yt ? KIND_YT : 0);
}

function overrideBits(id) {
    const o = LABEL_OVERRIDES[id];
    if (o === undefined) return undefined;
    const s = String(o).toLowerCase();
    return (/short/.test(s) ? KIND_SHORT : 0) | (/\bai\b/.test(s) ? KIND_AI : 0) | (/youtube/.test(s) ? KIND_YT : 0);
}
// undefined = not looked up yet, 0 = a normal movie, otherwise a mix of the KIND_ flags
function kindBits(id) {
    const o = overrideBits(id);
    if (o !== undefined) return o;
    return kindStore[id] ? kindStore[id][0] : undefined;
}
function kindLabel(bits) {      // "AI/YOUTUBE/SHORT" ; '' for a normal movie
    return [bits & KIND_AI ? 'AI' : '', bits & KIND_YT ? 'YOUTUBE' : '', bits & KIND_SHORT ? 'SHORT' : ''].filter(Boolean).join('/');
}
function kindGenres(bits) {
    return [bits & KIND_SHORT ? 'Short' : '', bits & KIND_AI ? 'AI Generated' : ''].filter(Boolean);
}

const kindWaiting = new Map(), kindQueue = [];
let kindActive = 0;
function storeKind(id, bits) {
    kindStore[id] = [bits, Date.now()];
    persistKinds();
    const cbs = kindWaiting.get(id);
    kindWaiting.delete(id);
    const final = kindBits(id);
    (cbs || []).forEach(cb => cb(final));
}
function pumpKinds() {
    while (kindActive < 3 && kindQueue.length) {
        const id = kindQueue.shift();
        kindActive++;
        tmdb(`https://api.themoviedb.org/3/movie/${id}?api_key=${API_KEY}&append_to_response=keywords`)
            .then(d => storeKind(id, classifyDetails(d)))
            .catch(() => kindWaiting.delete(id))              // network hiccup: the next time the card shows we ask again
            .then(() => { kindActive--; pumpKinds(); });
    }
}
function requestKind(id, cb) {
    const known = kindBits(id);
    if (known !== undefined) return cb(known);
    if (kindWaiting.has(id)) return kindWaiting.get(id).push(cb);
    kindWaiting.set(id, [cb]);
    kindQueue.push(id);
    pumpKinds();
}

// Cards look their title up only when they scroll near the screen, so a row of 20 posters off to the side costs nothing.
let kindObserver = null;
function watchKind(card, movie) {
    if (movie.media_type === 'tv') return;
    const show = bits => applyKind(card, movie, bits);
    const known = kindBits(movie.id);
    if (known !== undefined) return show(known);
    if (!('IntersectionObserver' in window)) return;
    if (!kindObserver) {
        kindObserver = new IntersectionObserver(entries => entries.forEach(en => {
            if (!en.isIntersecting) return;
            kindObserver.unobserve(en.target);
            en.target._kindWatch && requestKind(en.target._kindWatch.id, en.target._kindWatch.show);
        }), {rootMargin: '300px 600px'});
    }
    card._kindWatch = {id: movie.id, show};
    kindObserver.observe(card);
}
function applyKind(card, movie, bits) {
    const tag = card.querySelector('.type-tag'), gl = card.querySelector('.card-genres');
    const label = kindLabel(bits);
    if (tag) {
        const where = originName(movie);
        tag.classList.toggle('is-kind', !!label);
        tag.classList.toggle('is-yt', !!(bits & KIND_YT));
        tag.classList.toggle('is-ai', !!(bits & KIND_AI));
        tag.textContent = label || (where ? `${where} · MOVIE` : 'MOVIE');
        tag.title = label ? (where ? `${where} · ${label}` : label) : tag.textContent;
    }
    if (gl) setGenreLine(gl, movie, bits);
}
function setGenreLine(el, movie, bits) {
    const names = [...kindGenres(bits || 0), ...genreNames(movie)];
    el.textContent = [...new Set(names)].slice(0, 3).join(' · ');
    el.title = [...new Set(names)].join(' · ');
    el.hidden = !names.length;
}
// Info panels (hero, details popup, watch page): a label chip + the extra genres in front of TMDB's own chips.
function decorateChips(box, bits) {
    if (!box) return;
    box.querySelectorAll('.chip-kind').forEach(c => c.remove());
    if (!bits) return;
    const have = new Set([...box.children].map(c => c.textContent));
    const extra = [kindLabel(bits), ...kindGenres(bits)].filter(t => t && !have.has(t));
    box.prepend(...extra.map(t => mk('span', 'chip chip-kind' + (t === kindLabel(bits) ? ' chip-kind-label' : ''), t)));
}

function createMovieCard(movie, opts = {}) {
    if (!movie.poster_path || isBlocked(movie)) return null;
    const title = movie.title || movie.name || 'Untitled';
    const rating = movie.vote_average ? movie.vote_average.toFixed(1) : 'N/A';

    const card = document.createElement('div');
    card.className = 'movie-card';
    card.addEventListener('click', () => playMovie(movie));

    let cam = null;   // no quality badge unless we have a reason to show one
    if (isCinemaOnly(movie)) {
        cam = document.createElement('span');
        cam.className = 'meta-tag cam-tag';
        cam.textContent = 'CAM';
    }

    const rate = document.createElement('span');
    rate.className = 'meta-tag rating-tag';
    rate.textContent = `★ ${rating}`;

    // The poster gets its own wrapper so the heart / bookmark / remove buttons can sit on the picture itself.
    const poster = document.createElement('div');
    poster.className = 'poster';
    const img = document.createElement('img');
    img.src = IMAGE_BASE_URL + movie.poster_path;
    img.alt = title;
    img.loading = 'lazy';
    const actions = document.createElement('div');
    actions.className = 'card-actions';
    actions.append(makeSaveButton('liked', movie), makeSaveButton('watchlist', movie));
    poster.append(img, actions);
    const year = yearOf(movie);                       // release year, bottom-left of the picture (no change to the card's height)
    if (year) {
        const y = document.createElement('span');
        y.className = 'year-tag';
        y.textContent = year;
        poster.appendChild(y);
    }
    // bottom-right of the picture: where it is from + what it is ("South Korea · MOVIE", "United States · SERIES"). Country when TMDB or the Country filter
    // tells us, otherwise the original language. The type matters once TV shows get an episode player.
    const where = originName(movie);
    const kind = movie.media_type === 'tv' ? 'SERIES' : 'MOVIE';
    const t = document.createElement('span');
    t.className = 'type-tag' + (kind === 'SERIES' ? ' is-tv' : '');
    t.textContent = where ? `${where} · ${kind}` : kind;
    t.title = t.textContent;
    poster.appendChild(t);
    const saved = opts.removable && !isSeries(movie) ? progressMap.get(movie.id) : null;      // only the Continue watching cards (a series id could equal a movie id)
    const resume = saved && saved.seconds >= 5 ? saved : null;
    if (resume) {
        const tag = document.createElement('span');
        tag.className = 'resume-tag';
        tag.textContent = `▶ ${fmtTime(resume.seconds)}`;
        tag.title = `Continue from ${fmtTime(resume.seconds)}`;
        poster.appendChild(tag);
        if (resume.duration) {
            const bar = document.createElement('div');
            bar.className = 'resume-bar';
            const fill = document.createElement('i');
            fill.style.width = Math.min(100, (resume.seconds / resume.duration) * 100) + '%';
            bar.appendChild(fill);
            poster.appendChild(bar);
        }
    }

    if (opts.removable && isSeries(movie) && movie.ep) {                  // a series in your history says which episode you were on
        const tag = document.createElement('span');
        tag.className = 'resume-tag';
        tag.textContent = `S${movie.ep.s} · E${movie.ep.e}`;
        tag.title = `Last opened: season ${movie.ep.s}, episode ${movie.ep.e}`;
        poster.appendChild(tag);
    }

    if (opts.removable) {
        const rm = document.createElement('button');
        rm.type = 'button';
        rm.className = 'card-remove';
        rm.innerHTML = ICONS.close;
        rm.title = 'Remove from history';
        rm.setAttribute('aria-label', 'Remove from history');
        rm.addEventListener('click', e => {
            e.stopPropagation();
            removeFromHistory(movie);
        });
        poster.appendChild(rm);
    }

    const h4 = document.createElement('h4');
    h4.textContent = title;

    const gl = document.createElement('div');       // genres under the title, so nobody has to open a title to learn what it is
    gl.className = 'card-genres';
    setGenreLine(gl, movie, kindBits(movie.id));
    card.append(...(cam ? [cam] : []), rate, poster, h4, gl);
    watchKind(card, movie);
    return card;
}

function renderRow(movies, containerId, opts) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '';
    // Lite mode (TV): fewer cards per row keeps scrolling smooth; the Continue watching row is never trimmed.
    const list = isLite && !opts?.removable && movies.length > 14 ? movies.slice(0, 14) : movies;
    list.forEach(movie => {
        const card = createMovieCard(movie, opts);
        if (card) container.appendChild(card);
    });
    ensureArrows(container);
}

// Left/right buttons on a poster row (mouse users cannot swipe). They appear on hover, only when the row really overflows.
// On the home page every row also slides by itself (one card at a time) and shows page dots.
const AUTO_SLIDE_MS = 3000;

function ensureArrows(row) {
    const wrap = row.parentElement;
    if (!wrap || !wrap.classList.contains('carousel-container')) return;
    const auto = PAGE === 'home';
    if (!wrap.querySelector('.row-arrow')) {
        for (const dir of [-1, 1]) {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = `row-arrow ${dir < 0 ? 'prev' : 'next'}`;
            b.setAttribute('aria-label', dir < 0 ? 'Scroll left' : 'Scroll right');
            b.textContent = dir < 0 ? '‹' : '›';
            b.addEventListener('click', () => {
                row.scrollBy({left: dir * cardStep(row), behavior: 'smooth'});
                restartAuto(row);
            });
            wrap.appendChild(b);
        }
        let arrowFrame = 0;     // at most one arrow update per frame while scrolling (it reads the layout, which is costly on a TV)
        row.addEventListener('scroll', () => {
            if (arrowFrame) return;
            arrowFrame = requestAnimationFrame(() => {
                arrowFrame = 0;
                updateArrows(row);
            });
        }, {passive: true});
        window.addEventListener('resize', () => updateArrows(row));
        if (auto) {
            wrap.insertAdjacentHTML('beforeend', '<div class="row-dots" role="presentation"></div>');
            row.classList.add('has-dots');
            // anything the visitor does by hand (wheel, swipe, drag, keys) restarts the timer, so the row never jumps right after they touched it
            ['wheel', 'touchstart', 'pointerdown', 'keydown'].forEach(ev => row.addEventListener(ev, () => restartAuto(row), {passive: true}));
            if ('IntersectionObserver' in window) {
                new IntersectionObserver(entries => {
                    row._onScreen = entries.some(e => e.isIntersecting);
                }).observe(wrap);
            } else row._onScreen = true;
            row._auto = true;
        }
    }
    // layout is not ready the moment cards are added, so measure on the next frame
    requestAnimationFrame(() => updateArrows(row));
    if (row._auto) restartAuto(row);
}

// The distance from one poster to the next (poster width + gap). Arrows and auto-slide both move by exactly this much.
function cardStep(row) {
    const cards = row.querySelectorAll('.movie-card');
    return cards.length > 1 ? cards[1].offsetLeft - cards[0].offsetLeft : row.clientWidth * 0.85;
}

// One card every AUTO_SLIDE_MS; at the end it glides back to the start. Hovering does NOT pause it (the arrows can undo a miss),
// but it stays still for people who asked their system for reduced motion, in hidden tabs, and off-screen.
function restartAuto(row) {
    clearTimeout(row._timer);
    if (!row._auto || reducedMotion()) return;
    row._timer = setTimeout(() => {
        const cards = row.querySelectorAll('.movie-card');
        if (cards.length > 1 && row._onScreen !== false && !document.hidden && !row.matches(':has(:focus-visible)')) {
            const step = cardStep(row);
            const max = row.scrollWidth - row.clientWidth;
            if (max > 8) row.scrollTo({
                left: row.scrollLeft > max - 8 ? 0 : Math.min(row.scrollLeft + step, max),
                behavior: 'smooth'
            });
        }
        restartAuto(row);
    }, AUTO_SLIDE_MS);
}

function updateArrows(row) {
    const wrap = row.parentElement;
    if (!wrap) return;
    const prev = wrap.querySelector('.row-arrow.prev'), next = wrap.querySelector('.row-arrow.next');
    if (!prev || !next) return;
    const max = row.scrollWidth - row.clientWidth;
    prev.hidden = row.scrollLeft < 8;
    next.hidden = max < 8 || row.scrollLeft > max - 8;
    updateDots(row, max);
}

function updateDots(row, max) {
    const box = row.parentElement.querySelector('.row-dots');
    if (!box) return;
    const pages = max < 8 ? 0 : Math.min(12, Math.ceil(row.scrollWidth / row.clientWidth));
    if (box.children.length !== pages) {
        box.replaceChildren(...Array.from({length: pages}, (_, i) => {
            const d = document.createElement('button');
            d.type = 'button';
            d.className = 'row-dot';
            d.setAttribute('aria-label', `Go to page ${i + 1}`);
            d.addEventListener('click', () => {
                row.scrollTo({left: (max * i) / (pages - 1), behavior: 'smooth'});
                restartAuto(row);
            });
            return d;
        }));
    }
    const active = pages > 1 ? Math.round((row.scrollLeft / max) * (pages - 1)) : 0;
    [...box.children].forEach((d, i) => d.classList.toggle('active', i === active));
}

// --- ENDLESS SCROLL (genre, network and search pages) ---
// TMDB hands out results 20 at a time ("pages"). When the visitor scrolls close to the bottom we quietly
// ask for the next page and add its cards. After PAGES_PER_BATCH pages we pause and show a "Load more"
// button instead: that keeps the page light on phones and keeps the footer reachable.
const PAGES_PER_BATCH = 5;
let pager = null;

function resetPager() {
    if (pager) pager.observer.disconnect();
    pager = null;
    document.getElementById('grid-end')?.remove();
}

function startPager(urlFor, firstData, firstResults, prepare) {
    const totalPages = Math.min(firstData.total_pages || 1, 500);      // TMDB never serves beyond page 500
    const grid = document.getElementById('movie-grid');
    if (!grid || totalPages < 2) return;

    const end = document.createElement('div');
    end.id = 'grid-end';
    end.className = 'grid-end';
    end.innerHTML = '<p class="grid-end-msg" role="status"></p><button type="button" class="grid-more-btn" hidden>Load more</button>';
    grid.after(end);

    const p = pager = {
        urlFor, prepare, total: totalPages, page: 1, loading: false, batchLeft: PAGES_PER_BATCH,
        seen: new Set(firstResults.map(m => m.id)), end, capped: (firstData.total_pages || 1) > 500,
        msg: end.querySelector('.grid-end-msg'), btn: end.querySelector('.grid-more-btn'),
        observer: new IntersectionObserver(entries => {
            if (entries.some(e => e.isIntersecting)) loadNextPage();
        }, {rootMargin: '900px 0px'})
    };
    p.btn.addEventListener('click', () => {
        p.batchLeft = PAGES_PER_BATCH;
        loadNextPage();
    });
    p.observer.observe(end);
}

function pagerStatus(p, kind) {
    p.btn.hidden = true;
    p.btn.textContent = 'Load more';
    if (kind === 'loading') p.msg.textContent = 'Summoning more...';
    else if (kind === 'done') p.msg.textContent = p.capped
        ? 'That is as far as TMDB lets any list go (10,000 titles). Use the filters (year, country, genre) to dig into the rest.'
        : 'You have reached the bottom of the void.';
    else if (kind === 'more') {
        p.msg.textContent = '';
        p.btn.hidden = false;
    } else if (kind === 'error') {
        p.msg.textContent = 'Could not load more titles.';
        p.btn.hidden = false;
        p.btn.textContent = 'Try again';
    } else p.msg.textContent = '';
}

async function loadNextPage() {
    const p = pager;
    if (!p || p.loading || p.page >= p.total || p.batchLeft <= 0) return;
    p.loading = true;
    pagerStatus(p, 'loading');
    try {
        const data = await tmdb(p.urlFor(p.page + 1));
        if (pager !== p) return;                                          // filters changed while we waited: drop this page
        p.page++;
        p.batchLeft--;
        const grid = document.getElementById('movie-grid');
        p.prepare(data.results).forEach(m => {
            if (p.seen.has(m.id)) return;                                   // pages can overlap when TMDB re-sorts
            p.seen.add(m.id);
            const card = createMovieCard(m);                                // null when there is no poster / title is blocked
            if (card) grid.appendChild(card);
        });
    } catch (err) {
        if (pager !== p) return;
        console.error(err);
        p.loading = false;
        pagerStatus(p, 'error');
        return;
    }
    p.loading = false;
    if (p.page >= p.total) return pagerStatus(p, 'done');
    if (p.batchLeft <= 0) return pagerStatus(p, 'more');
    pagerStatus(p, '');
    p.observer.unobserve(p.end);
    p.observer.observe(p.end);            // still near the bottom? this fires again
}

// --- BACK TO TOP ---
function setupBackToTop() {
    const btn = document.getElementById('to-top');
    if (!btn) return;
    let ticking = false;
    const update = () => {
        ticking = false;
        btn.classList.toggle('show', window.scrollY > window.innerHeight * 1.2);
    };
    window.addEventListener('scroll', () => {
        if (!ticking) {
            ticking = true;
            requestAnimationFrame(update);
        }
    }, {passive: true});
    btn.addEventListener('click', () => window.scrollTo({top: 0, behavior: reducedMotion() ? 'auto' : 'smooth'}));
    update();
}

function renderGrid(movies) {
    const grid = document.getElementById('movie-grid');
    if (!grid) return;
    grid.innerHTML = '';
    movies.forEach(movie => {
        const card = createMovieCard(movie);
        if (card) grid.appendChild(card);
    });
}

// --- HERO BANNER ---
// One big featured title. On the home page it also shows a strip of thumbnails and rotates by itself;
// on category pages it is just a single featured title (setHeroBanner(movie) with no options).
const HERO_MS = 8000;
let heroList = [], heroIndex = 0, heroTimer = null, heroHovered = false;
const detailsCache = new Map();   // movie id -> details response, so a title is only fetched once

const reducedMotion = () => isLite || (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
const yearOf = m => (m.release_date || m.first_air_date || '').slice(0, 4);

async function getDetails(id) {
    if (detailsCache.has(id)) return detailsCache.get(id);
    const data = await tmdb(`https://api.themoviedb.org/3/movie/${id}?api_key=${API_KEY}&append_to_response=credits,videos,keywords`);
    detailsCache.set(id, data);
    if (data && data.keywords) storeKind(id, classifyDetails(data));      // the details already hold what the label needs
    return data;
}

function setHeroBanner(movie, opts = {}) {
    heroMovie = movie;
    endHeroSkeleton();
    const banner = document.getElementById('hero-banner');
    if (!banner) return;
    // crossfade: keep the OLD picture on a layer that fades out (see .hero-swap in style.css) and let the text slide in again
    if (!reducedMotion()) {
        banner.style.setProperty('--prev-bg', banner.style.backgroundImage || 'none');
        banner.classList.remove('hero-swap');
        void banner.offsetWidth;   // restart the CSS animations
        banner.classList.add('hero-swap');
    }
    // Some titles have no backdrop image; "url(...null)" would be a broken request.
    banner.style.backgroundImage = movie.backdrop_path ? `url(${BACKDROP_BASE_URL + movie.backdrop_path})` : 'none';
    banner.style.display = 'flex';
    document.getElementById('hero-title').innerText = movie.title || movie.name || '';
    setText('hero-kicker', opts.kicker || 'FEATURED');

    // rating ring: the arc is filled to the score (0-10 -> 0-100%)
    const score = movie.vote_average || 0;
    document.getElementById('hero-ring').style.setProperty('--pct', Math.round(score * 10));
    setText('hero-rating', score ? score.toFixed(1) : 'N/A');

    document.getElementById('hero-overview').innerText = movie.overview || '';
    const camEl = document.getElementById('hero-quality');
    if (camEl) camEl.style.display = isCinemaOnly(movie) ? '' : 'none';

    const poster = document.getElementById('hero-poster');
    poster.style.display = movie.poster_path ? '' : 'none';
    if (movie.poster_path) poster.src = IMAGE_BASE_URL + movie.poster_path;

    // genre chips come from the ids we already have; year now, runtime + country once the details arrive
    const chips = genreNames(movie).slice(0, 3);
    document.getElementById('hero-genres').replaceChildren(...chips.map(g => {
        const s = document.createElement('span');
        s.className = 'chip';
        s.textContent = g;
        return s;
    }));
    setHeroFacts(movie, null);
    decorateChips(document.getElementById('hero-genres'), kindBits(movie.id));
    getDetails(movie.id).then(d => {
        if (heroMovie === movie) {
            setHeroFacts(movie, d);
            decorateChips(document.getElementById('hero-genres'), kindBits(movie.id));
        }
    }).catch(() => {
    });

    // the + button is a watchlist toggle for whichever title is featured
    const wl = document.getElementById('hero-watchlist');
    if (wl) {
        wl.dataset.key = savedKey(movie);
        setSaveButtonState(wl, savedLists.watchlist.has(wl.dataset.key));
    }

    if (!opts.list) stopHeroRotation();   // category pages: a single title, nothing rotates
}

function setHeroFacts(movie, d) {
    const parts = [yearOf(movie)];
    if (d?.runtime) parts.push(`${d.runtime} min`);
    if (d?.production_countries?.[0]) parts.push(d.production_countries[0].name);
    setText('hero-facts', parts.filter(Boolean).join('  •  '));
    // if the genre ids were missing, fall back to the names from the details
    const chipBox = document.getElementById('hero-genres');
    if (d && chipBox && !chipBox.querySelector('.chip:not(.chip-kind)')) {
        chipBox.replaceChildren(...d.genres.slice(0, 3).map(g => {
            const s = document.createElement('span');
            s.className = 'chip';
            s.textContent = g.name;
            return s;
        }));
    }
}

function stopHeroRotation() {
    clearTimeout(heroTimer);
    heroTimer = null;
    heroList = [];
    const strip = document.getElementById('hero-strip');
    if (strip) {
        strip.replaceChildren();
        strip.style.display = 'none';
    }
}

// Home page: start the rotating hero from a list of trending movies.
function startHero(list) {
    heroList = list;
    heroIndex = 0;
    const strip = document.getElementById('hero-strip');
    const banner = document.getElementById('hero-banner');
    if (!strip || !banner) return;
    strip.style.display = '';
    strip.replaceChildren(...list.map((m, i) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'hero-thumb';
        b.setAttribute('role', 'tab');
        b.setAttribute('aria-label', m.title || m.name || 'Title');
        const img = document.createElement('img');
        img.src = IMAGE_BASE_URL + m.poster_path;
        img.alt = '';
        img.loading = 'lazy';
        const bar = document.createElement('span');
        bar.className = 'bar';
        b.append(img, bar);
        b.addEventListener('click', () => showHero(i));
        return b;
    }));
    banner.addEventListener('mouseenter', () => {
        heroHovered = true;
        clearTimeout(heroTimer);
        clearTimeout(trailer.timer);
        banner.classList.add('paused');
        holdTrailer('hover');
    });
    banner.addEventListener('mouseleave', () => {
        heroHovered = false;
        banner.classList.remove('paused');
        if (!heroList.length) return;
        if (trailer.playing) releaseTrailer('hover');   // a trailer that was playing simply carries on
        else {
            trailer.holds.delete('hover');
            showHero(heroIndex);
        }
    });
    // swipe left / right on a touch screen to change the featured title (the thumbnail strip is hidden on phones)
    let touchX = null;
    banner.addEventListener('touchstart', e => {
        touchX = e.touches[0].clientX;
    }, {passive: true});
    banner.addEventListener('touchend', e => {
        if (touchX === null) return;
        const dx = e.changedTouches[0].clientX - touchX;
        touchX = null;
        if (Math.abs(dx) > 50) showHero(heroIndex + (dx < 0 ? 1 : -1));
    }, {passive: true});
    // pause the trailer whenever the hero is off screen or the tab is hidden (saves data and battery)
    if ('IntersectionObserver' in window) new IntersectionObserver(es => es.forEach(e => (e.intersectionRatio < 0.35 ? holdTrailer('offscreen') : releaseTrailer('offscreen'))), {threshold: [0, 0.35, 1]}).observe(banner);
    document.addEventListener('visibilitychange', () => (document.hidden ? holdTrailer('tab') : releaseTrailer('tab')));
    showHero(0);
}

function showHero(i) {
    if (!heroList.length) return;
    heroIndex = (i + heroList.length) % heroList.length;
    stopTrailer();
    const token = ++trailer.token;
    const movie = heroList[heroIndex];
    setHeroBanner(movie, {kicker: 'TRENDING NOW', list: true});
    const thumbs = document.querySelectorAll('#hero-strip .hero-thumb');
    thumbs.forEach((t, n) => {
        const on = n === heroIndex;
        t.classList.remove('active');
        void t.offsetWidth;   // reflow, so the progress bar animation restarts from zero
        t.classList.toggle('active', on);
        t.setAttribute('aria-selected', String(on));
        t.querySelector('.bar').style.animationDuration = '';
    });
    clearTimeout(heroTimer);
    // no automatic rotation for people who asked their system for reduced motion, or while the mouse is over the hero
    if (!reducedMotion() && !heroHovered) heroTimer = setTimeout(() => showHero(heroIndex + 1), HERO_MS);
    scheduleTrailer(movie, token);
}

// --- HERO TRAILERS ---
// Sequence per title: image for TRAILER_DELAY, then its YouTube trailer plays muted behind the text (up to TRAILER_MAX),
// then the hero moves to the next title. Only on big screens with a mouse; phones and tablets keep the still image.
// Titles without a trailer, or any failure at all, just fall back to the normal 8-second image rotation.
const TRAILER_DELAY = 3000, TRAILER_MAX = 25000, TRAILER_START = 4;
const trailer = {
    player: null, ready: false, api: null, token: 0, timer: null, capTimer: null, playing: false, activeToken: 0,
    holds: new Set(), pausedByHold: false, capEnd: 0, remaining: 0, armed: false, watchdog: null, pending: null
};

const trailersAllowed = () =>
    window.matchMedia('(min-width: 1025px) and (hover: hover)').matches && !reducedMotion() && !isLite && !navigator.connection?.saveData;

function pickTrailer(d) {
    const vids = (d?.videos?.results || []).filter(v => v.site === 'YouTube' && v.key);
    const best = vids.find(v => v.type === 'Trailer' && v.official) || vids.find(v => v.type === 'Trailer') || vids.find(v => v.type === 'Teaser');
    return best ? best.key : null;
}

function loadYouTubeApi() {
    if (trailer.api) return trailer.api;
    trailer.api = new Promise((resolve, reject) => {
        if (window.YT && window.YT.Player) return resolve();
        const done = setTimeout(() => reject(new Error('YouTube API timed out')), 8000);
        window.onYouTubeIframeAPIReady = () => {
            clearTimeout(done);
            resolve();
        };
        const tag = document.createElement('script');
        tag.src = 'https://www.youtube.com/iframe_api';
        tag.onerror = () => {
            clearTimeout(done);
            reject(new Error('YouTube API blocked'));
        };
        document.head.appendChild(tag);
    }).catch(err => {
        trailer.api = null;
        throw err;
    });
    return trailer.api;
}

async function scheduleTrailer(movie, token) {
    if (!trailersAllowed()) return;
    let details;
    try {
        details = await getDetails(movie.id);
    } catch (e) {
        return;
    }
    if (token !== trailer.token) return;               // the hero already moved on
    const key = pickTrailer(details);
    if (!key) return;                                   // no trailer: the normal image rotation continues
    clearTimeout(heroTimer);                            // the trailer decides when the hero moves on
    const bar = document.querySelector('#hero-strip .hero-thumb.active .bar');
    if (bar) {
        bar.style.animationDuration = `${(TRAILER_DELAY + TRAILER_MAX) / 1000}s`;
        const t = bar.parentElement;
        t.classList.remove('active');
        void t.offsetWidth;
        t.classList.add('active');
    }
    if (heroHovered) return;                            // mouse is on the hero: showHero runs again when it leaves
    // safety net: if the trailer never starts (blocked, slow, broken), do not leave the hero stuck on one title
    trailer.watchdog = setTimeout(() => {
        if (token === trailer.token && !trailer.playing) trailerFailed(token);
    }, TRAILER_DELAY + 12000);
    trailer.timer = setTimeout(() => playTrailer(key, token), TRAILER_DELAY);
}

async function playTrailer(key, token) {
    try {
        await loadYouTubeApi();
    } catch (err) {
        console.warn('trailer:', err.message);
        return trailerFailed(token);
    }
    if (token !== trailer.token) return;
    trailer.activeToken = token;
    const box = document.getElementById('hero-trailer');
    if (!box) return;
    const opts = {videoId: key, startSeconds: TRAILER_START};
    trailer.pending = opts;
    if (trailer.player && trailer.ready) {
        trailer.player.loadVideoById(opts);
        return;
    }
    if (trailer.player) return;                         // still starting up; its onReady will play what was asked last
    const holder = document.createElement('div');
    holder.id = 'hero-trailer-player';
    box.appendChild(holder);
    trailer.player = new YT.Player('hero-trailer-player', {
        videoId: key,
        playerVars: {
            autoplay: 1,
            mute: 1,
            controls: 0,
            disablekb: 1,
            fs: 0,
            modestbranding: 1,
            rel: 0,
            playsinline: 1,
            iv_load_policy: 3,
            start: TRAILER_START,
            origin: location.origin
        },
        events: {
            onReady: e => {
                trailer.ready = true;
                fitTrailer();
                if (trailer.pending && trailer.activeToken === trailer.token) e.target.loadVideoById(trailer.pending);
            },
            onStateChange: e => onTrailerState(e.data),
            onError: () => trailerFailed(trailer.activeToken)
        }
    });
}

function onTrailerState(state) {
    if (trailer.activeToken !== trailer.token) return;  // an old title's video
    const box = document.getElementById('hero-trailer');
    if (state === 1) {                                  // PLAYING
        fitTrailer();
        box?.classList.add('on');
        const snd = document.getElementById('trailer-sound');
        if (snd) snd.style.display = '';
        trailer.playing = true;
        clearTimeout(trailer.watchdog);
        // YouTube also reports "playing" after every pause/resume and every buffering hiccup. Only the FIRST one of a title
        // starts the 25-second countdown; later ones must not restart it (or leave a second timer running).
        if (trailer.armed) return;
        trailer.armed = true;
        if (trailer.holds.size) {
            trailer.player.pauseVideo();
            trailer.pausedByHold = true;
            trailer.remaining = TRAILER_MAX;
            return;
        }
        clearTimeout(trailer.capTimer);
        trailer.capEnd = Date.now() + TRAILER_MAX;
        trailer.capTimer = setTimeout(nextAfterTrailer, TRAILER_MAX);
    } else if (state === 0) {                           // ENDED
        nextAfterTrailer();
    }
}

function nextAfterTrailer() {
    if (!heroHovered) showHero(heroIndex + 1);
}

function trailerFailed(token) {
    if (token !== trailer.token) return;
    stopTrailer();
    if (!heroHovered) heroTimer = setTimeout(() => showHero(heroIndex + 1), 4000);   // keep the image a little, then move on
}

function stopTrailer() {
    clearTimeout(trailer.timer);
    clearTimeout(trailer.capTimer);
    clearTimeout(trailer.watchdog);
    trailer.playing = false;
    trailer.armed = false;
    trailer.pausedByHold = false;
    trailer.pending = null;
    document.getElementById('hero-trailer')?.classList.remove('on');
    const btn = document.getElementById('trailer-sound');
    if (btn) btn.style.display = 'none';
    if (trailer.player && trailer.ready) {
        try {
            trailer.player.pauseVideo();
        } catch (e) { /* player gone */
        }
    }
}

// Reasons to hold a playing trailer: the mouse is on the hero, the hero is scrolled away, the tab is hidden.
function holdTrailer(reason) {
    trailer.holds.add(reason);
    if (trailer.playing && !trailer.pausedByHold) {
        trailer.remaining = Math.max(1500, trailer.capEnd - Date.now());
        clearTimeout(trailer.capTimer);
        trailer.player.pauseVideo();
        trailer.pausedByHold = true;
    }
}

function releaseTrailer(reason) {
    trailer.holds.delete(reason);
    if (trailer.playing && trailer.pausedByHold && !trailer.holds.size) {
        trailer.pausedByHold = false;
        clearTimeout(trailer.capTimer);
        trailer.player.playVideo();
        trailer.capEnd = Date.now() + trailer.remaining;
        trailer.capTimer = setTimeout(nextAfterTrailer, trailer.remaining);
    }
}

function toggleTrailerSound() {
    if (!trailer.player || !trailer.ready) return;
    const btn = document.getElementById('trailer-sound');
    if (!btn) return;
    if (trailer.player.isMuted()) {
        trailer.player.unMute();
        btn.innerHTML = UI.volOn;
        btn.setAttribute('aria-label', 'Turn trailer sound off');
    } else {
        trailer.player.mute();
        btn.innerHTML = UI.volOff;
        btn.setAttribute('aria-label', 'Turn trailer sound on');
    }
}

// YouTube serves 16:9 video. Scale it so it always covers the hero (like background-size: cover), cropping the sides or the top.
function fitTrailer() {
    const banner = document.getElementById('hero-banner'), frame = document.querySelector('#hero-trailer iframe');
    if (!banner || !frame) return;
    const w = banner.clientWidth, h = banner.clientHeight;
    const vw = Math.max(w, (h * 16) / 9), vh = Math.max(h, (w * 9) / 16);
    frame.style.width = `${vw}px`;
    frame.style.height = `${vh}px`;
}

window.addEventListener('resize', () => fitTrailer());

// --- POP-UP (movie details, saga lists) ---
let modalReturnFocus = null;

function openModal(node) {
    const overlay = document.getElementById('ruin-modal');
    if (!overlay) return;
    modalReturnFocus = document.activeElement;
    document.getElementById('modal-body').replaceChildren(node);
    overlay.style.display = 'flex';
    document.body.style.overflow = 'hidden';   // the page behind must not scroll
    overlay.querySelector('.modal-close')?.focus();
    refreshSavedUI();
}

function closeModal() {
    const overlay = document.getElementById('ruin-modal');
    if (!overlay || overlay.style.display === 'none') return;
    overlay.style.display = 'none';
    document.body.style.overflow = '';
    if (modalReturnFocus && document.contains(modalReturnFocus)) modalReturnFocus.focus();
}

document.addEventListener('keydown', e => {
    const overlay = document.getElementById('ruin-modal');
    if (!overlay || overlay.style.display === 'none') return;
    if (e.key === 'Escape') {
        closeModal();
        return;
    }
    if (e.key === 'Tab') {   // keep keyboard focus inside the pop-up
        const items = [...overlay.querySelectorAll('button, a[href]')].filter(el => !el.disabled);
        if (!items.length) return;
        const first = items[0], last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
        }
    }
});

function mk(tag, className, text) {
    const n = document.createElement(tag);
    if (className) n.className = className;
    if (text !== undefined) n.textContent = text;
    return n;
}

function modalSaveButton(list, movie, label) {
    const b = mk('button', 'hero-btn modal-save');
    b.type = 'button';
    b.dataset.list = list;
    b.dataset.key = savedKey(movie);
    b.innerHTML = (list === 'liked' ? ICONS.heart : ICONS.bookmark) + `<span>${label}</span>`;
    b.addEventListener('click', () => toggleSaved(list, movie));
    setSaveButtonState(b, savedLists[list].has(b.dataset.key));
    return b;
}

async function openDetails(movie) {
    if (!movie) return;
    const box = mk('div', 'details');
    const poster = mk('img', 'details-poster');
    poster.alt = '';
    if (movie.poster_path) poster.src = IMAGE_BASE_URL + movie.poster_path; else poster.style.display = 'none';
    const info = mk('div', 'details-info');
    const title = mk('h2', '', movie.title || movie.name || '');
    title.id = 'modal-title';
    const facts = mk('p', 'details-facts', [yearOf(movie), movie.vote_average ? `★ ${movie.vote_average.toFixed(1)}` : ''].filter(Boolean).join('  •  '));
    const chipBox = mk('div', 'hero-genres');
    const overview = mk('p', 'details-overview', movie.overview || 'No description yet.');
    const cast = mk('p', 'details-cast');
    const actions = mk('div', 'hero-buttons');
    const play = mk('button', 'play-btn', '');
    play.innerHTML = `${UI.play} ENTER THE VOID`;
    play.type = 'button';
    play.addEventListener('click', () => playMovie(movie));
    actions.append(play, modalSaveButton('liked', movie, 'Like'), modalSaveButton('watchlist', movie, 'Watch later'));
    info.append(title, facts, chipBox, overview, cast, actions);
    box.append(poster, info);
    openModal(box);

    try {
        const d = await getDetails(movie.id);
        if (!document.contains(box)) return;   // closed or replaced while loading
        const bits = [yearOf(movie) || (d.release_date || '').slice(0, 4), d.runtime ? `${d.runtime} min` : '', d.production_countries?.[0]?.name, movie.vote_average ? `★ ${movie.vote_average.toFixed(1)}` : ''];
        facts.textContent = bits.filter(Boolean).join('  •  ');
        chipBox.replaceChildren(...d.genres.slice(0, 4).map(g => mk('span', 'chip', g.name)));
        decorateChips(chipBox, kindBits(movie.id));
        if (d.tagline) overview.textContent = `“${d.tagline}” — ${d.overview || movie.overview || ''}`;
        else if (d.overview) overview.textContent = d.overview;
        const names = (d.credits?.cast || []).slice(0, 5).map(c => c.name);
        if (names.length) cast.textContent = 'Starring: ' + names.join(', ');
    } catch (err) {
        console.error(err);
    }
}

// --- PLAYER LOGIC ---
// Pressing play anywhere takes you to that movie's own page (watch.html?id=...), where the player lives.
const watchUrl = id => pageUrl('watch') + '?id=' + id;
const personUrl = id => pageUrl('person') + '?id=' + id;
const seriesUrl = (id, s, e) => pageUrl('series') + '?id=' + id + (s ? `&s=${s}${e ? `&e=${e}` : ''}` : '');

function playHeroMovie() {
    playMovie(heroMovie);
}

function playMovie(movie) {
    if (isBlocked(movie)) {
        showToast('This title is no longer available.');
        return;
    }
    // A series has its own page (seasons + episodes). The movie player must never receive a series id: it would load a different movie.
    if (movie.media_type === 'tv') {
        location.href = movie.ep ? seriesUrl(movie.id, movie.ep.s, movie.ep.e) : seriesUrl(movie.id);      // a history card reopens at its episode
        return;
    }
    location.href = watchUrl(movie.id);
}

// --- STREAM PLAYER ---
// Your own library first (8788). A file on this machine cannot expire, cannot 403 and cannot hand you a cam rip.
// If it has nothing, the grab daemon (8789) is asked straight away and the loading state covers it. Providers
// (8787) are the last resort and only run when the fetch fails or the viewer asks for them. No iframes anywhere.
//
// All three daemons are reached on the SAME hostname the page came from (localhost, a LAN address, ruintv.to),
// so the origin always matches and <track crossOrigin="anonymous"> is accepted.
const DAEMON_HOST = location.hostname || '127.0.0.1';
const DAEMON_PROTO = location.protocol === 'https:' ? 'https:' : 'http:';
const LIBRARY_API = `${DAEMON_PROTO}//${DAEMON_HOST}:8788`;
const STREAM_API = `${DAEMON_PROTO}//${DAEMON_HOST}:8787`;
const GRAB_API = `${DAEMON_PROTO}//${DAEMON_HOST}:8789`;

// How long a source may take to produce a manifest or metadata before we treat it as dead.
const STALL_MS = 20000;
// How many automatic re-resolves (fresh tokens) a single player session may use before giving up.
const MAX_RETRIES = 2;
// The relay holds a first response to a floor and then streams the rest through /more, so this is a backstop only.
const RESOLVE_TIMEOUT_MS = 40000;
// The relay forgets a job after 180 s, and the host tokens baked into its URLs die with it. A list older than
// this is re-resolved before it is used, so picking a source from an old menu never hands the player a 401.
// Library URLs carry no token, so they never need this.
const SOURCE_TTL_MS = 150000;

let hls = null, streamSources = [], sourceIndex = 0, playerMovie = null;
let streamImdb = null, moreSourcesPending = false, waitingForMore = false;
let hideTimer = null, saveTimer = null, lastSaved = 0;
let retriesUsed = 0, playerBound = false, stallBound = false;
let playToken = 0, stallTimer = null, resolveSession = 0, resolveCtrl = null, resolvedAt = 0;
// Where playback had reached when the current source was torn down, and whether the saved position was already restored.
let carryTime = 0, progressRestored = false;
// True once the viewer picked a source by hand: from then on a newly arrived digital copy must not override them.
let manualPick = false;
// Which resolve path the current session is on: 'auto' tries the library then fetches, 'providers' skips to the relay.
let resolveMode = 'auto';

const pel = id => document.getElementById(id);
const playerShell = () => pel('player-shell');
const vid = () => pel('video-player');

function fmtTime(s) {
    s = Math.max(0, Math.floor(s || 0));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    return h
        ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
        : `${m}:${String(sec).padStart(2, '0')}`;
}

// player-ui.js replaces this with an auto-hiding version; the fallback keeps script.js usable on its own.
function pToast(msg) {
    const t = pel('pl-toast');
    if (!t) return;
    t.textContent = msg || '';
    t.hidden = !msg;
}

function clearStall() {
    clearTimeout(stallTimer);
    stallTimer = null;
}

// A viewer pressing pause is not a dead server. The watchdog is dropped on pause and on seek, and started
// again on play, so a source standing still on purpose is never torn down and swapped out from under them.
function bindStallGuard() {
    const v = vid();
    if (!v) return;
    v.addEventListener('pause', () => {
        if (!v.ended) clearStall();
    });
    v.addEventListener('play', () => {
        if (!stallTimer && v.readyState < 2) armStall(playToken);
    });
    v.addEventListener('seeking', clearStall);
    v.addEventListener('seeked', () => {
        if (!stallTimer && !v.paused && v.readyState < 2) armStall(playToken);
    });
}

// Starts the stall watchdog for one attempt. If nothing plays in time the source is abandoned.
function armStall(token) {
    clearStall();
    stallTimer = setTimeout(() => {
        if (token !== playToken) return;
        const v = vid();
        if (!v) return;
        if (v.paused || v.seeking) return;   // idle on purpose: leave it, play/seeked re-arm
        if (v.readyState >= 2) return;       // it is actually playing
        failSource(token, sourceIndex + 1);
    }, STALL_MS);
}

// A source is dead: drop it and move on.
function failSource(token, nextIndex) {
    if (token !== playToken) return;
    clearStall();
    teardownPlayer();
    playSource(nextIndex);
}

function initPlayer(m) {
    const shell = playerShell();
    if (!shell) return;
    // A resolve may still be in flight for the previous title. Cancel it here, or its guard would block this one.
    resolveSession++;
    if (resolveCtrl) {
        try {
            resolveCtrl.abort();
        } catch (e) { /* already finished */
        }
        resolveCtrl = null;
    }
    playerMovie = m;
    streamSources = [];
    sourceIndex = 0;
    retriesUsed = 0;
    lastSaved = 0;
    carryTime = 0;
    progressRestored = false;
    resolvedAt = 0;
    streamImdb = m.imdb_id || null;
    moreSourcesPending = false;
    waitingForMore = false;
    manualPick = false;
    resolveMode = 'auto';
    hideMiss();
    // crossOrigin has to be on the element before any src or <track> is attached, or the subtitle fetch is blocked.
    const v = vid();
    if (v && !v.crossOrigin) v.crossOrigin = 'anonymous';
    if (!playerBound) {
        bindPlayerControls();
        playerBound = true;
    }
    if (!stallBound) {
        bindStallGuard();
        stallBound = true;
    }
    resolveStreams();
}

// --- the library (8788) ---
// One entry per file that exists on this machine for this title. The library also hands out its sidecar
// subtitles as WebVTT, already converted, so nothing here has to parse SRT.
async function librarySources(id) {
    try {
        const r = await fetch(`${LIBRARY_API}/index.json?tmdb=${encodeURIComponent(id)}`);
        if (!r.ok) return [];
        const data = await r.json();
        const files = Array.isArray(data?.files) ? data.files : [];
        return files.map(f => {
            const direct = f.kind === 'mp4';
            return {
                label: f.height ? `LOCAL · ${f.height}p` : 'LOCAL',
                provider: 'library',
                local: true,
                kind: direct ? 'mp4' : 'hls',
                // a browser-safe file is streamed as it is; anything else is remuxed by the library into fMP4 HLS
                url: `${LIBRARY_API}${direct ? '/file/' : '/stream/'}${id}/${f.index}`,
                seconds: f.seconds || 0,
                subtitles: (f.subtitles || []).map(s => ({label: s.label, lang: s.lang, url: s.url})),
                meta: {height: f.height || null, tags: [], cam: false},
            };
        });
    } catch (err) {
        console.warn('library unreachable:', err.message || err);
        return [];
    }
}

// ---- the fetching state -------------------------------------------------------------------------------------------
// A title with no local file starts fetching itself. The overlay is a ring, a changing line and a progress bar; the
// escape hatches (providers, rescan) only appear if something actually fails. Nothing here is a static panel.
let missStylesDone = false;

function ensureMissStyles() {
    if (missStylesDone) return;
    missStylesDone = true;
    const s = document.createElement('style');
    s.id = 'pl-miss-styles';
    s.textContent = `
@keyframes plm-spin { to { transform: rotate(360deg); } }
@keyframes plm-pulse { 0%, 100% { opacity: .28; transform: scale(1); } 50% { opacity: .62; transform: scale(1.1); } }
@keyframes plm-in { from { opacity: 0; transform: translateY(7px); } to { opacity: 1; transform: none; } }
@keyframes plm-bar { from { background-position: 0 0; } to { background-position: 34px 0; } }
#pl-miss {
  position: absolute; top: 0; right: 0; bottom: 0; left: 0; z-index: 6; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 13px; padding: 26px; text-align: center;
  background: radial-gradient(circle at 50% 42%, rgba(122,0,0,.20), rgba(5,5,7,.95) 62%);
  backdrop-filter: blur(7px); -webkit-backdrop-filter: blur(7px);
}
#pl-miss .plm-box { position: relative; display: grid; place-items: center; width: 150px; height: 150px; }
#pl-miss .plm-glow { position: absolute; width: 140px; height: 140px; border-radius: 50%;
  background: radial-gradient(circle, rgba(218,0,0,.55), transparent 68%); filter: blur(9px); animation: plm-pulse 2.7s ease-in-out infinite; }
#pl-miss .plm-ring { position: relative; width: 62px; height: 62px; border-radius: 50%;
  background: conic-gradient(from 0deg, rgba(218,0,0,0) 0 30%, #da0000 68%, #ff7a7a 100%);
  -webkit-mask: radial-gradient(circle, transparent 23px, #000 24px); mask: radial-gradient(circle, transparent 23px, #000 24px);
  animation: plm-spin 1.15s linear infinite; }
#pl-miss .plm-check { width: 62px; height: 62px; border-radius: 50%; display: grid; place-items: center;
  background: rgba(28,181,105,.15); border: 1px solid rgba(28,181,105,.55); color: #3ce08f; font-size: 25px; animation: plm-in .3s ease both; }
#pl-miss .plm-kicker { font: 800 9.5px Montserrat, sans-serif; letter-spacing: .3em; text-transform: uppercase; color: #ff8f8f; animation: plm-in .35s ease both; }
#pl-miss .plm-line { font: 800 15.5px Montserrat, sans-serif; letter-spacing: .01em; color: #fff; max-width: 430px; animation: plm-in .35s ease both; }
#pl-miss .plm-sub { font: 500 12.5px Montserrat, sans-serif; line-height: 1.6; color: #9a9a9a; max-width: 410px; animation: plm-in .35s ease both; }
#pl-miss .plm-bar { width: min(270px, 72%); height: 4px; border-radius: 99px; background: rgba(255,255,255,.11); overflow: hidden; }
#pl-miss .plm-bar > i { display: block; height: 100%; width: 0; border-radius: 99px; transition: width .6s cubic-bezier(.2,.8,.2,1);
  background: linear-gradient(90deg, #7d0000, #ff4d4d); box-shadow: 0 0 14px rgba(218,0,0,.75); }
#pl-miss .plm-bar.indet > i { width: 38%; background: linear-gradient(90deg, transparent, #ff4d4d, transparent);
  background-size: 34px 100%; animation: plm-bar 1s linear infinite; transition: none; }
#pl-miss .plm-timer { font: 600 10.5px ui-monospace, monospace; letter-spacing: .1em; color: #6a6a6a; }
#pl-miss [hidden] { display: none !important; }
#pl-miss .plm-row { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-top: 3px; animation: plm-in .3s ease both; }
#pl-miss .plm-btn { padding: 9px 15px; border-radius: 999px; font: 700 10.5px Montserrat, sans-serif; letter-spacing: .05em;
  cursor: pointer; background: transparent; border: 1px solid rgba(255,255,255,.22); color: #d8d8d8;
  transition: background .15s, border-color .15s, color .15s; }
#pl-miss .plm-btn:hover { background: rgba(255,255,255,.09); color: #fff; border-color: rgba(255,255,255,.42); }
#pl-miss .plm-btn.primary { background: #da0000; border-color: #da0000; color: #fff; }
#pl-miss .plm-btn.primary:hover { background: #ff1a1a; border-color: #ff1a1a; }
@media (prefers-reduced-motion: reduce) {
  #pl-miss .plm-ring { animation-duration: 2.4s; }
  #pl-miss .plm-glow { animation: none; opacity: .45; }
}
`;
    document.head.appendChild(s);
}

const miss = {
    job: null, polls: 0, began: 0, ticker: null, poll: null, busy: false,
    el: null,
};

function missClearTimers() {
    clearInterval(miss.ticker);
    clearTimeout(miss.poll);
    miss.ticker = null;
    miss.poll = null;
}

function hideMiss() {
    missClearTimers();
    miss.job = null;
    miss.polls = 0;
    miss.busy = false;
    miss.el = null;
    pel('pl-miss')?.remove();
    const big = pel('pl-bigplay');
    if (big && big.style.display === 'none') big.style.display = '';
}

// Built once and kept: rebuilding these nodes on every poll restarted the ring animation and made the
// status line look like it was being retyped, which is what made the whole state strobe.
function missRoot() {
    const shell = playerShell();
    if (!shell) return null;
    let box = pel('pl-miss');
    if (box && miss.el) return box;
    if (!box) {
        ensureMissStyles();
        box = document.createElement('div');
        box.id = 'pl-miss';
        shell.appendChild(box);
        const big = pel('pl-bigplay');
        if (big) big.style.display = 'none';
    }
    const holder = mk('div', 'plm-box');
    const glow = mk('div', 'plm-glow');
    const ring = mk('div', 'plm-ring');
    const check = mk('div', 'plm-check', '✓');
    check.hidden = true;
    holder.append(glow, ring, check);
    const kicker = mk('div', 'plm-kicker');
    const line = mk('div', 'plm-line');
    const sub = mk('div', 'plm-sub');
    const barWrap = mk('div', 'plm-bar');
    const barFill = mk('i');
    barWrap.appendChild(barFill);
    const timer = mk('div', 'plm-timer');
    const row = mk('div', 'plm-row');
    row.hidden = true;
    box.replaceChildren(holder, kicker, line, sub, barWrap, timer, row);
    miss.el = {box, holder, glow, ring, check, kicker, line, sub, barWrap, barFill, timer, row};
    return box;
}

// Writes only when the value really changed, so an unchanged poll touches nothing in the DOM.
function setIf(node, text) {
    if (node && node.textContent !== text) node.textContent = text;
}

// One call paints one state. `bar` is 0..100, or null for the indeterminate sweep, or false to hide it.
function missPaint({kicker, line, sub, bar, timer, spinner = true, done = false, buttons = []}) {
    const box = missRoot();
    if (!box) return;
    const el = miss.el;

    const spinning = spinner && !done;
    el.glow.hidden = !spinning;
    el.ring.hidden = !spinning;
    el.check.hidden = !done;

    setIf(el.kicker, kicker || '');
    el.kicker.hidden = !kicker;
    setIf(el.line, line || '');
    el.line.hidden = !line;
    setIf(el.sub, sub || '');
    el.sub.hidden = !sub;

    if (bar === false) {
        el.barWrap.hidden = true;
    } else {
        el.barWrap.hidden = false;
        const indet = bar === null;
        el.barWrap.classList.toggle('indet', indet);
        if (!indet) el.barFill.style.width = Math.max(0, Math.min(100, bar)) + '%';
    }

    if (timer === false) {
        el.timer.hidden = true;
    } else {
        el.timer.hidden = false;
        setIf(el.timer, timer || '');
    }

    // the escape hatches only exist on the failure state, so the row is only rebuilt when the set changes
    const sig = buttons.map(b => b[0]).join('|');
    if (el.row.dataset.sig !== sig) {
        el.row.dataset.sig = sig;
        el.row.replaceChildren(...buttons.map(([label, primary, fn]) => {
            const b = mk('button', 'plm-btn' + (primary ? ' primary' : ''), label);
            b.type = 'button';
            b.addEventListener('click', e => {
                e.stopPropagation();
                fn();
            });
            return b;
        }));
    }
    el.row.hidden = !buttons.length;
}

function missElapsed() {
    const s = Math.max(0, Math.floor((Date.now() - miss.began) / 1000));
    return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')} elapsed`;
}

// The fetch itself: overlay first, then a non-forced grab, then the queue is watched.
// A page load does not force: an existing row (queued, cancelled, failed, skipped) is reported as it stands,
// and only "Try again" asks grab to re-decide. Without that, every reload re-ran the whole provider sweep.
async function beginFetch(force = false) {
    if (miss.busy || !playerMovie) return;
    miss.busy = true;
    miss.polls = 0;
    miss.began = Date.now();
    missClearTimers();
    missPaint({
        kicker: 'Not in your library',
        line: force ? 'Looking again…' : 'Fetching a copy…',
        sub: 'It downloads once and stays on your drive. Nothing here can expire.',
        bar: null,
        timer: missElapsed(),
    });
    miss.ticker = setInterval(() => {
        if (miss.el) setIf(miss.el.timer, missElapsed());
    }, 1000);

    try {
        const res = await fetch(`${GRAB_API}/grab`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({tmdb: Number(playerMovie.id), force: force ? 1 : 0}),
        });
        const job = await res.json().catch(() => ({}));
        if (!res.ok) return missFailed(job.error || `The grab daemon answered ${res.status}.`);
        miss.job = job;
        if (job.id) pollFetch();
    } catch (err) {
        missFailed('The grab daemon did not answer. Is it running?');
    }
}

async function pollFetch() {
    clearTimeout(miss.poll);
    if (!playerMovie || !miss.busy) return;
    let job = null;
    try {
        // all=1: the queue hides finished rows, and a job that ends has to stay findable or the
        // end states below are never reached and this polls an empty list until it gives up
        const res = await fetch(`${GRAB_API}/queue?all=1`);
        const list = await res.json();
        job = (Array.isArray(list) ? list : [])
            .filter(j => Number(j.tmdb) === Number(playerMovie.id))
            .sort((a, b) => b.added - a.added)[0] || null;
    } catch (err) { /* grab unreachable, counted below */ }

    if (!job) {
        miss.polls++;
        if (miss.polls >= 4) return missFailed('The grab daemon did not answer. Is it running?');
        miss.poll = setTimeout(pollFetch, 2000);
        return;
    }

    miss.job = job;
    const pct = job.progress_pct || 0;

    if (job.state === 'done' || job.state === 'present') {
        miss.busy = false;
        missClearTimers();
        missPaint({kicker: 'Filed', line: 'Starting…', sub: '', bar: 100, timer: false, spinner: false, done: true});
        setTimeout(() => resolveStreams(0, 'auto'), 800);
        return;
    }
    // queued is a finished answer, not a step: nothing proved itself, so nothing will change until asked
    if (job.state === 'queued') {
        return missFailed('Every candidate was rejected. Nothing is proven for this title yet.', 'Nothing proven yet.');
    }
    // skipped is the same shape: grab answered at once and started no sweep
    if (job.state === 'skipped') {
        return missFailed('Skipped. Try again to search anyway.', 'Skipped.');
    }
    if (job.state === 'failed' || job.state === 'cancelled' || job.state === 'wrong') {
        return missFailed(job.error || (job.state === 'cancelled' ? 'Cancelled.' : 'The download failed.'));
    }

    if (job.state === 'downloading') {
        missPaint({
            kicker: 'Fetching a copy',
            line: `${pct.toFixed(0)}% of ${job.size_h || 'the file'}`,
            sub: job.speed_h ? `${job.speed_h} · ${job.title || ''}` : (job.title || ''),
            bar: pct,
            timer: missElapsed(),
        });
    } else if (job.state === 'moving') {
        missPaint({kicker: 'Filing', line: 'Moving the file into your library…', sub: job.title || '', bar: 100, timer: missElapsed()});
    } else if (job.state === 'handed_off') {
        missPaint({
            kicker: 'Fetching a copy',
            line: 'Waiting for the download to finish…',
            sub: `${job.title || ''} · ${job.size_h || ''} — it files itself the moment it lands.`,
            bar: null,
            timer: missElapsed(),
        });
    } else {
        missPaint({kicker: 'Fetching a copy', line: 'Looking for a torrent…', sub: job.title || '', bar: null, timer: missElapsed()});
    }
    miss.poll = setTimeout(pollFetch, 2000);
}

function missFailed(reason, line = 'The fetch did not work.') {
    miss.busy = false;
    missClearTimers();
    missPaint({
        kicker: 'Not in your library',
        line,
        sub: reason || 'Nothing came back.',
        bar: false,
        timer: false,
        buttons: [
            ['Try again', true, () => beginFetch(true)],
            ['Search providers', false, () => searchProviders()],
            ['Rescan library', false, rescanLibrary],
        ],
    });
}

async function rescanLibrary() {
    missPaint({kicker: 'Library', line: 'Rescanning the folder…', sub: '', bar: null, timer: false});
    try {
        await fetch(`${LIBRARY_API}/scan`, {method: 'POST'});
    } catch (err) {
        return missFailed('The library daemon is not running.');
    }
    resolveStreams(0, 'auto');
}

// Asks the relay for sources. Only when the fetch failed, or when the viewer asks for it.
async function searchProviders() {
    resolveStreams(0, 'providers');
}

// Guarded by a session id, time-limited, and keeps polling /more for slower providers.
// `preferIndex` is the slot to start on once the fresh list arrives (used when a stale list is being replaced).
async function resolveStreams(preferIndex = 0, mode = 'auto') {
    if (!playerMovie) return;
    playToken++;                        // anything still attached to the old source goes stale now
    const session = ++resolveSession;
    moreSourcesPending = false;
    waitingForMore = false;
    manualPick = false;
    resolveMode = mode;
    miss.busy = false;
    missClearTimers();

    if (mode === 'auto') {
        const local = await librarySources(playerMovie.id);
        if (session !== resolveSession) return;
        if (local.length) {
            hideMiss();
            streamSources = local;
            sourceIndex = 0;
            resolvedAt = Date.now();
            fillSourceMenu();
            playSource(0);
            return;
        }
        return beginFetch();
    }

    missPaint({kicker: 'Providers', line: 'Searching the 14 providers…', sub: '', bar: null, timer: false});
    const q = new URLSearchParams({id: playerMovie.id, tmdb: playerMovie.id, type: playerMovie.media_type || 'movie'});
    if (playerMovie.season) {
        q.set('s', playerMovie.season);
        q.set('e', playerMovie.episode);
    }

    const ctrl = new AbortController();
    resolveCtrl = ctrl;
    const cutoff = setTimeout(() => ctrl.abort(), RESOLVE_TIMEOUT_MS);
    let data = null, problem = '';
    try {
        const r = await fetch(`${STREAM_API}/resolve?${q}`, {signal: ctrl.signal});
        if (!r.ok) problem = `Resolver answered ${r.status}.`;
        else data = await r.json();
    } catch (err) {
        problem = err.name === 'AbortError' ? 'The resolver timed out.' : 'Resolver unreachable.';
        console.warn('resolve:', err.message || err);
    } finally {
        clearTimeout(cutoff);
        if (resolveCtrl === ctrl) resolveCtrl = null;
    }

    if (session !== resolveSession) return;   // a newer title was opened meanwhile

    if (!data || !Array.isArray(data.sources) || !data.sources.length) {
        return resolveFailed(problem || 'No provider answered.');
    }

    if (data.imdb) streamImdb = data.imdb;
    streamSources = data.sources;
    sourceIndex = 0;
    resolvedAt = Date.now();
    moreSourcesPending = Boolean(data.more);
    fillSourceMenu();
    playSource(Math.min(Math.max(0, preferIndex), streamSources.length - 1));

    if (moreSourcesPending) pollMoreSources(session, Number.isFinite(data.next) ? data.next : streamSources.length);
}

// Fills the menu with sources the relay produced after the first response. Append-only, keyed by URL.
async function pollMoreSources(session, since) {
    let rounds = 0;
    while (session === resolveSession && moreSourcesPending && playerMovie && rounds++ < 40) {
        try {
            const q = new URLSearchParams({id: playerMovie.id, since: String(since)});
            const r = await fetch(`${STREAM_API}/more?${q}`);
            if (!r.ok || session !== resolveSession) break;
            const data = await r.json();
            if (session !== resolveSession) break;

            const incoming = Array.isArray(data.sources) ? data.sources : [];
            let added = false;
            for (const item of incoming) {
                if (!streamSources.some(s => s.direct === item.direct || s.url === item.url)) {
                    streamSources.push(item);
                    added = true;
                }
            }
            if (added) {
                fillSourceMenu();
                if (waitingForMore && sourceIndex < streamSources.length) {
                    waitingForMore = false;
                    playSource(sourceIndex);
                } else if (!manualPick && streamSources[sourceIndex]?.meta?.cam) {
                    // a recording of a cinema screen is playing and something digital just arrived: take the digital one
                    const better = streamSources.findIndex(s => s !== streamSources[sourceIndex] && !s.meta?.cam && !s.local);
                    if (better > -1) {
                        pToast('Digital copy found — switching.');
                        playSource(better);
                    }
                }
            }
            since = Number.isFinite(data.next) ? data.next : (since + incoming.length);
            moreSourcesPending = Boolean(data.more && !data.done);
            if (!incoming.length && !moreSourcesPending) break;
        } catch (err) {
            break;
        }
    }
    moreSourcesPending = false;
    if (session === resolveSession && waitingForMore) {
        waitingForMore = false;
        playSource(sourceIndex);
    }
}

// The resolve itself produced nothing useful: try again with fresh tokens, then hand back to the overlay.
function resolveFailed(reason) {
    if (resolveMode === 'providers' && retriesUsed < MAX_RETRIES) {
        retriesUsed++;
        pToast('Retrying sources…');
        setTimeout(() => resolveStreams(0, 'providers'), 700);
        return;
    }
    missFailed(reason);
}

// One server row. CAM is spelled out because a 1080p recording of a cinema screen still looks worse than a
// 480p digital copy, and the height alone would read the wrong way round.
function sourceOptionText(s) {
    if (s.local) return `LOCAL · ${s.meta?.height ? `${s.meta.height}p · ` : ''}${s.kind === 'mp4' ? 'MP4 · ' : ''}${fmtTime(s.seconds)}`;
    const cam = s.meta?.cam ? 'CAM · ' : '';
    const res = s.meta?.height ? `${s.meta.height}p · ` : '';
    const kind = s.kind === 'mp4' ? 'MP4 · ' : '';
    return `${s.label} · ${cam}${res}${kind}${fmtTime(s.seconds)}`;
}

function fillSourceMenu() {
    const sel = pel('server-switcher');
    if (!sel) return;
    sel.replaceChildren(...streamSources.map((s, i) => {
        const o = document.createElement('option');
        o.value = String(i);
        o.textContent = sourceOptionText(s);
        return o;
    }));
    sel.value = String(Math.min(sourceIndex, Math.max(0, streamSources.length - 1)));
    // a manual pick is a fresh intent, so the retry budget starts over and auto-upgrading stops
    sel.onchange = () => {
        retriesUsed = 0;
        waitingForMore = false;
        manualPick = true;
        playSource(Number(sel.value));
    };
}

// Drops any <track> element (embedded or external) and its blob. player-ui.js owns the external ones, but
// both selectors are cleared here so a source switch never leaves a stale language rendering.
function clearExternalTrack() {
    const v = vid();
    if (v) v.querySelectorAll('track[data-ext], track[data-ruin-ext]').forEach(t => t.remove());
}

function teardownPlayer() {
    clearStall();
    const v = vid();
    // Remember where we were before the element is emptied, so a source switch resumes instead of restarting.
    if (v && v.duration && v.currentTime > 5) carryTime = v.currentTime;
    if (hls) {
        hls.destroy();
        hls = null;
    }
    clearExternalTrack();
    if (!v) return;
    v.onloadedmetadata = null;
    v.onerror = null;
    v.removeAttribute('src');
    v.load();
    v.replaceChildren();   // drops any native <track> subtitles
}

async function playSource(i) {
    if (!streamSources.length) return resolveFailed('No source answered.');
    if (i >= streamSources.length) {
        if (moreSourcesPending) {
            sourceIndex = i;
            waitingForMore = true;
            pToast('Waiting for backup sources…');
            return;
        }
        // this whole batch is exhausted: ask the relay again for fresh tokens before giving up
        if (resolveMode === 'providers' && retriesUsed < MAX_RETRIES) {
            retriesUsed++;
            pToast('Refreshing sources…');
            setTimeout(() => resolveStreams(0, 'providers'), 700);
            return;
        }
        return missFailed('Every source failed.');
    }

    // The list is older than the relay's job lifetime: its host tokens have probably expired. Get a fresh list
    // first and land on the same slot, instead of feeding the player a URL that answers 401.
    // Library URLs carry no token, so a local list never needs this.
    const nextSrc = streamSources[i];
    if (!nextSrc?.local && Date.now() - resolvedAt > SOURCE_TTL_MS && !resolveCtrl) {
        pToast('Refreshing sources…');
        resolveStreams(i, 'providers');
        return;
    }

    const token = ++playToken;          // any handler from an older attempt sees a stale token and stays quiet
    sourceIndex = i;
    waitingForMore = false;
    const src = streamSources[i];
    const sel = pel('server-switcher');
    if (sel) sel.value = String(i);

    hideMiss();
    pToast(`Trying ${src.label}…`);
    teardownPlayer();
    const fallback = pel('player-fallback');
    if (fallback && !fallback.hidden) fallback.removeAttribute('src');   // stop an old embed still playing behind us

    const v = vid();
    if (!v) return;
    v.crossOrigin = 'anonymous';
    useVideoMode();          // undo anything a leftover embed left on screen

    // The saved position is restored once per visit; after a source switch the carried position wins instead.
    v.onloadedmetadata = () => {
        if (token !== playToken) return;
        clearStall();
        if (!progressRestored) {
            progressRestored = true;
            restoreProgress();
        } else if (carryTime > 5) {
            try {
                v.currentTime = carryTime;
            } catch (e) { /* seek before the buffer exists */
            }
        }
        carryTime = 0;
        pToast('');
    };
    v.onerror = () => {
        if (token !== playToken) return;
        failSource(token, i + 1);
    };

    armStall(token);

    // A progressive MP4 (the library's browser-safe files, and vidlink) is not an HLS playlist:
    // hls.js would fail to parse it, so feed the element directly.
    if (src.kind === 'mp4') {
        addNativeSubs(src.subtitles);
        if (typeof buildSubtitleMenu === 'function') buildSubtitleMenu();
        v.src = src.url;
        v.play().catch(() => {
        });
        return;
    }

    // hls.js first, always. Chrome answers canPlayType() with "maybe", so the native branch would win by mistake
    // and never build a player. Native is only used where hls.js genuinely cannot run (iOS Safari).
    if (typeof Hls === 'undefined' || !Hls.isSupported()) {
        addNativeSubs(src.subtitles);
        if (typeof buildSubtitleMenu === 'function') buildSubtitleMenu();
        v.src = src.url;
        v.play().catch(() => {
        });
        return;
    }

    hls = new Hls({enableWorker: false, maxBufferLength: 40, backBufferLength: 90});

    hls.on(Hls.Events.LEVEL_SWITCHED, () => {
        if (token !== playToken) return;
        updateQualityUI();
    });

    hls.on(Hls.Events.MANIFEST_PARSED, () => {
        if (token !== playToken) return;
        clearStall();
        buildQualityMenu();
        // player-ui.js replaces buildSubtitleMenu; this call fills its menu from the new stream's tracks.
        if (typeof buildSubtitleMenu === 'function') buildSubtitleMenu();
        const top = hls.levels.reduce((best, l, idx) => levelHeight(l) > levelHeight(hls.levels[best]) ? idx : best, 0);
        if (top > 0) hls.currentLevel = top;
        v.play().catch(() => {
        });
    });

    hls.on(Hls.Events.SUBTITLE_TRACKS_UPDATED, () => {
        if (token !== playToken) return;
        if (typeof buildSubtitleMenu === 'function') buildSubtitleMenu();
    });

    hls.on(Hls.Events.ERROR, (_, d) => {
        if (token !== playToken) return;
        if (!d.fatal) {
            // a stall the browser cannot get out of on its own: nudge the loader once
            if (d.details === 'bufferStalledError' && hls) hls.startLoad();
            return;
        }
        console.warn('hls fatal:', d.details);
        failSource(token, i + 1);
    });

    hls.attachMedia(v);      // attach before loadSource, otherwise the media element is missing on the first segment
    hls.loadSource(src.url);
}

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
    if (!hls || !indices.length) {
        if (btn) btn.hidden = true;
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

// Fallback for the native (iOS) path, which has no hls.js track list. player-ui.js handles the main menu.
// `list` entries arrive already pointed at the library's or the relay's subtitle endpoint, which hands back WebVTT.
function addNativeSubs(list) {
    const v = vid();
    if (!v) return;
    (list || []).forEach((s, i) => {
        const t = document.createElement('track');
        t.kind = 'subtitles';
        t.label = s.label || `Subtitle ${i + 1}`;
        t.srclang = s.lang || 'en';
        t.dataset.ruinExt = '1';
        t.src = s.url;
        v.appendChild(t);
    });
}

// The film played to its end: same as passing the 95% mark in saveProgress().
// (media events do not bubble, so this listens in the capture phase on the document)
document.addEventListener('ended', e => {
    if (PAGE !== 'watch' || !playerMovie || e.target !== vid()) return;
    clearTimeout(saveTimer);
    clearProgress(playerMovie.id);
    lastSaved = 0;
}, true);

// player-ui.js replaces bindPlayerControls() and does not start the save loop, so the loop is started HERE, from the video's
// own events (media events do not bubble, so this listens in the capture phase on the document). Without it the position was
// only saved when you seeked. Saves: every 10 s while playing, on pause, when the tab is hidden and when the page closes.
document.addEventListener('playing', e => {
    if (PAGE === 'watch' && e.target === vid()) startSaveLoop();
}, true);
document.addEventListener('pause', e => {
    if (PAGE !== 'watch' || e.target !== vid()) return;
    clearInterval(saveTimer);
    saveProgress();
}, true);
// While a page is closing, a normal request is usually cancelled before it leaves. A "keepalive" request is allowed to finish
// after the page is gone, so leaving right after a seek (or in the middle of the last minutes) still saves the exact spot.
function saveProgressOnExit() {
    if (PAGE !== 'watch' || !currentUser || !playerMovie || !authToken) return;
    const v = vid();
    if (!v || !Number.isFinite(v.duration) || v.currentTime < 5 || v.ended || isFinished(v.currentTime, v.duration)) return;
    if (Math.abs(v.currentTime - lastSaved) < 2) return;
    lastSaved = v.currentTime;
    fetch(`${SUPABASE_URL}/rest/v1/watch_progress?on_conflict=user_id,movie_id`, {
        method: 'POST',
        keepalive: true,
        headers: {
            apikey: SUPABASE_KEY,
            Authorization: `Bearer ${authToken}`,
            'Content-Type': 'application/json',
            Prefer: 'resolution=merge-duplicates,return=minimal',
        },
        body: JSON.stringify({
            user_id: currentUser.id,
            movie_id: playerMovie.id,
            seconds: Math.floor(v.currentTime),
            duration: Math.floor(v.duration),
            updated_at: new Date().toISOString(),
        }),
    }).catch(() => {});
}
window.addEventListener('pagehide', saveProgressOnExit);
document.addEventListener('visibilitychange', () => {
    if (PAGE === 'watch' && document.hidden) saveProgress();
});

async function restoreProgress() {
    if (!currentUser || !playerMovie) return;
    const {data} = await supabaseClient
        .from('watch_progress')
        .select('seconds,duration')
        .eq('user_id', currentUser.id)
        .eq('movie_id', playerMovie.id)
        .maybeSingle();

    if (!data || !data.seconds) return;
    
    const v = vid();
    if (!v) return;
    v.currentTime = data.seconds;
    pToast(`Resumed at ${fmtTime(data.seconds)}`);
}

function startSaveLoop() {
    clearInterval(saveTimer);
    saveTimer = setInterval(saveProgress, 10000);
}

async function saveProgress() {
    if (!currentUser || !playerMovie) return;
    const v = vid();
    if (!v || !v.duration || v.currentTime < 5) return;
    if (isFinished(v.currentTime, v.duration)) {            // finished: there is nothing to continue, so the saved position is deleted
        if (lastSaved || progressMap.has(playerMovie.id)) await clearProgress(playerMovie.id);
        lastSaved = 0;
        return;
    }
    if (Math.abs(v.currentTime - lastSaved) < 5) return;
    lastSaved = v.currentTime;

    const {error} = await supabaseClient.from('watch_progress').upsert({
        user_id: currentUser.id,
        movie_id: playerMovie.id,
        seconds: Math.floor(v.currentTime),
        duration: Number.isFinite(v.duration) ? Math.floor(v.duration) : null,
        updated_at: new Date().toISOString(),
    }, {onConflict: 'user_id,movie_id'});
    if (error) {
        lastSaved = 0;                                   // try again on the next tick instead of believing it was saved
        console.warn('watch_progress: could not save your position:', error.message || error,
            '- if this says "row-level security", the table is missing its policies (run watch_progress_delete.sql)');
    }
}

// The basic wiring. player-ui.js replaces this with the full control bar once it has loaded, and that version is
// what initPlayer ends up calling, because a later global assignment beats this declaration.
function bindPlayerControls() {
    const v = vid(), box = playerShell();
    if (!v || !box) return;
    const playBtn = pel('pl-play');

    const on = (id, fn) => {
        const el = pel(id);
        if (el) el.onclick = fn;
    };

    on('pl-play', togglePlay);
    on('pl-bigplay', togglePlay);
    on('pl-back10', () => {
        v.currentTime = Math.max(0, v.currentTime - 10);
    });
    on('pl-fwd10', () => {
        v.currentTime = Math.min(v.duration || 0, v.currentTime + 10);
    });

    on('pl-pip', () => {
        if (!document.pictureInPictureEnabled) return pToast('Picture-in-picture is not available here.');
        if (document.pictureInPictureElement) document.exitPictureInPicture();
        else v.requestPictureInPicture().catch(() => {
        });
    });

    on('pl-full', () => {
        if (document.fullscreenElement) document.exitFullscreen();
        else box.requestFullscreen().catch(() => {
        });
    });

    const vol = pel('pl-volume');
    if (vol) {
        v.volume = 1;
        vol.oninput = () => {
            v.volume = Number(vol.value);
            v.muted = v.volume === 0;
        };
    }

    const seek = pel('pl-seek');
    if (seek) {
        seek.oninput = () => {
            if (v.duration) v.currentTime = (Number(seek.value) / 1000) * v.duration;
        };
    }

    v.onplay = () => {
        clearStall();
        if (playBtn) playBtn.textContent = '❚❚';
        box.classList.add('playing');
        startSaveLoop();
        wakePlayer();
    };
    v.onpause = () => {
        if (playBtn) playBtn.textContent = '▶';
        box.classList.remove('playing');
        clearInterval(saveTimer);
        saveProgress();
    };

    v.ontimeupdate = () => {
        const d = v.duration || 0;
        const played = d ? (v.currentTime / d) * 100 : 0;
        const buffered = d && v.buffered.length ? (v.buffered.end(v.buffered.length - 1) / d) * 100 : 0;
        if (seek) {
            seek.value = d ? Math.round((v.currentTime / d) * 1000) : 0;
            seek.style.setProperty('--p', played + '%');
            seek.style.setProperty('--b', Math.max(played, buffered) + '%');
        }
        const timeEl = pel('pl-time');
        if (timeEl) timeEl.textContent = `${fmtTime(v.currentTime)} / ${fmtTime(d)}`;
    };

    v.onclick = togglePlay;
    box.onmousemove = wakePlayer;
    box.onmouseleave = () => box.classList.add('idle');

    document.addEventListener('keydown', playerKeys);
    document.addEventListener('click', hidePlayerMenus);
    window.addEventListener('beforeunload', saveProgress);
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) saveProgress();
    });
}

function togglePlayerMenu(id) {
    const m = pel(id);
    if (!m) return;
    const open = !m.hidden;
    hidePlayerMenus();
    m.hidden = open;
}

function hidePlayerMenus() {
    ['pl-quality', 'pl-subs'].forEach(id => {
        const m = pel(id);
        if (m) m.hidden = true;
    });
}

function playerKeys(e) {
    if (/^(input|textarea|select)$/i.test(document.activeElement?.tagName)) return;
    const v = vid();
    if (!v) return;

    switch (e.key) {
        case ' ':
        case 'k':
            e.preventDefault();
            togglePlay();
            break;
        case 'ArrowLeft':
            e.preventDefault();
            v.currentTime = Math.max(0, v.currentTime - 10);
            break;
        case 'ArrowRight':
            e.preventDefault();
            v.currentTime = Math.min(v.duration || 0, v.currentTime + 10);
            break;
        case 'ArrowUp': {
            e.preventDefault();
            v.volume = Math.min(1, v.volume + 0.1);
            const vol = pel('pl-volume');
            if (vol) vol.value = v.volume;
            break;
        }
        case 'ArrowDown': {
            e.preventDefault();
            v.volume = Math.max(0, v.volume - 0.1);
            const vol = pel('pl-volume');
            if (vol) vol.value = v.volume;
            break;
        }
        case 'm':
            v.muted = !v.muted;
            break;
        case 'f':
            pel('pl-full')?.click();
            break;
    }
}

function togglePlay() {
    const v = vid();
    if (!v) return;
    v.paused ? v.play().catch(() => {
    }) : v.pause();
}

function wakePlayer() {
    const box = playerShell();
    if (!box) return;
    box.classList.remove('idle');
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => box.classList.add('idle'), 2600);
}

// A real source is on screen: undo everything a leftover embed could have left behind. The embed element
// stays in watch.html unused, so this is only a tidy-up, never a switch.
function useVideoMode() {
    const v = vid(), box = playerShell(), f = pel('player-fallback');
    if (v) v.style.display = '';
    const big = pel('pl-bigplay');
    if (big) big.style.display = '';
    box?.classList.remove('embed');
    if (f) f.hidden = true;
    pel('embed-next')?.remove();
}

// Kept for the pages that still ship the iframe element: hides the <video> and lets player-ui.js follow the class.
function embedMode() {
    const v = vid(), box = playerShell();
    if (v) v.style.display = 'none';
    const big = pel('pl-bigplay');
    if (big) big.style.display = 'none';
    box?.classList.add('embed');
    hidePlayerMenus();
    clearTimeout(hideTimer);
    box?.classList.remove('idle');
}

// Hooks for player-ui.js: quality, sources, progress and the resolve chain, without reaching into private names.
window.ruinPlayer = {
    getSources: () => streamSources,
    getSourceIndex: () => sourceIndex,
    playSource,
    resolveStreams,
    searchProviders,
    rescanLibrary,
    beginFetch,
    getHls: () => hls,
    getMovie: () => playerMovie,
    getImdb: () => streamImdb,
    getOffsetSec: () => 0
};

// --- THE WATCH PAGE (watch.html?id=603) ---
// "Back" returns to the page you came from (with its filters, because they live in that page's address).
// If you opened the link fresh (a bookmark, a message), there is nothing to go back to, so it goes home.
function goBack(event) {
    event.preventDefault();
    let sameSite = false;
    try {
        sameSite = !!document.referrer && new URL(document.referrer).origin === location.origin;
    } catch (e) { /* no referrer */
    }
    if (sameSite && history.length > 1) history.back(); else location.href = pageUrl('');
}

// Watching is recorded once, and only when we know both the movie and who is logged in (guests are never recorded).
let watchRecorded = false;

function recordWatchOnce() {
    if (watchRecorded || !currentMovie || !authReady) return;
    watchRecorded = true;
    addToHistory(currentMovie);
}

function watchFail(text) {
    const view = document.getElementById('watch-view');
    if (!view) return;
    const back = mk('a', 'hero-btn', 'Back to home');
    back.href = pageUrl('');
    view.replaceChildren(mk('p', 'empty-note', text), back);
    document.title = 'Not found | RUIN.TO';
}

async function initWatch() {
    const idText = new URLSearchParams(location.search).get('id') || '';
    if (!/^\d{1,9}$/.test(idText)) return watchFail('That link does not point to a movie.');
    const id = Number(idText);
    if (isBlocked({id})) return watchFail('This title is no longer available.');
    SK.fill('similar-row', 8);

    let d;
    try {
        d = await getDetails(id);
    } catch (err) {
        console.error(err);
        return watchFail('The void could not find that movie, or could not be reached. Try again in a moment.');
    }

    currentMovie = slimMovie({...d, id, media_type: 'movie'});
    const title = d.title || d.name || 'Movie';
    const year = yearOf(currentMovie);
    document.title = `${title}${year ? ` (${year})` : ''} | RUIN.TO`;
    document.querySelector('.watch-frame')?.classList.remove('sk');
    initPlayer({...currentMovie, runtime: d.runtime || 0, imdb_id: d.imdb_id || null});
    refreshSavedUI();
    recordWatchOnce();

    // blurred backdrop behind the whole page
    if (d.backdrop_path) document.getElementById('watch-backdrop').style.backgroundImage = `url(https://image.tmdb.org/t/p/w1280${d.backdrop_path})`;

    // poster + text + facts
    const facts = [year, d.runtime ? `${d.runtime} min` : '', d.production_countries?.[0]?.name, d.vote_average ? `★ ${d.vote_average.toFixed(1)}` : ''].filter(Boolean).join('  •  ');
    const info = document.getElementById('watch-info');
    const body = mk('div', 'watch-body');
    body.append(mk('h1', 'watch-title', title), mk('p', 'details-facts', facts));
    if (d.tagline) body.append(mk('p', 'watch-tagline', `“${d.tagline}”`));
    const chips = mk('div', 'hero-genres');
    chips.replaceChildren(...(d.genres || []).slice(0, 5).map(g => mk('span', 'chip', g.name)));
    const kBits = kindBits(id) || 0;
    decorateChips(chips, kBits);
    document.body.dataset.kind = kindLabel(kBits).toLowerCase() || 'movie';
    window.ruinKind = {tmdb: id, ai: !!(kBits & KIND_AI), youtube: !!(kBits & KIND_YT), short: !!(kBits & KIND_SHORT), homepage: d.homepage || ''};   // hook for your own YouTube fetching
    document.dispatchEvent(new CustomEvent('ruin:kind', {detail: window.ruinKind}));
    body.append(chips, mk('p', 'details-overview', d.overview || 'No description yet.'));
    const director = (d.credits?.crew || []).filter(m => m.job === 'Director').slice(0, 2).map(m => m.name).join(', ');
    const grid = mk('div', 'watch-facts');
    const fact = (label, value) => {
        if (value) grid.append(mk('span', 'wf-label', label), mk('span', 'wf-value', value));
    };
    fact('Director', director);
    fact('Released', d.release_date ? prettyDate(d.release_date) : '');
    fact('Runtime', d.runtime ? `${d.runtime} min` : '');
    fact('Language', d.spoken_languages?.[0]?.english_name);
    fact('Country', (d.production_countries || []).slice(0, 2).map(x => x.name).join(', '));
    fact('Studio', d.production_companies?.[0]?.name);
    fact('Rating', d.vote_average ? `★ ${d.vote_average.toFixed(1)} (${fmtCount(d.vote_count || 0)} votes)` : '');
    const kids = [];
    if (d.poster_path) {
        const img = mk('img', 'watch-poster');
        img.src = 'https://image.tmdb.org/t/p/w500' + d.poster_path;
        img.alt = title;
        kids.push(img);
    }
    info.classList.toggle('no-poster', !kids.length);
    info.replaceChildren(...kids, body, ...(grid.children.length ? [grid] : []));

    // cast
    const cast = (d.credits?.cast || []).slice(0, 14);
    if (cast.length) {
        document.getElementById('watch-cast').replaceChildren(...cast.map(c => {
            const card = mk('a', 'cast-card');
            card.href = personUrl(c.id);
            const photo = mk('div', 'cast-photo');
            if (c.profile_path) {
                const img = mk('img');
                img.src = 'https://image.tmdb.org/t/p/w185' + c.profile_path;
                img.alt = '';
                img.loading = 'lazy';
                photo.appendChild(img);
            } else photo.textContent = (c.name || '?').charAt(0);
            card.append(photo, mk('b', '', c.name), mk('span', '', c.character || ''));
            return card;
        }));
        document.getElementById('watch-cast-box').hidden = false;
    }

    // more like this: TMDB's recommendations first, then "similar" to fill the row
    try {
        const base = `https://api.themoviedb.org/3/movie/${id}`;
        let list = (await tmdb(`${base}/recommendations?api_key=${API_KEY}`)).results;
        if (list.length < 10) list = list.concat((await tmdb(`${base}/similar?api_key=${API_KEY}`)).results);
        const seen = new Set([id]);
        list = list.filter(m => m.poster_path && !isBlocked(m) && !seen.has(m.id) && seen.add(m.id)).slice(0, 16);
        if (list.length) renderRow(list.map(m => ({...m, media_type: 'movie'})), 'similar-row');
        else document.getElementById('watch-similar-box').hidden = true;
    } catch (err) {
        console.error(err);
        rowMessage('similar-row', 'The void refused to answer.');
    }
}


// --- THE PERSON PAGE (person.html?id=1189) ---
// One TMDB request: the person, with their movie credits attached (append_to_response saves a second round trip).
function ageFrom(birth, death) {
    const b = new Date(birth), e = death ? new Date(death) : new Date();
    if (isNaN(b)) return null;
    let age = e.getFullYear() - b.getFullYear();
    if (e.getMonth() < b.getMonth() || (e.getMonth() === b.getMonth() && e.getDate() < b.getDate())) age--;
    return age;
}

const prettyDate = iso => {
    const d = new Date(iso + 'T00:00:00');
    return isNaN(d) ? '' : d.toLocaleDateString('en-GB', {day: '2-digit', month: 'short', year: 'numeric'});
};

function personFail(text) {
    const view = document.getElementById('person-view');
    if (!view) return;
    const back = mk('a', 'hero-btn', 'Back to home');
    back.href = pageUrl('');
    view.replaceChildren(mk('p', 'empty-note', text), back);
    document.title = 'Not found | RUIN.TO';
}

// A list of credits (Acting / Directing / Writing): newest first, one row per movie, each row opens that movie.
function creditsSection(title, items, noteOf) {
    const seen = new Set();
    const rows = items.filter(m => m.id && (m.title || m.original_title) && !isBlocked(m) && !seen.has(m.id) && seen.add(m.id))
        .sort((a, b) => (b.release_date || '0000').localeCompare(a.release_date || '0000'));
    if (!rows.length) return null;
    const box = mk('section', 'credits-box');
    box.append(mk('h2', 'section-title', `${title} (${rows.length})`));
    const list = mk('div', 'credits-list');
    for (const m of rows) {
        const a = mk('a', 'credit-row');
        a.href = watchUrl(m.id);
        a.append(mk('span', 'credit-year', (m.release_date || '').slice(0, 4) || '—'), mk('b', 'credit-title', m.title || m.original_title), mk('span', 'credit-note', noteOf(m) || ''));
        list.appendChild(a);
    }
    box.appendChild(list);
    return box;
}

async function initPerson() {
    const idText = new URLSearchParams(location.search).get('id') || '';
    if (!/^\d{1,9}$/.test(idText)) return personFail('That link does not point to a person.');
    let p;
    try {
        p = await tmdb(`https://api.themoviedb.org/3/person/${idText}?api_key=${API_KEY}&append_to_response=movie_credits`);
    } catch (err) {
        console.error(err);
        return personFail('The void could not find that person, or could not be reached. Try again in a moment.');
    }

    document.title = `${p.name} | RUIN.TO`;
    const cast = p.movie_credits?.cast || [], crew = p.movie_credits?.crew || [];
    const directed = crew.filter(m => m.job === 'Director'),
        wrote = crew.filter(m => ['Writer', 'Screenplay', 'Story'].includes(m.job));
    const all = new Set([...cast, ...directed, ...wrote].filter(m => m.id && !isBlocked(m)).map(m => m.id));

    // left column: photo + facts
    const side = mk('aside', 'person-side');
    const photo = mk('div', 'person-photo');
    if (p.profile_path) {
        const img = mk('img');
        img.src = 'https://image.tmdb.org/t/p/h632' + p.profile_path;
        img.alt = p.name;
        photo.appendChild(img);
    } else photo.textContent = (p.name || '?').charAt(0);
    const gender = {1: 'Female', 2: 'Male', 3: 'Non-binary'}[p.gender] || '';
    const age = p.birthday ? ageFrom(p.birthday, p.deathday) : null;
    const facts = mk('div', 'person-facts');
    const fact = (label, value) => {
        if (value) facts.append(mk('div', 'pf-label', label), mk('div', 'pf-value', value));
    };
    fact('Known for', p.known_for_department);
    fact('Gender', gender);
    fact('Birthday', p.birthday ? `${prettyDate(p.birthday)}${p.deathday ? '' : age !== null ? ` (${age} years old)` : ''}` : '');
    fact('Died', p.deathday ? `${prettyDate(p.deathday)}${age !== null ? ` (aged ${age})` : ''}` : '');
    fact('Place of birth', p.place_of_birth);
    fact('Movies', all.size ? String(all.size) : '');
    side.append(photo, mk('h3', 'pf-heading', 'Overview'), facts);

    // right column: name, biography (cut short, "Show more" opens it), the six best-known films
    const main = mk('div', 'person-main');
    main.append(mk('h1', 'watch-title', p.name));
    main.append(mk('h2', 'section-title', 'BIOGRAPHY'));
    const bio = mk('p', 'person-bio clamped', (p.biography || '').trim() || 'No biography yet.');
    main.append(bio);
    if ((p.biography || '').length > 450) {
        const more = mk('button', 'person-more', 'Show more');
        more.type = 'button';
        more.onclick = () => {
            const open = bio.classList.toggle('clamped');
            more.textContent = open ? 'Show more' : 'Show less';
        };
        main.append(more);
    }
    const known = [...cast].filter(m => m.poster_path && !isBlocked(m)).sort((a, b) => (b.popularity || 0) - (a.popularity || 0)).slice(0, 12);
    if (known.length) {
        main.append(mk('h2', 'section-title', 'KNOWN FOR'));
        const row = mk('div', 'movie-row');
        row.id = 'known-row';
        main.append(row);
    }
    const layout = mk('div', 'person-layout');
    layout.append(side, main);
    document.querySelector('.person-layout')?.replaceWith(layout);      // swap the ghost version for the real one (the Back link stays)
    if (known.length) renderRow(known.map(m => ({...m, media_type: 'movie'})), 'known-row');

    const view = document.getElementById('person-view');
    if (!view) return;
    const sections = [
        creditsSection('ACTING', cast, m => m.character),
        creditsSection('DIRECTING', directed, () => 'Director'),
        creditsSection('WRITING', wrote, m => m.job),
    ].filter(Boolean);
    view.append(...sections);
    if (!sections.length) view.append(mk('p', 'empty-note', 'No movies are listed for this person yet.'));
}

// --- SHARED UI HELPERS ---
// These are declared above boot() because const/let sit in the temporal dead zone until their line runs,
// and boot() -> buildPage() -> T.hero() reads SK immediately.
// Default profile picture: a dark circle with the person's first letter in blood red, drawn as a tiny SVG.
// Nothing is stored or downloaded, so it can never break like a hosted image link does.
function initialAvatar(name) {
    const letter = ([...String(name || '').trim()].find(ch => /[\p{L}\p{N}]/u.test(ch)) || 'R').toUpperCase();
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120"><defs><radialGradient id="g" cx="50%" cy="35%" r="75%"><stop offset="0" stop-color="#2a0707"/><stop offset="1" stop-color="#0a0a0a"/></radialGradient></defs><rect width="120" height="120" fill="url(#g)"/><text x="60" y="60" text-anchor="middle" dominant-baseline="central" font-family="Georgia,'Times New Roman',serif" font-weight="700" font-size="64" fill="#da0000">${letter.replace(/[<>&]/g, '')}</text></svg>`;
    return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
}

// If a saved picture link ever fails to load, fall back to the letter instead of showing broken-image text.
function avatarFallback(img) {
    img.onerror = null;
    img.src = initialAvatar(document.getElementById('dash-display-name')?.textContent || '');
}

// Loading placeholders ("skeletons"). Each one is a ghost card that shimmers until the real cards replace it.
// aria-hidden keeps screen readers from announcing empty boxes.
const SK = {
    card: () => '<div class="movie-card sk-card" aria-hidden="true"><div class="sk-poster sk"></div><div class="sk-line sk"></div></div>',
    // put n ghost cards into the element with this id (a poster row or a grid)
    fill(id, n) {
        const el = document.getElementById(id);
        if (el) el.innerHTML = SK.card().repeat(n);
    },
    hero: () => `<div id="hero-skeleton" class="hero-showcase hero-skel sk" aria-hidden="true"><div class="hero-skel-content"><span class="sk b1"></span><span class="sk b2"></span><span class="sk b3"></span><span class="sk b4"></span><span class="sk b5"></span></div></div>`
};

// Removes the hero ghost. Called when the real hero appears AND whenever the hero is given up on, so it can never get stuck.
function endHeroSkeleton() {
    document.getElementById('hero-skeleton')?.remove();
}

// --- BUILD THE PAGE ---
// The page file only contains <div id="app">. We fill it with the pieces this page needs (see components.js).
function buildPage() {
    let html = T.header();
    if (PAGE === 'category') html += T.toolbar();
    html += '<main class="content">';
    if (PAGE === 'home' || PAGE === 'category') html += T.hero();
    if (PAGE === 'home' || PAGE === 'category') html += T.modal();   // movie details + saga lists
    if (PAGE === 'home') html += T.home();
    else if (PAGE === 'category') html += T.grid(false);   // the title is inside the toolbar
    else if (PAGE === 'search') html += T.grid(true);
    else if (PAGE === 'dashboard') html += T.dashboard(document.body.dataset.tab);
    else if (PAGE === 'watch') html += T.watch();
    else if (PAGE === 'series') html += T.series();
    else if (PAGE === 'person') html += T.person();
    else if (PAGE === 'login' || PAGE === 'register') html += T.auth(PAGE);
    else if (PAGE === 'legal') html += T.legal(document.body.dataset.doc);
    html += '</main>';
    if (PAGE !== 'login' && PAGE !== 'register') html += T.footer();
    if (PAGE !== 'login' && PAGE !== 'register') {
        html += T.tabbar();
        html += T.toTop();
        document.body.classList.add('has-tabbar');
    }
    return html;
}

const PAGE_TITLES = {
    home: 'RUIN.TO | The Abyss',
    search: 'Search | RUIN.TO',
    login: 'Sign in | RUIN.TO',
    register: 'Create an Account | RUIN.TO'
};

// --- PHONE / TABLET NAVIGATION ---
function setupMobileNav() {
    // highlight the tab for the page we are on
    const current = {home: 'home', dashboard: 'profile', search: 'search'}[PAGE];
    if (current) document.querySelector(`.tab[data-tab="${current}"]`)?.classList.add('active');

    // the profile menu opens on hover with a mouse; on touch screens there is no hover, so a tap toggles it too
    const profile = document.getElementById('user-profile');
    if (profile) profile.addEventListener('click', e => {
        if (!e.target.closest('.profile-menu a')) profile.classList.toggle('open');
    });
    window.addEventListener('click', e => {
        if (!e.target.closest('#user-profile')) profile?.classList.remove('open');
    });

    // press "/" anywhere (like GitHub, YouTube) to jump to the search box, unless you are already typing somewhere
    document.addEventListener('keydown', e => {
        if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return;
        if (/^(input|textarea|select)$/i.test(document.activeElement?.tagName) || document.activeElement?.isContentEditable) return;
        const box = document.getElementById('search-input');
        if (box && box.offsetParent !== null) {
            e.preventDefault();
            box.focus();
            box.select();
        }
    });
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') {
            toggleGenreSheet(false);
            document.body.classList.remove('search-open');
        }
    });
}

function toggleGenreSheet(force) {
    const sheet = document.getElementById('genre-sheet');
    if (!sheet) return;
    const show = typeof force === 'boolean' ? force : sheet.style.display === 'none';
    sheet.style.display = show ? 'flex' : 'none';
    document.body.style.overflow = show ? 'hidden' : '';
    document.querySelector('.tab[data-tab="genres"]')?.classList.toggle('active', show);
}

// On a phone the search box is hidden to save room; the Search tab slides it open under the header.
function toggleMobileSearch() {
    toggleGenreSheet(false);
    const open = document.body.classList.toggle('search-open');
    document.querySelector('.tab[data-tab="search"]')?.classList.toggle('active', open || PAGE === 'search');
    if (open) document.getElementById('search-input')?.focus();
}

// --- INSTALLABLE APP (PWA) ---
let installPrompt = null;

function registerServiceWorker() {
    // Needs a secure address (https, or localhost while testing). sw.js only makes the site installable and
    // supplies the offline page; it never caches pages or scripts, so updates always arrive immediately.
    if ('serviceWorker' in navigator && window.isSecureContext) {
        navigator.serviceWorker.register('sw.js').catch(err => console.warn('service worker:', err.message));
    }
    const link = document.getElementById('install-link');
    const standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone;
    if (!link || standalone) return;
    window.addEventListener('beforeinstallprompt', e => {
        e.preventDefault();
        installPrompt = e;
        link.hidden = false;
    });
    window.addEventListener('appinstalled', () => {
        installPrompt = null;
        link.hidden = true;
    });
    // iPhones and iPads cannot be prompted; they only install through Safari's Share menu, so show the link with instructions
    if (/iphone|ipad|ipod/i.test(navigator.userAgent)) link.hidden = false;
}

async function installApp() {
    if (installPrompt) {
        installPrompt.prompt();
        await installPrompt.userChoice.catch(() => {
        });
        installPrompt = null;
        document.getElementById('install-link').hidden = true;
    } else {
        showToast('To install: tap the Share button, then "Add to Home Screen".');
    }
}

function initParticles() {
    // If the particles CDN is blocked, the rest of the site must still work.
    if (!window.particlesJS || isLite) return;
    const cfg = {
        "particles": {
            "number": {"value": 120, "density": {"enable": true, "value_area": 800}},
            "color": {"value": ["#da0000", "#ff4500", "#555555"]},
            "shape": {"type": "circle"},
            "opacity": {
                "value": 0.8,
                "random": true,
                "anim": {"enable": true, "speed": 1, "opacity_min": 0.1, "sync": false}
            },
            "size": {"value": 4, "random": true, "anim": {"enable": true, "speed": 2, "size_min": 0.1, "sync": false}},
            "line_linked": {"enable": false},
            "move": {
                "enable": true,
                "speed": 1.5,
                "direction": "top",
                "random": true,
                "straight": false,
                "out_mode": "out",
                "bounce": false
            }
        },
        "interactivity": {
            "detect_on": "canvas",
            "events": {
                "onhover": {"enable": true, "mode": "repulse"},
                "onclick": {"enable": true, "mode": "push"},
                "resize": true
            },
            "modes": {"repulse": {"distance": 100, "duration": 0.4}, "push": {"particles_nb": 4}}
        },
        "retina_detect": true
    };
    // phones: far fewer particles, no retina doubling, so scrolling stays smooth and the battery lasts
    if (window.matchMedia('(max-width: 700px)').matches) {
        cfg.particles.number.value = 30;
        cfg.retina_detect = false;
    }
    particlesJS("particles-js", cfg);
}

// Small visual touches that need a little script: the header changes once you scroll, and poster cards tilt towards the mouse
// and carry a soft light that follows it. Pure decoration: if anything here fails the site works exactly the same.
// A thin red progress line at the very top: starts when you open a page or click an internal link, finishes when the page
// has loaded. It only moves with transform (cheap) and gives instant feedback that "something is happening".
function setupRouteBar() {
    if (isLite) return;
    const bar = document.createElement('div');
    bar.id = 'route-bar';
    bar.setAttribute('aria-hidden', 'true');
    const fill = document.createElement('i');
    bar.appendChild(fill);
    document.body.appendChild(bar);
    let p = 0, tick = 0, safety = 0;
    const set = v => {
        p = v;
        fill.style.transform = `scaleX(${v})`;
    };
    const start = () => {
        clearInterval(tick);
        clearTimeout(safety);
        bar.classList.add('on');
        set(0.1);
        tick = setInterval(() => set(p + (0.92 - p) * 0.1), 220);
        safety = setTimeout(done, 9000);             // never leave it hanging if a page stalls
    };
    const done = () => {
        clearInterval(tick);
        clearTimeout(safety);
        set(1);
        setTimeout(() => {
            bar.classList.remove('on');
            set(0);
        }, 380);
    };
    if (document.readyState !== 'complete') {
        start();
        window.addEventListener('load', done, {once: true});
    }
    window.addEventListener('pageshow', e => {
        if (e.persisted) done();                       // back button restored the page from memory
    });
    document.addEventListener('click', e => {
        const a = e.target.closest && e.target.closest('a[href]');
        if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        if ((a.target && a.target !== '_self') || a.hasAttribute('download')) return;
        let u;
        try {
            u = new URL(a.href, location.href);
        } catch (err) {
            return;
        }
        if (u.origin !== location.origin || u.hash && u.pathname === location.pathname) return;
        if (u.pathname === location.pathname && u.search === location.search) return;
        start();
    });
}

// Pictures fade in when they arrive instead of popping. Only an image that is NOT already loaded gets the fade, and a
// timer always removes it, so a picture can never be left invisible.
function setupImageFade() {
    if (isLite || !window.MutationObserver) return;
    const settle = img => {
        img.classList.remove('img-wait');
        img.classList.add('img-in');
    };
    const wait = img => {
        if (img.complete || img.dataset.fade || img.closest('.watch-frame, .top-bar')) return;
        img.dataset.fade = '1';
        img.classList.add('img-wait');
        img.addEventListener('load', () => settle(img), {once: true});
        img.addEventListener('error', () => img.classList.remove('img-wait'), {once: true});
        setTimeout(() => img.classList.remove('img-wait'), 5000);
    };
    new MutationObserver(list => list.forEach(m => m.addedNodes.forEach(n => {
        if (n.nodeType !== 1) return;
        if (n.tagName === 'IMG') wait(n);
        else if (n.querySelectorAll) n.querySelectorAll('img').forEach(wait);
    }))).observe(document.body, {childList: true, subtree: true});
}

function setupPolish() {
    const onScroll = () => document.body.classList.toggle('scrolled', window.scrollY > 24);
    window.addEventListener('scroll', onScroll, {passive: true});
    onScroll();
    if (reducedMotion() || !window.matchMedia('(hover: hover)').matches) return;   // phones and TVs: no tilt
    let frame = 0, card = null, ev = null;
    const paint = () => {
        frame = 0;
        if (!card || !ev) return;
        const r = card.getBoundingClientRect();
        const x = (ev.clientX - r.left) / r.width, y = (ev.clientY - r.top) / r.height;   // 0..1 across the card
        card.style.setProperty('--mx', `${(x * 100).toFixed(1)}%`);
        card.style.setProperty('--my', `${(y * 100).toFixed(1)}%`);
        card.style.setProperty('--ry', `${((x - 0.5) * 9).toFixed(2)}deg`);
        card.style.setProperty('--rx', `${((0.5 - y) * 9).toFixed(2)}deg`);
    };
    document.addEventListener('pointermove', e => {
        if (e.pointerType !== 'mouse') return;
        const c = e.target.closest ? e.target.closest('.movie-card') : null;
        if (card && card !== c) {
            ['--mx', '--my', '--rx', '--ry'].forEach(p => card.style.removeProperty(p));
        }
        card = c;
        ev = e;
        if (card && !frame) frame = requestAnimationFrame(paint);
    }, {passive: true});
    document.addEventListener('pointerleave', () => {
        if (card) ['--mx', '--my', '--rx', '--ry'].forEach(p => card.style.removeProperty(p));
        card = null;
    });
}

// ---------------------------------------------------------------- opening splash + Discord status
// A short intro the first time you open the home page in a browser session. It never blocks anything: the page loads underneath,
// a click or key press skips it, and it removes itself. Not shown to people who asked their system for less motion.
function showSplash() {
    try {
        if (PAGE !== 'home' || reducedMotion()) return;
        if (navigator.webdriver && !window.__forceSplash) return;           // automated tests
        if (sessionStorage.getItem('ruin.splash')) return;
        sessionStorage.setItem('ruin.splash', '1');
    } catch (e) {
        return;
    }
    const el = document.createElement('div');
    el.id = 'splash';
    el.setAttribute('aria-hidden', 'true');
    el.innerHTML = '<div class="splash-logo" data-text="RUIN.TO">RUIN.TO</div><div class="splash-line"><i></i></div><div class="splash-sub">ENTER THE ABYSS</div>';
    document.body.appendChild(el);
    const close = () => {
        if (!el.isConnected || el.classList.contains('leaving')) return;
        el.classList.add('leaving');
        setTimeout(() => el.remove(), 700);
    };
    setTimeout(close, 2100);
    el.addEventListener('click', close);
    document.addEventListener('keydown', close, {once: true});
}

// The green dot by the Discord button. Green while the invite link works; it only turns red when Discord says the invite no longer
// exists (server deleted or invite revoked). If the check cannot run (offline, blocked) the dot simply stays green.
async function checkDiscordStatus(force = false) {
    const dots = document.querySelectorAll('.live-dot');
    if (!dots.length || typeof DISCORD_URL === 'undefined' || !DISCORD_URL) return;
    const code = DISCORD_URL.split('/').pop().split('?')[0];
    if (!code) return;
    const show = (alive, online) => {
        dots.forEach(d => d.classList.toggle('down', alive === false));
        const link = document.querySelector('.nav-discord');
        if (link) link.title = alive === false ? 'Discord invite is not working right now' : (online ? `Join our Discord server · ${online} online` : 'Join our Discord server');
    };
    try {
        const cached = JSON.parse(sessionStorage.getItem('ruin.discord') || 'null');
        if (!force && cached && Date.now() - cached.t < 60 * 1000) return show(cached.alive, cached.online);
    } catch (e) { /* no storage: just ask again */ }
    try {
        const res = await fetch(`https://discord.com/api/v10/invites/${encodeURIComponent(code)}?with_counts=true`);
        let alive = null, online = 0;
        if (res.status === 404) alive = false;
        else if (res.ok) {
            alive = true;
            online = (await res.json()).approximate_presence_count || 0;
        }
        if (alive === null) return;
        show(alive, online);
        try {
            sessionStorage.setItem('ruin.discord', JSON.stringify({t: Date.now(), alive, online}));
        } catch (e) { /* fine */ }
    } catch (e) {
        /* offline or blocked by the browser: keep the default green dot */
    }
}

function boot() {
    showSplash();
    tidyAddressBar();
    document.getElementById('app').innerHTML = buildPage();
    if (PAGE === 'legal') document.title = `${LEGAL_DOCS[document.body.dataset.doc]?.title || 'About'} | RUIN.TO`;
    else if (PAGE === 'dashboard') document.title = `${document.body.dataset.title || 'Profile'} | RUIN.TO`;
    else if (PAGE_TITLES[PAGE]) document.title = PAGE_TITLES[PAGE];
    initParticles();
    syncFilterUI();
    setupMobileNav();
    setupBackToTop();
    setupPolish();
    setupRouteBar();
    setupImageFade();
    checkDiscordStatus();
    // keep the dot live: ask again every minute while the tab is visible, and as soon as you come back to the tab
    setInterval(() => {
        if (!document.hidden) checkDiscordStatus(true);
    }, 60 * 1000);
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) checkDiscordStatus();
    });
    registerServiceWorker();

    if (PAGE === 'home') initHomepage();
    else if (PAGE === 'category') initCategory();
    else if (PAGE === 'search') initSearch();
    else if (PAGE === 'watch') initWatch();
    else if (PAGE === 'series') initSeries();
    else if (PAGE === 'person') initPerson();
}

// --- THE SERIES PAGE (series.html?id=76669&s=2&e=5) ---
// Details, seasons, and an episode picker. The picker only chooses WHICH episode; it does not start any stream. When the
// streaming side is ready it can listen for the "ruin:episode" event (or read window.ruinEpisode), which carry
// { tmdb, type: 'tv', season, episode, title, runtime }.
let seriesData = null, seriesSeasons = [], seriesSeasonNo = 1, seriesEpisodeNo = 1, seriesEpisodes = [];
let seriesChosen = false, seriesRecorded = false, seriesSaveTimer = 0;

// Watch history for a series, same rule as a movie: it is added when its page is opened (guests are never recorded). The entry
// also remembers the episode you are on ({ep: {s, e}}), so the history card says "S2 · E5" and reopens right there.
const seriesHistoryEntry = () => ({...currentMovie, ...(seriesEpisodes.length ? {ep: {s: seriesSeasonNo, e: seriesEpisodeNo}} : {})});

function recordSeriesOnce() {
    if (seriesRecorded || !seriesChosen || !currentMovie || !authReady) return;
    seriesRecorded = true;
    addToHistory(seriesHistoryEntry());
}
const seasonCache = new Map();           // "id:season" -> season details, so switching back is instant

function seriesFail(text) {
    const view = document.getElementById('series-view');
    if (!view) return;
    const back = mk('a', 'hero-btn', 'Back to home');
    back.href = pageUrl('');
    view.replaceChildren(mk('p', 'empty-note', text), back);
    document.title = 'Not found | RUIN.TO';
}

const stillUrl = (path, size = 'w300') => path ? `https://image.tmdb.org/t/p/${size}${path}` : '';
const seasonLabel = n => n === 0 ? 'Specials' : `Season ${n}`;

async function loadSeason(seasonNo) {
    const key = `${seriesData.id}:${seasonNo}`;
    if (seasonCache.has(key)) return seasonCache.get(key);
    const data = await tmdb(`https://api.themoviedb.org/3/tv/${seriesData.id}/season/${seasonNo}?api_key=${API_KEY}`);
    seasonCache.set(key, data);
    return data;
}

function paintSeasonTabs() {
    const bar = document.getElementById('season-tabs');
    if (!bar) return;
    bar.replaceChildren(...seriesSeasons.map(s => {
        const b = mk('button', 'season-tab' + (s.season_number === seriesSeasonNo ? ' active' : ''), seasonLabel(s.season_number));
        b.type = 'button';
        b.setAttribute('role', 'tab');
        b.setAttribute('aria-selected', String(s.season_number === seriesSeasonNo));
        b.title = `${s.episode_count} episode${s.episode_count === 1 ? '' : 's'}`;
        b.addEventListener('click', () => {
            if (s.season_number !== seriesSeasonNo) selectSeason(s.season_number, 1, true);
        });
        return b;
    }));
}

// touchUrl: true when the viewer chose it (the address then remembers it); false for the automatic first pick, so the page never
// rewrites its own address while it is still loading (that can abort the browser's page transition).
async function selectSeason(seasonNo, episodeNo, touchUrl = false) {
    seriesSeasonNo = seasonNo;
    paintSeasonTabs();
    const list = document.getElementById('episode-list');
    list.replaceChildren(...Array.from({length: 4}, () => mk('div', 'episode-row sk-ep')));
    let season;
    try {
        season = await loadSeason(seasonNo);
    } catch (err) {
        console.error(err);
        if (seasonNo === seriesSeasonNo) list.replaceChildren(stateBlock('The void could not list these episodes. Try again.', true, () => selectSeason(seasonNo, episodeNo, touchUrl)));
        return;
    }
    if (seasonNo !== seriesSeasonNo) return;     // another season was chosen while this one loaded
    seriesEpisodes = (season.episodes || []).slice().sort((a, b) => a.episode_number - b.episode_number);
    if (!seriesEpisodes.length) {
        list.replaceChildren(stateBlock('No episodes are listed for this season yet.', true));
        return;
    }
    const today = isoDate(0);
    list.replaceChildren(...seriesEpisodes.map(ep => {
        const row = mk('button', 'episode-row');
        row.type = 'button';
        row.dataset.ep = ep.episode_number;
        const thumb = mk('span', 'ep-thumb');
        const src = stillUrl(ep.still_path);
        if (src) {
            const img = mk('img');
            img.src = src;
            img.alt = '';
            img.loading = 'lazy';
            thumb.appendChild(img);
        }
        thumb.appendChild(mk('i', 'ep-num', String(ep.episode_number)));
        const main = mk('span', 'ep-main');
        const unaired = ep.air_date && ep.air_date > today;
        const meta = [ep.runtime ? `${ep.runtime} min` : '', ep.air_date ? (unaired ? `Airs ${prettyDate(ep.air_date)}` : prettyDate(ep.air_date)) : ''].filter(Boolean).join('  •  ');
        main.append(mk('b', 'ep-title', ep.name || `Episode ${ep.episode_number}`), mk('span', 'ep-meta', meta));
        if (ep.overview) main.appendChild(mk('span', 'ep-over', ep.overview));
        row.append(thumb, main);
        if (unaired) row.classList.add('unaired');
        row.addEventListener('click', () => selectEpisode(ep.episode_number, true));
        return row;
    }));
    const wanted = seriesEpisodes.some(e => e.episode_number === episodeNo) ? episodeNo : seriesEpisodes[0].episode_number;
    selectEpisode(wanted, touchUrl ? false : null);
}

function selectEpisode(episodeNo, userPicked) {
    const ep = seriesEpisodes.find(e => e.episode_number === episodeNo);
    if (!ep) return;
    seriesEpisodeNo = episodeNo;
    document.querySelectorAll('#episode-list .episode-row').forEach(r => r.classList.toggle('active', Number(r.dataset.ep) === episodeNo));

    if (userPicked !== null) {                      // null = the automatic first pick: leave the address (and the history) alone
        if (seriesRecorded) {                         // moving between episodes updates the history entry (a little later, so quick Next clicks cost one save)
            clearTimeout(seriesSaveTimer);
            seriesSaveTimer = setTimeout(() => addToHistory(seriesHistoryEntry()), 1500);
        }
        const q = new URLSearchParams(location.search);
        q.set('s', seriesSeasonNo);
        q.set('e', episodeNo);
        try {
            history.replaceState(null, '', `${location.pathname}?${q}`);          // a refresh or a shared link keeps the chosen episode
        } catch (e) { /* some browsers refuse; harmless */
        }
    }

    const still = stillUrl(ep.still_path, 'w780') || (seriesData.backdrop_path ? `https://image.tmdb.org/t/p/w780${seriesData.backdrop_path}` : '');
    document.getElementById('series-still').style.backgroundImage = still ? `url(${still})` : '';
    setText('series-stage-label', `${seriesSeasonNo === 0 ? 'Special' : `S${seriesSeasonNo}`} · E${episodeNo}`);
    setText('series-stage-title', ep.name || `Episode ${episodeNo}`);
    setText('series-stage-meta', [ep.runtime ? `${ep.runtime} min` : '', ep.air_date ? prettyDate(ep.air_date) : ''].filter(Boolean).join('  •  '));
    const idx = seriesEpisodes.indexOf(ep);
    document.getElementById('series-prev').disabled = idx === 0 && !prevSeason();
    document.getElementById('series-next').disabled = idx === seriesEpisodes.length - 1 && !nextSeason();
    if (userPicked === true) document.getElementById('series-stage').scrollIntoView({behavior: reducedMotion() ? 'auto' : 'smooth', block: 'nearest'});

    window.ruinEpisode = {tmdb: seriesData.id, type: 'tv', season: seriesSeasonNo, episode: episodeNo, title: ep.name || '', runtime: ep.runtime || 0};
    document.dispatchEvent(new CustomEvent('ruin:episode', {detail: window.ruinEpisode}));
}

const prevSeason = () => seriesSeasons[seriesSeasons.findIndex(s => s.season_number === seriesSeasonNo) - 1] || null;
const nextSeason = () => seriesSeasons[seriesSeasons.findIndex(s => s.season_number === seriesSeasonNo) + 1] || null;

async function stepEpisode(delta) {
    const i = seriesEpisodes.findIndex(e => e.episode_number === seriesEpisodeNo) + delta;
    if (i >= 0 && i < seriesEpisodes.length) return selectEpisode(seriesEpisodes[i].episode_number, false);
    const other = delta > 0 ? nextSeason() : prevSeason();
    if (!other) return;
    await selectSeason(other.season_number, delta > 0 ? 1 : 9999, true);     // 9999 = "last episode" (falls back to the nearest one below)
    if (delta < 0 && seriesEpisodes.length) selectEpisode(seriesEpisodes[seriesEpisodes.length - 1].episode_number, false);
}

async function initSeries() {
    const q = new URLSearchParams(location.search);
    const idText = q.get('id') || '';
    if (!/^\d{1,9}$/.test(idText)) return seriesFail('That link does not point to a series.');
    const id = Number(idText);
    SK.fill('similar-row', 8);

    let d;
    try {
        d = await tmdb(`https://api.themoviedb.org/3/tv/${id}?api_key=${API_KEY}&append_to_response=credits,similar`);
    } catch (err) {
        console.error(err);
        return seriesFail('The void could not find that series, or could not be reached. Try again in a moment.');
    }
    seriesData = {...d, id};
    currentMovie = slimMovie({...d, id, media_type: 'tv'});
    const title = d.name || 'Series';
    const year = (d.first_air_date || '').slice(0, 4);
    document.title = `${title}${year ? ` (${year})` : ''} | RUIN.TO`;
    document.getElementById('series-stage').classList.remove('sk');
    refreshSavedUI();

    if (d.backdrop_path) document.getElementById('series-backdrop').style.backgroundImage = `url(https://image.tmdb.org/t/p/w1280${d.backdrop_path})`;

    // details
    const seasonCount = d.number_of_seasons || 0, epCount = d.number_of_episodes || 0;
    const facts = [year, seasonCount ? `${seasonCount} season${seasonCount === 1 ? '' : 's'}` : '', epCount ? `${epCount} episodes` : '',
        d.vote_average ? `★ ${d.vote_average.toFixed(1)}` : ''].filter(Boolean).join('  •  ');
    const info = document.getElementById('series-info');
    const body = mk('div', 'watch-body');
    body.append(mk('h1', 'watch-title', title), mk('p', 'details-facts', facts));
    if (d.tagline) body.append(mk('p', 'watch-tagline', `“${d.tagline}”`));
    const chips = mk('div', 'hero-genres');
    chips.replaceChildren(...(d.genres || []).slice(0, 5).map(g => mk('span', 'chip', g.name)));
    body.append(chips, mk('p', 'details-overview', d.overview || 'No description yet.'));
    const grid = mk('div', 'watch-facts');
    const fact = (label, value) => {
        if (value) grid.append(mk('span', 'wf-label', label), mk('span', 'wf-value', value));
    };
    fact('Created by', (d.created_by || []).slice(0, 3).map(c => c.name).join(', '));
    fact('Network', (d.networks || []).slice(0, 2).map(n => n.name).join(', '));
    fact('Status', d.status);
    fact('First aired', d.first_air_date ? prettyDate(d.first_air_date) : '');
    fact('Last aired', d.status !== 'Returning Series' && d.last_air_date ? prettyDate(d.last_air_date) : '');
    fact('Language', d.spoken_languages?.[0]?.english_name);
    fact('Country', (d.production_countries || []).slice(0, 2).map(x => x.name).join(', ') || (d.origin_country || []).join(', '));
    fact('Rating', d.vote_average ? `★ ${d.vote_average.toFixed(1)} (${fmtCount(d.vote_count || 0)} votes)` : '');
    const kids = [];
    if (d.poster_path) {
        const img = mk('img', 'watch-poster');
        img.src = 'https://image.tmdb.org/t/p/w500' + d.poster_path;
        img.alt = title;
        kids.push(img);
    }
    info.classList.toggle('no-poster', !kids.length);
    info.replaceChildren(...kids, body, ...(grid.children.length ? [grid] : []));

    // seasons + episodes
    seriesSeasons = (d.seasons || []).filter(s => s.episode_count > 0)
        .sort((a, b) => (a.season_number || 999) - (b.season_number || 999));   // Specials (season 0) go last
    if (seriesSeasons.length) {
        document.getElementById('series-episodes-box').hidden = false;
        document.getElementById('series-prev').onclick = () => stepEpisode(-1);
        document.getElementById('series-next').onclick = () => stepEpisode(1);
        document.getElementById('series-play').onclick = () => showToast('Episode playback is not available yet.');
        // No season in the address: pick up where the history says you were (it can take a moment to load; never wait long).
        let histEp = null;
        if (!q.has('s')) {
            await Promise.race([historyReady, new Promise(r => setTimeout(r, 2000))]);
            histEp = historyList.find(m => isSeries(m) && m.id === id)?.ep || null;
        }
        const wantS = q.has('s') ? Number(q.get('s')) : (histEp ? histEp.s : NaN);        // Number(null) would be 0 (the Specials)
        const wantE = q.has('e') ? Number(q.get('e')) : (histEp ? histEp.e : NaN);
        const first = seriesSeasons.find(s => s.season_number === wantS) || seriesSeasons.find(s => s.season_number > 0) || seriesSeasons[0];
        await selectSeason(first.season_number, Number.isInteger(wantE) && wantE > 0 ? wantE : 1);
    } else {
        document.getElementById('series-stage').hidden = true;
        document.getElementById('series-episodes-box').hidden = true;
    }
    seriesChosen = true;
    recordSeriesOnce();

    // cast
    const cast = (d.credits?.cast || []).slice(0, 14);
    if (cast.length) {
        document.getElementById('series-cast').replaceChildren(...cast.map(c => {
            const card = mk('a', 'cast-card');
            card.href = personUrl(c.id);
            const photo = mk('div', 'cast-photo');
            if (c.profile_path) {
                const img = mk('img');
                img.src = 'https://image.tmdb.org/t/p/w185' + c.profile_path;
                img.alt = '';
                img.loading = 'lazy';
                photo.appendChild(img);
            } else photo.textContent = (c.name || '?').charAt(0);
            card.append(photo, mk('b', '', c.name), mk('span', '', c.roles?.[0]?.character || c.character || ''));
            return card;
        }));
        document.getElementById('series-cast-box').hidden = false;
    }

    // more like this
    const similar = (d.similar?.results || []).filter(m => m.poster_path).map(slimTv);
    if (similar.length) renderRow(similar, 'similar-row');
    else document.getElementById('series-similar-box').hidden = true;
}

boot();