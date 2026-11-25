// =====================================================================
//  RUIN.TO  -  components.js
//  The HTML that several pages share (header, filter bar, dashboard...).
//  Every page file (index.html, login.html, horror.html ...) is only a tiny shell;
//  script.js asks this file for the right pieces and puts them on the page.
//  Everything here is only CALLED after script.js has loaded, so it can use pageUrl().
// =====================================================================

const T = {};

// Small outline icons. Drawn as SVG (not emoji) so CSS can FILL them when active: a heart that turns red, a bookmark that turns gold.
const ICONS = {
    heart: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>',
    bookmark: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17 3H7c-1.1 0-2 .9-2 2v16l7-3 7 3V5c0-1.1-.9-2-2-2z"/></svg>',
    discord: '<svg class="ico-fill" viewBox="0 0 24 24" aria-hidden="true"><path d="M20.317 4.3698a19.7913 19.7913 0 00-4.8851-1.5152.0741.0741 0 00-.0785.0371c-.211.3753-.4447.8648-.6083 1.2495-1.8447-.2762-3.68-.2762-5.4868 0-.1636-.3933-.4058-.8742-.6177-1.2495a.077.077 0 00-.0785-.037 19.7363 19.7363 0 00-4.8852 1.515.0699.0699 0 00-.0321.0277C.5334 9.0458-.319 13.5799.0992 18.0578a.0824.0824 0 00.0312.0561c2.0528 1.5076 4.0413 2.4228 5.9929 3.0294a.0777.0777 0 00.0842-.0276c.4616-.6304.8731-1.2952 1.226-1.9942a.076.076 0 00-.0416-.1057c-.6528-.2476-1.2743-.5495-1.8722-.8923a.077.077 0 01-.0076-.1277c.1258-.0943.2517-.1923.3718-.2914a.0743.0743 0 01.0776-.0105c3.9278 1.7933 8.18 1.7933 12.0614 0a.0739.0739 0 01.0785.0095c.1202.099.246.1981.3728.2924a.077.077 0 01-.0066.1276 12.2986 12.2986 0 01-1.873.8914.0766.0766 0 00-.0407.1067c.3604.698.7719 1.3628 1.225 1.9932a.076.076 0 00.0842.0286c1.961-.6067 3.9495-1.5219 6.0023-3.0294a.077.077 0 00.0313-.0552c.5004-5.177-.8382-9.6739-3.5485-13.6604a.061.061 0 00-.0312-.0286zM8.02 15.3312c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9555-2.4189 2.157-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.9555 2.4189-2.1569 2.4189zm7.9748 0c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9554-2.4189 2.1569-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.946 2.4189-2.1568 2.4189Z"/></svg>',
    close: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>'
};

// Small UI icons for buttons (play, back, close, sort, volume, eye, mail). SVG so every device shows the same clean shapes.
const uIcon = (d, cls = '') => `<svg class="ui-ico${cls}" viewBox="0 0 24 24" aria-hidden="true">${d}</svg>`;
const UI = {
    play: uIcon('<path d="M7 4.5l12 7.5-12 7.5z"/>', ' fill'),
    back: uIcon('<path d="M19 12H5M11 6l-6 6 6 6"/>'),
    x: uIcon('<path d="M6 6l12 12M18 6L6 18"/>'),
    sort: uIcon('<path d="M8 4v16M4 8l4-4 4 4M16 20V4M12 16l4 4 4-4"/>'),
    volOn: uIcon('<path d="M4 9v6h4l5 4V5L8 9z"/><path d="M16.5 8.5a5 5 0 010 7M19 6a8.5 8.5 0 010 12"/>'),
    volOff: uIcon('<path d="M4 9v6h4l5 4V5L8 9z"/><path d="M17 9.5l4 5M21 9.5l-4 5"/>'),
    eye: uIcon('<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>'),
    mail: uIcon('<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>')
};

// ---------------------------------------------------------------- home page data
// Streaming services shown on the home page. Each one is also its own page (netflix.html ...).
//  provider = TMDB "watch provider" id(s)   company = TMDB production company id(s) (Marvel/DC are studios, not services)
//  A "|" between ids means OR. logoId is the id whose logo we show (the logo is fetched live from TMDB, see loadNetworkLogos).
const NETWORKS = [
    {key: 'netflix', name: 'Netflix', provider: '8', logoId: '8', match: /^Netflix/i},
    {key: 'disney', name: 'Disney+', provider: '337', logoId: '337', match: /^Disney\s*(\+|Plus)/i},
    {key: 'max', name: 'Max', provider: '1899|384', logoId: '1899', match: /^(Max|HBO Max)\b/i},
    {key: 'prime', name: 'Amazon Prime', provider: '9', logoId: '9', match: /^(Amazon )?Prime Video/i},
    {key: 'hulu', name: 'Hulu', provider: '15', logoId: '15', match: /^Hulu/i},
    {key: 'appletv', name: 'Apple TV+', provider: '350', logoId: '350', match: /^Apple TV\s*(\+|Plus)/i},
    {key: 'paramount', name: 'Paramount+', provider: '531', logoId: '531', match: /^Paramount\s*(\+|Plus)/i},
    {key: 'peacock', name: 'Peacock', provider: '386|387', logoId: '386', match: /^Peacock/i},
    {key: 'crunchyroll', name: 'Crunchyroll', provider: '283', logoId: '283', match: /^Crunchyroll/i},
    {key: 'starz', name: 'Starz', provider: '43', logoId: '43', match: /^Starz/i},
    {key: 'marvel', name: 'Marvel Studios', company: '420', logoId: '420'},
    {key: 'dc', name: 'DC Entertainment', company: '9993|128064', logoId: '9993'}
];

// Line icons for genres and section banners. Drawn as SVG (not emoji) so every device shows the same clean picture, and CSS
// can colour them. Used inside the genre cards, the Genres menu, the mobile genre sheet and the home page banners.
const gIcon = d => `<svg class="g-ico" viewBox="0 0 24 24" aria-hidden="true">${d}</svg>`;
const GI = {
    action: gIcon('<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>'),
    horror: gIcon('<path d="M5 21V11a7 7 0 0114 0v10l-2.5-2-2 2-2.5-2-2.5 2-2-2z"/><path d="M9.5 11h.01M14.5 11h.01"/>'),
    scifi: gIcon('<circle cx="12" cy="12" r="4.5"/><ellipse cx="12" cy="12" rx="10" ry="3.6" transform="rotate(-25 12 12)"/>'),
    comedy: gIcon('<circle cx="12" cy="12" r="9"/><path d="M8 14c1 2 2.2 3 4 3s3-1 4-3M9 9.5h.01M15 9.5h.01"/>'),
    animation: gIcon('<path d="M4 20l1-4L16 5l3 3L8 19z"/><path d="M14 7l3 3"/>'),
    crime: gIcon('<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>'),
    adventure: gIcon('<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>'),
    documentary: gIcon('<rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 10l5-3v10l-5-3z"/>'),
    drama: gIcon('<path d="M5 4h14v7c0 4-3 7-7 7s-7-3-7-7z"/><path d="M9 9h.01M15 9h.01M9 13c1 1 2 1.5 3 1.5s2-.5 3-1.5"/>'),
    family: gIcon('<circle cx="9" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M3 20c0-3.5 2.7-6 6-6s6 2.5 6 6M15 14.5c3 0 6 2 6 5.5"/>'),
    fantasy: gIcon('<path d="M12 3l6 17H6z"/><path d="M4 20h16"/>'),
    history: gIcon('<path d="M3 9l9-5 9 5z"/><path d="M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 20h18"/>'),
    music: gIcon('<path d="M9 18V5l10-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>'),
    mystery: gIcon('<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 115 0c0 1.7-2.5 2-2.5 4M12 17h.01"/>'),
    romance: gIcon('<path d="M12 20.5l-1.2-1.1C6 15.2 3 12.4 3 8.9 3 6.2 5.1 4.2 7.7 4.2c1.6 0 3.1.8 4.3 2.1 1.2-1.3 2.7-2.1 4.3-2.1C18.9 4.2 21 6.2 21 8.9c0 3.5-3 6.3-7.8 10.5z"/>'),
    thriller: gIcon('<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>'),
    war: gIcon('<circle cx="12" cy="12" r="8"/><path d="M12 2v5M12 17v5M2 12h5M17 12h5"/>'),
    western: gIcon('<path d="M12 3l2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.2l-5.6 3 1.1-6.2L3 9.6l6.2-.9z"/>'),
    tvmovie: gIcon('<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M8 21h8M9 3l3 3 3-3"/>'),
    film: gIcon('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M8 4l2 5M14 4l2 5"/>'),
    flower: gIcon('<circle cx="12" cy="12" r="2.6"/><path d="M12 3.5c2.6 2.2 2.6 5 0 6M12 20.5c-2.6-2.2-2.6-5 0-6M3.5 12c2.2-2.6 5-2.6 6 0M20.5 12c-2.2 2.6-5 2.6-6 0"/>'),
    star: gIcon('<path d="M12 3l2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.2l-5.6 3 1.1-6.2L3 9.6l6.2-.9z"/>'),
    trophy: gIcon('<path d="M7 4h10v5a5 5 0 01-10 0z"/><path d="M7 6H4v2a3 3 0 003 3M17 6h3v2a3 3 0 01-3 3M12 14v4M8 21h8M10 18h4"/>'),
};

// "Browse by genre" cards: [page key, label, icon, accent colour]. The key is also the page name (horror.html).
const GENRE_CARDS = [
    ['action', 'Action', GI.action, '#da0000'],
    ['horror', 'Horror', GI.horror, '#8e44ad'],
    ['scifi', 'Sci-Fi', GI.scifi, '#2e86de'],
    ['comedy', 'Comedy', GI.comedy, '#f0a500'],
    ['animation', 'Animation', GI.animation, '#d6409f'],
    ['crime', 'Crime', GI.crime, '#5d7b8a'],
    // the home page shows the first GENRE_VISIBLE cards; "Show all genres" reveals the rest
    ['adventure', 'Adventure', GI.adventure, '#e67e22'],
    ['documentary', 'Documentary', GI.documentary, '#16a085'],
    ['drama', 'Drama', GI.drama, '#b5651d'],
    ['family', 'Family', GI.family, '#27ae60'],
    ['fantasy', 'Fantasy', GI.fantasy, '#7d5fff'],
    ['history', 'History', GI.history, '#a08040'],
    ['music', 'Music', GI.music, '#e84393'],
    ['mystery', 'Mystery', GI.mystery, '#6c5ce7'],
    ['romance', 'Romance', GI.romance, '#ff6b81'],
    ['thriller', 'Thriller', GI.thriller, '#cf3a3a'],
    ['war', 'War', GI.war, '#6b8e23'],
    ['western', 'Western', GI.western, '#c19a6b'],
    ['tvmovie', 'TV Movie', GI.tvmovie, '#3498db']
];
const GENRE_VISIBLE = 6;
// history.html is the History GENRE; the Watch history page (your own viewing history) is watchhistory.html
const genreHref = key => pageUrl(key);

// Pages in the top bar next to Genres: [page key, emoji, label]. Each one is a normal page (trending.html ...).
// The emoji is its own field, so slicing a string can never split a surrogate pair.
// Clean line icons for the top bar (they take the colour of the text, so hover/active colours just work)
const navIcon = d => `<svg class="nav-ico" viewBox="0 0 24 24" aria-hidden="true">${d}</svg>`;
const NAV_ICONS = {
    home: navIcon('<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>'),
    grid: navIcon('<rect x="3" y="3" width="7" height="7" rx="1.6"/><rect x="14" y="3" width="7" height="7" rx="1.6"/><rect x="3" y="14" width="7" height="7" rx="1.6"/><rect x="14" y="14" width="7" height="7" rx="1.6"/>'),
    tv: navIcon('<rect x="3" y="5" width="18" height="12" rx="2"/><path d="M8 21h8M12 17v4"/>'),
    trending: navIcon('<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>'),
    star: navIcon('<path d="M12 3l2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.2l-5.6 3 1.1-6.2L3 9.6l6.2-.9z"/>'),
    spark: navIcon('<path d="M12 3v3M12 18v3M3 12h3M18 12h3"/><path d="M12 8l1.7 2.3L16 12l-2.3 1.7L12 16l-1.7-2.3L8 12l2.3-1.7z"/>'),
    flower: navIcon('<circle cx="12" cy="12" r="2.6"/><path d="M12 3.5c2.6 2.2 2.6 5 0 6M12 20.5c-2.6-2.2-2.6-5 0-6M3.5 12c2.2-2.6 5-2.6 6 0M20.5 12c-2.2 2.6-5 2.6-6 0"/>'),
    user: navIcon('<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7"/>'),
    clock: navIcon('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
    heart: navIcon('<path d="M12 20.5l-1.2-1.1C6 15.2 3 12.4 3 8.9 3 6.2 5.1 4.2 7.7 4.2c1.6 0 3.1.8 4.3 2.1 1.2-1.3 2.7-2.1 4.3-2.1C18.9 4.2 21 6.2 21 8.9c0 3.5-3 6.3-7.8 10.5z"/>'),
    bookmark: navIcon('<path d="M6 3h12v18l-6-4-6 4z"/>'),
    gear: navIcon('<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9L17 7M7 17l-2.1 2.1"/>'),
    logout: navIcon('<path d="M9 4H5v16h4"/><path d="M16 8l4 4-4 4M20 12H9"/>'),
    key: navIcon('<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M16 7l3 3"/>'),
    userPlus: navIcon('<circle cx="10" cy="8" r="4"/><path d="M3 21c0-4 3.1-6.5 7-6.5M18 8v6M15 11h6"/>'),
    chevron: '<svg class="nav-chev" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>'
};
// [page, icon, label, badge shown next to the word in the top bar]
const NAV_PAGES = [['trending', NAV_ICONS.trending, ' Trending', 'HOT'], ['tv', NAV_ICONS.tv, ' Series'], ['toprated', NAV_ICONS.star, ' Top Rated'], ['new', NAV_ICONS.spark, ' New'], ['anime', NAV_ICONS.flower, ' Anime']];

// "Ever epic series": a saga is either a list of TMDB collection ids or one production company.
const COLLECTIONS = [
    {key: 'marvel', name: 'Marvel Universe', company: '420'},
    {key: 'starwars', name: 'Star Wars', collections: [10]},
    {key: 'tolkien', name: "Tolkien's World", collections: [119, 121938]},
    {key: 'wizarding', name: 'Wizarding World', collections: [1241, 435259]}
];

// ---------------------------------------------------------------- header (every page)
T.header = () => `
  <header class="top-bar">
    <a class="logo" href="${pageUrl('')}" data-text="RUIN.TO">RUIN.TO</a>

    <nav class="nav-links">
      <a class="nav-item" href="${pageUrl('')}"><span class="nav-emoji" aria-hidden="true">${NAV_ICONS.home}</span>HOME</a>
      <div class="nav-item dropdown">
        <span class="nav-emoji" aria-hidden="true">${NAV_ICONS.grid}</span>GENRES ${NAV_ICONS.chevron}
        <div class="dropdown-content mega-menu">
          ${[0, 5, 10, 15].map(i => `<div class="menu-col">${GENRE_CARDS.slice(i, i + 5).map(([key, label, icon]) => `
            <a href="${genreHref(key)}">${icon} ${label}</a>`).join('')}
          </div>`).join('')}
        </div>
      </div>
      ${NAV_PAGES.map(([key, icon, label, badge]) => `<a class="nav-item" href="${pageUrl(key)}"><span class="nav-emoji" aria-hidden="true">${icon}</span>${label}${badge ? `<em class="nav-badge">${badge}</em>` : ''}</a>`).join('')}
    </nav>

    <div class="right-controls">
      ${DISCORD_URL ? `<a class="nav-discord" href="${DISCORD_URL}" target="_blank" rel="noopener noreferrer" aria-label="Join our Discord server" title="Join our Discord server">${ICONS.discord}<span>Discord</span><i class="live-dot" aria-hidden="true"></i></a>` : ''}
      <div class="search-box">
        <input type="text" id="search-input" placeholder="Summon a title..." onkeydown="handleSearch(event)">
      </div>

      <div id="auth-section">
        <!-- Logged OUT: Account button with a Sign in / Sign up dropdown -->
        <div class="account-wrapper" id="guest-account">
          <button class="account-btn" type="button" onclick="toggleAccountMenu(event)">
            <span class="acc-ico">${NAV_ICONS.user}</span><span class="acc-label"> Account </span><span class="chev">${NAV_ICONS.chevron}</span>
          </button>
          <div class="account-menu" id="account-menu">
            <a class="account-item" href="${pageUrl('login')}">
              <span class="ai-icon">${NAV_ICONS.key}</span>
              <span class="ai-text"><b>Sign in</b><small>Access your account</small></span>
            </a>
            <a class="account-item" href="${pageUrl('register')}">
              <span class="ai-icon">${NAV_ICONS.userPlus}</span>
              <span class="ai-text"><b>Sign up</b><small>Create new account</small></span>
            </a>
          </div>
        </div>

        <!-- Logged IN: avatar with the profile menu -->
        <div id="user-profile" style="display: none;">
          <img id="nav-avatar" src="${initialAvatar('')}" alt="Avatar" onerror="avatarFallback(this)">
          <div class="dropdown-content profile-menu">
            <a href="${pageUrl('profile')}">${NAV_ICONS.user} My profile</a>
            <a href="${pageUrl('watchhistory')}">${NAV_ICONS.clock} Watch history</a>
            <a href="${pageUrl('liked')}">${NAV_ICONS.heart} Liked</a>
            <a href="${pageUrl('watchlist')}">${NAV_ICONS.bookmark} Watchlist</a>
            <hr style="border-color: #222; margin: 5px 0;">
            <a href="${pageUrl('settings')}">${NAV_ICONS.gear} Settings</a>
            <a href="#" onclick="handleLogout(); return false;" style="color: var(--blood-red);">${NAV_ICONS.logout} Logout</a>
          </div>
        </div>
      </div>
    </div>
  </header>`;

// ---------------------------------------------------------------- phone / tablet navigation
// A bottom tab bar (shown by CSS on screens up to 900px wide) replaces the top menu there.
T.tabbar = () => {
    const svg = d => `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
    const icons = {
        home: svg('<path d="M3 11 12 3l9 8"/><path d="M5 10v10h14V10"/>'),
        genres: svg('<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>'),
        search: svg('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>'),
        user: svg('<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/>')
    };
    return `
  <nav class="tab-bar" aria-label="Main">
    <a class="tab" data-tab="home" href="${pageUrl('')}">${icons.home}<span>Home</span></a>
    <button class="tab" data-tab="genres" type="button" aria-haspopup="dialog" onclick="toggleGenreSheet()">${icons.genres}<span>Genres</span></button>
    <button class="tab" data-tab="search" type="button" onclick="toggleMobileSearch()">${icons.search}<span>Search</span></button>
    <a class="tab" id="bar-profile" data-tab="profile" href="${pageUrl('login')}">${icons.user}<span id="bar-profile-label">Sign in</span></a>
  </nav>
  <div class="sheet-overlay" id="genre-sheet" style="display: none;" onclick="if (event.target === this) toggleGenreSheet(false)">
    <div class="sheet" role="dialog" aria-modal="true" aria-label="Genres and services">
      <div class="sheet-handle" aria-hidden="true"></div>
      <h3>Browse</h3>
      <div class="sheet-grid">
        ${NAV_PAGES.map(([key, icon, label]) => `<a href="${pageUrl(key)}">${icon}${label}</a>`).join('')}
        ${DISCORD_URL ? `<a class="sheet-discord" href="${DISCORD_URL}" target="_blank" rel="noopener noreferrer">${ICONS.discord} Discord</a>` : ''}
      </div>
      <h3>Genres</h3>
      <div class="sheet-grid">
        ${GENRE_CARDS.map(([key, label, icon]) => `<a href="${genreHref(key)}"><span aria-hidden="true">${icon}</span> ${label}</a>`).join('')}
      </div>
      <h3>Services</h3>
      <div class="sheet-grid">
        ${NETWORKS.map(n => `<a href="${pageUrl(n.key)}">${n.name}</a>`).join('')}
      </div>
    </div>
  </div>`;
};

// ---------------------------------------------------------------- filter toolbar (category pages)
// Everything the toolbar offers is DATA in the lists below, so adding a country or a genre is a one-line change.
const THIS_YEAR = new Date().getFullYear();

// Genres: [key, label, TMDB movie id, TMDB tv id, label when TV is selected]
// TMDB uses different genre ids for movies and TV, and some genres exist for only one of them (null = does not exist).
const GENRES = [
    ['action', 'Action', '28', '10759', 'Action & Adventure'],
    ['adventure', 'Adventure', '12', null],
    ['animation', 'Animation', '16', '16'],
    ['comedy', 'Comedy', '35', '35'],
    ['crime', 'Crime', '80', '80'],
    ['documentary', 'Documentary', '99', '99'],
    ['drama', 'Drama', '18', '18'],
    ['family', 'Family', '10751', '10751'],
    ['fantasy', 'Fantasy', '14', null],
    ['history', 'History', '36', null],
    ['horror', 'Horror', '27', null],
    ['kids', 'Kids', null, '10762'],
    ['music', 'Music', '10402', null],
    ['mystery', 'Mystery', '9648', '9648'],
    ['news', 'News', null, '10763'],
    ['reality', 'Reality', null, '10764'],
    ['romance', 'Romance', '10749', null],
    ['scifi', 'Science Fiction', '878', '10765', 'Sci-Fi & Fantasy'],
    ['soap', 'Soap', null, '10766'],
    ['talk', 'Talk', null, '10767'],
    ['thriller', 'Thriller', '53', null],
    ['tvmovie', 'TV Movie', '10770', null],
    ['war', 'War', '10752', '10768', 'War & Politics'],
    ['western', 'Western', '37', '37']
];
const GENRE_BY_KEY = Object.fromEntries(GENRES.map(g => [g[0], g]));

const COUNTRIES = [
    ['AR', 'Argentina'], ['AU', 'Australia'], ['AT', 'Austria'], ['BE', 'Belgium'], ['BR', 'Brazil'], ['CA', 'Canada'],
    ['CL', 'Chile'], ['CN', 'China'], ['CO', 'Colombia'], ['CZ', 'Czechia'], ['DK', 'Denmark'], ['EG', 'Egypt'],
    ['FI', 'Finland'], ['FR', 'France'], ['DE', 'Germany'], ['GR', 'Greece'], ['HK', 'Hong Kong'], ['HU', 'Hungary'],
    ['IN', 'India'], ['ID', 'Indonesia'], ['IR', 'Iran'], ['IE', 'Ireland'], ['IL', 'Israel'], ['IT', 'Italy'],
    ['JP', 'Japan'], ['MY', 'Malaysia'], ['MX', 'Mexico'], ['NL', 'Netherlands'], ['NZ', 'New Zealand'],
    ['NG', 'Nigeria'], ['NO', 'Norway'], ['PK', 'Pakistan'], ['PH', 'Philippines'], ['PL', 'Poland'],
    ['PT', 'Portugal'], ['RO', 'Romania'], ['RU', 'Russia'], ['SA', 'Saudi Arabia'], ['SG', 'Singapore'],
    ['ZA', 'South Africa'], ['KR', 'South Korea'], ['ES', 'Spain'], ['SE', 'Sweden'], ['CH', 'Switzerland'],
    ['TW', 'Taiwan'], ['TH', 'Thailand'], ['TR', 'Turkey'], ['UA', 'Ukraine'], ['AE', 'United Arab Emirates'],
    ['GB', 'United Kingdom'], ['US', 'United States'], ['VN', 'Vietnam']
];

// Countries where TMDB knows which services carry which films ("watch regions"). Streaming catalogues differ by country,
// so TMDB answers for ONE at a time. 'All regions' (the default) asks the biggest ones and merges them (see tmdbAllRegions).
const REGIONS = [
    ['', 'All regions'], ['US', 'United States'], ['GB', 'United Kingdom'], ['CA', 'Canada'], ['AU', 'Australia'], ['NZ', 'New Zealand'],
    ['IE', 'Ireland'], ['DE', 'Germany'], ['FR', 'France'], ['ES', 'Spain'], ['IT', 'Italy'], ['NL', 'Netherlands'],
    ['BE', 'Belgium'], ['CH', 'Switzerland'], ['AT', 'Austria'], ['SE', 'Sweden'], ['NO', 'Norway'], ['DK', 'Denmark'],
    ['FI', 'Finland'], ['PL', 'Poland'], ['PT', 'Portugal'], ['GR', 'Greece'], ['CZ', 'Czechia'], ['HU', 'Hungary'],
    ['RO', 'Romania'], ['TR', 'Turkey'], ['RU', 'Russia'], ['UA', 'Ukraine'], ['IL', 'Israel'], ['EG', 'Egypt'],
    ['SA', 'Saudi Arabia'], ['AE', 'United Arab Emirates'], ['ZA', 'South Africa'], ['IN', 'India'], ['JP', 'Japan'],
    ['KR', 'South Korea'], ['TW', 'Taiwan'], ['HK', 'Hong Kong'], ['TH', 'Thailand'], ['VN', 'Vietnam'],
    ['ID', 'Indonesia'], ['MY', 'Malaysia'], ['SG', 'Singapore'], ['PH', 'Philippines'], ['BR', 'Brazil'],
    ['MX', 'Mexico'], ['AR', 'Argentina'], ['CL', 'Chile'], ['CO', 'Colombia'], ['PE', 'Peru']
];

// Each filter: how it looks. multi = several pills can be on at once. toggle = clicking an active pill turns it off.
// align 'right' makes the popover open leftwards, so it never runs off the edge of the screen.
const FILTER_DEFS = {
    type: {title: 'Type', id: 'popover-type', pills: [['movie', 'Movie'], ['tv', 'Series']]},
    genre: {
        title: 'Genre', id: 'popover-genre', multi: true, large: true,
        pills: GENRES.map(g => [g[0], g[1], {movieOnly: g[3] === null, tvOnly: g[2] === null, tvLabel: g[4]}])
    },
    country: {title: 'Country', id: 'popover-country', toggle: true, large: true, align: 'right', pills: COUNTRIES},
    // only shown on streaming-service pages (see .provider-only in style.css)
    region: {title: 'Region', id: 'popover-region', large: true, providerOnly: true, pills: REGIONS},
    year: {
        title: 'Released', id: 'popover-year', align: 'right',
        pills: [['', 'All'],
            ...Array.from({length: 5}, (_, i) => [String(THIS_YEAR - i), String(THIS_YEAR - i)]),
            ['older', 'Older']]
    },
    rating: {
        title: 'Rating', id: 'popover-rating', toggle: true, align: 'right',
        pills: [['4', '4+'], ['5', '5+'], ['6', '6+'], ['7', '7+'], ['8', '8+'], ['9', '9+'], ['10', '10']]
    },
    // TMDB has no video-quality data, so this is built from its RELEASE TYPES (see buildDiscoverUrl). Movies only.
    quality: {
        title: 'Quality', id: 'popover-quality', toggle: true, align: 'right', movieOnly: true,
        // 4K and SD are shown but switched off: TMDB cannot tell us either one, so they stay inactive until we have real data.
        pills: [['4k', '4K', {disabled: true}], ['hd', 'HD'], ['sd', 'SD', {disabled: true}], ['cam', 'CAM']]
    }
};

T.toolbar = () => {
    const pill = (key, [value, label, extra = {}]) => `
          <div class="filter-pill ${extra.movieOnly ? 'movie-only' : ''} ${extra.tvOnly ? 'tv-only' : ''} ${extra.disabled ? 'disabled' : ''}"
               data-key="${key}" data-value="${value}" data-label="${label}" ${extra.tvLabel ? `data-tv-label="${extra.tvLabel}"` : ''}
               ${extra.disabled ? 'title="Coming soon" aria-disabled="true"' : `onclick="selectPill('${key}', '${value}')"`}>${label}</div>`;
    const block = (key, def) => `
    <div class="filter-wrapper ${def.movieOnly ? 'movie-only' : ''} ${def.providerOnly ? 'provider-only' : ''}">
      <div class="filter-trigger" id="trigger-${key}" onclick="toggleFilterPopover(event, '${def.id}')">${def.title}
        <span class="filter-badge" id="badge-${key}"></span> <span class="eq-icon">=</span></div>
      <div class="filter-popover ${def.large ? 'large-popover' : ''} ${def.align === 'right' ? 'align-right' : ''}" id="${def.id}">
        <div class="pill-grid">${def.pills.map(p => pill(key, p)).join('')}
        </div>
        <button class="apply-btn" onclick="applyFilters()">Apply</button>
      </div>
    </div>`;

    const sortItems = [['newest', 'Newest'], ['popular', 'Most viewed'], ['release', 'Release date'],
        ['rating', 'Top rated'], ['name', 'Name A-Z'], ['votes', 'Most voted']];
    return `
  <div class="filter-toolbar" id="filter-toolbar">
    <h1 class="toolbar-title" id="category-title">&nbsp;</h1>
    <div class="toolbar-filters">
      ${Object.entries(FILTER_DEFS).map(([key, def]) => block(key, def)).join('')}

      <div class="filter-trigger clear-btn" onclick="clearFilters()">${UI.x} Clear All</div>

      <div class="filter-wrapper toolbar-sort">
        <div class="filter-trigger sort-button" id="sort-trigger" onclick="toggleFilterPopover(event, 'popover-sort')">Newest ${UI.sort}</div>
        <div class="filter-popover align-right" id="popover-sort" style="min-width: 200px; padding: 10px 0;">
          <div class="sort-list">
            ${sortItems.map(([key, label]) => `
            <div class="sort-item" data-sort="${key}" onclick="selectSort('${key}')">${label}</div>`).join('')}
          </div>
        </div>
      </div>
    </div>
  </div>`;
};

// ---------------------------------------------------------------- hero + player (home, categories, search)
T.hero = () => `
  ${SK.hero()}
  <div id="hero-banner" class="hero-showcase" style="display: none;">
    <div id="hero-trailer" class="hero-trailer" aria-hidden="true"></div>
    <div class="hero-overlay"></div>
    <button id="trailer-sound" class="trailer-sound" type="button" style="display: none;" aria-label="Turn trailer sound on" onclick="toggleTrailerSound()">${UI.volOff}</button>
    <div class="hero-content">
      <span class="hero-kicker" id="hero-kicker">FEATURED</span>
      <h1 id="hero-title">Movie Title</h1>
      <div class="hero-meta">
        <span class="rating-ring" id="hero-ring" style="--pct: 0" title="TMDB user score"><b id="hero-rating">0.0</b></span>
        <span id="hero-quality" class="meta-tag cam-tag" style="display: none;">CAM</span>
        <span id="hero-facts" class="hero-facts"></span>
      </div>
      <div id="hero-genres" class="hero-genres"></div>
      <p id="hero-overview">Overview...</p>
      <div class="hero-buttons">
        <button class="play-btn" onclick="playHeroMovie()">${UI.play} ENTER THE VOID</button>
        <button class="hero-btn" onclick="openDetails(heroMovie)">ⓘ Details</button>
        <button class="hero-icon-btn" id="hero-watchlist" data-list="watchlist" aria-label="Watch later" onclick="toggleSaved('watchlist', heroMovie)">${ICONS.bookmark}</button>
      </div>
    </div>
    <img id="hero-poster" class="hero-poster" alt="" style="display: none;">
    <div id="hero-strip" class="hero-strip" role="tablist" aria-label="Featured titles"></div>
  </div>`;

// A pop-up used for movie details and for a saga's list of films.
T.modal = () => `
  <div id="ruin-modal" class="modal-overlay" style="display: none;" onclick="if (event.target === this) closeModal()">
    <div class="modal-box" role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <button class="modal-close" type="button" aria-label="Close" onclick="closeModal()">${ICONS.close}</button>
      <div id="modal-body"></div>
    </div>
  </div>`;

// The watch page: one movie, its player, its details, its cast and similar films. (ids are reused by the player code)
T.watch = () => `
  <div id="watch-backdrop" class="watch-backdrop" aria-hidden="true"></div>
  <section id="watch-view" class="watch-view">
    <a class="watch-back" href="${pageUrl('')}" onclick="goBack(event)">${UI.back} Back</a>
    <div id="player-container" class="watch-player">
      <div class="watch-frame sk" id="player-shell">
        <video id="video-player" playsinline crossorigin="anonymous" preload="metadata"></video>
        <iframe id="player-fallback" title="Fallback player" hidden
                 allow="autoplay; fullscreen; encrypted-media; picture-in-picture"></iframe>

        <button id="pl-bigplay" type="button" aria-label="Play">▶</button>
        <div id="pl-toast" class="pl-toast" hidden></div>
        <div class="pl-menu" id="pl-quality" hidden></div>
        <div class="pl-menu" id="pl-subs" hidden></div>

        <div class="pl-controls">
          <button id="pl-play" type="button" aria-label="Play or pause">▶</button>
          <button id="pl-back10" type="button" aria-label="Back 10 seconds">↺</button>
          <button id="pl-fwd10" type="button" aria-label="Forward 10 seconds">↻</button>
          <span id="pl-time" class="pl-time">0:00 / 0:00</span>
          <input id="pl-seek" class="pl-seek" type="range" min="0" max="1000" value="0" aria-label="Seek">
          <input id="pl-volume" class="pl-volume" type="range" min="0" max="1" step="0.05" value="1" aria-label="Volume">
          <button id="pl-subs-btn" type="button" aria-label="Subtitles" hidden>CC</button>
          <button id="pl-quality-btn" type="button" aria-label="Quality" hidden>HD</button>
          <button id="pl-pip" type="button" aria-label="Picture in picture">▭</button>
          <button id="pl-full" type="button" aria-label="Fullscreen">⛶</button>
        </div>
      </div>

      <div class="dj-board">
        <div class="server-pick">
          <label for="server-switcher">SOURCE</label>
          <select id="server-switcher"></select>
        </div>
        <p class="watch-hint">Stuck or buffering? Switch the source.</p>
        <div class="player-actions">
          <button class="player-save-btn" id="player-like" data-list="liked" onclick="togglePlayerSave('liked')">${ICONS.heart}<span>Like</span></button>
          <button class="player-save-btn" id="player-watchlist" data-list="watchlist" onclick="togglePlayerSave('watchlist')">${ICONS.bookmark}<span>Watch later</span></button>
        </div>
      </div>
    </div>
    <div id="watch-info" class="watch-info" aria-live="polite">
      <div class="sk watch-sk-title"></div><div class="sk watch-sk-line"></div><div class="sk watch-sk-line short"></div>
    </div>
    <div id="watch-cast-box" class="watch-block" hidden><h2 class="section-title">CAST</h2><div id="watch-cast" class="watch-cast"></div></div>
    <div id="watch-similar-box" class="watch-block"><h2 class="section-title">MORE LIKE THIS</h2><div class="movie-row watch-similar" id="similar-row"></div></div>
  </section>`;

// ---------------------------------------------------------------- person (actor / director page)
T.person = () => `
  <section id="person-view" class="person-view">
    <a class="watch-back" href="#" onclick="goBack(event)">‹ Back</a>
    <div class="person-layout">
      <aside class="person-side"><div class="sk person-photo"></div></aside>
      <div class="person-main"><div class="sk watch-sk-title"></div><div class="sk watch-sk-line"></div><div class="sk watch-sk-line short"></div></div>
    </div>
  </section>`;

// ---------------------------------------------------------------- home
T.home = () => `
  <div id="home-view">
    <h2 class="section-title">BROWSE BY GENRE</h2>
    <div class="genre-grid" id="genre-grid">
      ${GENRE_CARDS.map(([key, label, icon, accent], i) => `
      <a class="genre-card${i >= GENRE_VISIBLE ? ' gc-extra' : ''}" data-loading data-genre="${key}" href="${genreHref(key)}" style="--accent: ${accent}">
        <span class="gc-icon" aria-hidden="true">${icon}</span>
        <span class="gc-text"><b class="gc-name">${label}</b><span class="gc-count">&nbsp;</span></span>
        <span class="gc-collage" aria-hidden="true"></span>
      </a>`).join('')}
    </div>
    <button type="button" class="genre-more-btn" id="genre-more" aria-expanded="false" onclick="toggleAllGenres()">Show all ${GENRE_CARDS.length} genres</button>

    <div id="continue-watching-section" style="display: none;">
      <h2 class="section-title">THE ABYSSAL ARCHIVES (Continue)</h2>
      <div class="carousel-container"><div class="movie-row" id="home-history-row"></div></div>
    </div>

    <h2 class="section-title">TRENDING IN THE INFERNO <a class="see-all" href="${pageUrl('trending')}">See all ›</a></h2>
    <div class="carousel-container"><div class="movie-row" id="trending-row"></div></div>

    <h2 class="section-title">PREMIUM NETWORKS</h2>
    <div class="network-grid" id="network-grid">
      ${NETWORKS.map(n => `
      <a class="network-card ${n.key}" data-loading data-network="${n.key}" href="${pageUrl(n.key)}">
        <span class="nc-logo"><span class="network-fallback">${n.name}</span></span>
        <span class="nc-name">${n.name}</span>
        <span class="nc-count">&nbsp;</span>
      </a>`).join('')}
    </div>

    <h2 class="section-title"><span id="network-tab-title">TRENDING ON NETFLIX</span> <a class="see-all" id="network-see-all" href="${pageUrl('netflix')}">See all ›</a></h2>
    <div class="network-tabs" id="network-tabs" role="tablist">
      ${NETWORKS.map((n, i) => `<button type="button" class="network-tab${i === 0 ? ' active' : ''}" role="tab" aria-selected="${i === 0}" data-network="${n.key}" onclick="selectNetworkTab('${n.key}')">${n.name}</button>`).join('')}
    </div>
    <div class="carousel-container"><div class="movie-row" id="network-row"></div></div>

    ${T.banner(GI.film, 'Latest Movies', 'Newest releases first', '#f08c2e', '', 'new')}
    <div class="movie-grid poster-grid" id="latest-grid"></div>

    ${T.banner(GI.flower, 'Anime Universe', 'アニメ', '#c04fd6', 'anime-count', 'anime')}
    <div class="movie-grid poster-grid" id="anime-grid"></div>

    <h2 class="section-title">EVER EPIC SERIES</h2>
    <div class="collection-grid" id="collection-grid">
      ${COLLECTIONS.map(c => `
      <button type="button" class="collection-card" data-loading data-collection="${c.key}" onclick="openCollection('${c.key}')" disabled>
        <span class="cc-stack"></span>
        <span class="cc-name">${c.name}</span>
        <span class="cc-count">&nbsp;</span>
      </button>`).join('')}
    </div>

    ${T.banner(GI.star, 'Top Rated Movies', 'Loved by the crowd', '#e8b84a', '', 'toprated')}
    <div class="carousel-container"><div class="movie-row" id="top-rated-row"></div></div>

    ${T.banner(GI.trophy, 'Award-Worthy Movies', 'Highly rated blockbusters', '#d4a017')}
    <div class="carousel-container"><div class="movie-row" id="award-row"></div></div>

    ${T.banner(GI.tvmovie, 'Popular Series', 'Trending this week', '#3498db', '', 'trending', pageUrl('trending') + '?type=tv')}
    <div class="carousel-container"><div class="movie-row" id="series-row"></div></div>

    ${T.banner(GI.star, 'Top Rated Series', 'The best of all time', '#e8b84a', '', 'toprated', pageUrl('toprated') + '?type=tv')}
    <div class="carousel-container"><div class="movie-row" id="series-top-row"></div></div>
  </div>`;

// The series page: details, season tabs and an episode list. The big box shows the chosen episode; it is a picker for now
// (the streaming side can listen for the "ruin:episode" event later), so its play button only explains that.
T.series = () => `
  <div id="series-backdrop" class="watch-backdrop" aria-hidden="true"></div>
  <section id="series-view" class="watch-view series-view">
    <a class="watch-back" href="#" onclick="goBack(event)">${UI.back} Back</a>
    <div class="series-stage sk" id="series-stage">
      <div class="series-still" id="series-still"></div>
      <button type="button" class="series-play" id="series-play" aria-label="Play episode"><svg viewBox="0 0 24 24" width="34" height="34" fill="currentColor" aria-hidden="true"><path d="M8 5.5v13a1 1 0 0 0 1.5.86l11-6.5a1 1 0 0 0 0-1.72l-11-6.5A1 1 0 0 0 8 5.5z"/></svg></button>
      <div class="series-stage-ui">
        <div class="series-stage-text">
          <span class="series-stage-label" id="series-stage-label"></span>
          <b class="series-stage-title" id="series-stage-title"></b>
          <span class="series-stage-meta" id="series-stage-meta"></span>
        </div>
        <div class="series-stage-nav">
          <button type="button" class="series-step" id="series-prev" aria-label="Previous episode">‹ Prev</button>
          <button type="button" class="series-step" id="series-next" aria-label="Next episode">Next ›</button>
        </div>
      </div>
    </div>
    <div class="player-actions series-actions">
      <button class="player-save-btn" id="player-like" data-list="liked" onclick="togglePlayerSave('liked')">${ICONS.heart}<span>Like</span></button>
      <button class="player-save-btn" id="player-watchlist" data-list="watchlist" onclick="togglePlayerSave('watchlist')">${ICONS.bookmark}<span>Watch later</span></button>
    </div>
    <div id="series-info" class="watch-info" aria-live="polite">
      <div class="sk watch-sk-title"></div><div class="sk watch-sk-line"></div><div class="sk watch-sk-line short"></div>
    </div>
    <div id="series-episodes-box" class="watch-block" hidden>
      <h2 class="section-title">EPISODES</h2>
      <div class="season-tabs" id="season-tabs" role="tablist" aria-label="Seasons"></div>
      <div class="episode-list" id="episode-list"></div>
    </div>
    <div id="series-cast-box" class="watch-block" hidden><h2 class="section-title">CAST</h2><div id="series-cast" class="watch-cast"></div></div>
    <div id="series-similar-box" class="watch-block"><h2 class="section-title">MORE LIKE THIS</h2><div class="movie-row watch-similar" id="similar-row"></div></div>
  </section>`;

T.toTop = () => `
  <button type="button" id="to-top" class="to-top" aria-label="Back to top">
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5"/><path d="M5 12l7-7 7 7"/></svg>
  </button>`;

// ---------------------------------------------------------------- category + search results
T.grid = (withTitle) => `
  <div id="grid-view">
    ${withTitle ? '<h1 id="category-title">&nbsp;</h1>' : ''}
    <div class="movie-grid" id="movie-grid"></div>
  </div>`;

// ---------------------------------------------------------------- profile / history / liked / watchlist / settings
T.dashboard = (tab) => {
    const isSettings = tab === 'settings';
    const paneTitle = 'font-family: \'Montserrat\'; font-size: 1.2em; font-weight: bold; border: none; padding: 0;';
    const tabs = [['overview', 'profile', 'Overview'], ['liked', 'liked', 'Liked'],
        ['history', 'watchhistory', 'Watch history'], ['watchlist', 'watchlist', 'Watchlist']];

    const panes = {
        overview: `<h2 class="section-title" style="${paneTitle}">Recent Activity</h2>
               <div class="carousel-container" style="margin-top: 20px;"><div class="movie-row" id="overview-history-row"></div></div>`,
        history: `<div class="pane-head">
                 <h2 class="section-title" style="${paneTitle}">Full Watch History</h2>
                 <div id="clear-history-wrap" style="display: none;"><button class="pane-action-btn" onclick="askClearHistory()">Clear all history</button></div>
               </div>
               <div class="carousel-container" style="margin-top: 20px;"><div class="movie-row" id="full-history-row"></div></div>
               <p class="empty-note" id="history-empty" style="display: none;">Nothing here yet. Movies you start watching will appear here.</p>`,
        liked: `<h2 class="section-title" style="${paneTitle}">Liked Souls</h2>
               <div class="movie-grid saved-grid" id="liked-grid"></div>
               <p class="empty-note" id="liked-empty">You haven't liked any movies yet. Tap the heart on a movie to keep it here.</p>`,
        watchlist: `<h2 class="section-title" style="${paneTitle}">Your Watchlist</h2>
               <div class="movie-grid saved-grid" id="watchlist-grid"></div>
               <p class="empty-note" id="watchlist-empty">Your watchlist is empty. Tap the bookmark on a movie to save it for later.</p>`
    };

    const banner = isSettings
        ? `<div id="banner-overlay" class="edit-overlay" onclick="document.getElementById('set-banner-file').click()" style="display: flex;"><span class="edit-label"><svg class="cam-icon" viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 8h3l1.5-2h7L17 8h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/><circle cx="12" cy="13" r="3.5"/></svg><b id="banner-overlay-text">Change banner</b></span></div>`
        : '';
    const avatarEdit = isSettings
        ? `<div id="avatar-overlay" class="edit-overlay avatar-edit-overlay" onclick="document.getElementById('set-avatar-file').click()" style="display: flex;"><span class="edit-label"><svg class="cam-icon" viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 8h3l1.5-2h7L17 8h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/><circle cx="12" cy="13" r="3.5"/></svg><b>Change</b></span></div>`
        : '';

    const body = isSettings ? `
    <div id="settings-content">
      <div class="settings-form-container">
        <div class="input-group">
          <label>Name</label>
          <input type="text" id="set-name" placeholder="☠ Ruin ☠" maxlength="40">
        </div>
        <div class="input-group">
          <label>Email</label>
          <input type="email" id="set-email" disabled style="opacity: 0.5; cursor: not-allowed;">
        </div>
        <div class="input-group">
          <label>Username</label>
          <input type="text" id="set-username" placeholder="Your name in the abyss" autocapitalize="none" spellcheck="false" oninput="onUsernameInput(this, 'set-username-hint')">
          <div class="field-hint" id="set-username-hint">2-24 characters. Letters, emoji, symbols, spaces: anything goes.</div>
        </div>
        <div class="input-group">
          <label>About</label>
          <input type="text" id="set-about" placeholder="depressed" maxlength="120">
        </div>

        <h3 style="margin-top: 40px; margin-bottom: 20px; font-family: 'Montserrat'; border: none; font-size: 1.2em;">Change password</h3>
        <div class="input-group">
          <label>Current password</label>
          <input type="password" id="set-current-password" placeholder="Current password" autocomplete="current-password">
        </div>
        <div class="input-group">
          <label>New password</label>
          <input type="password" id="set-new-password" placeholder="New password (min. 8 characters)" autocomplete="new-password">
        </div>
        <button id="save-settings-btn" class="play-btn" style="background: #1cb569; width: auto; min-width: 200px; padding: 15px; margin-top: 10px;" onclick="saveSettings()">Save change</button>
        <p id="settings-msg" style="color: var(--blood-red); margin-top: 15px; font-weight: bold; height: 20px; transition: 0.3s;"></p>
      </div>
    </div>` : `
    <div id="profile-content">
      <div class="dash-tabs">
        ${tabs.map(([key, page, label]) => `<a id="tab-${key}" class="dash-tab ${key === tab ? 'active' : ''}" href="${pageUrl(page)}">${label}</a>`).join('')}
      </div>
      <div id="pane-${tab}" class="tab-pane" style="margin-top: 30px;">${panes[tab]}</div>
    </div>`;

    return `
  <div id="user-dashboard" style="max-width: 1200px; margin: 0 auto;">
    <div class="dash-header">
      <div id="dash-banner" class="dash-banner">${banner}</div>
      <input type="file" id="set-banner-file" accept="image/*" style="display: none;" onchange="handleFileSelect(event, 'banner')">

      <div class="dash-user-info">
        <div class="dash-avatar-wrapper">
          <img id="dash-avatar" src="${initialAvatar('')}" alt="Avatar" onerror="avatarFallback(this)">
          ${avatarEdit}
        </div>
        <input type="file" id="set-avatar-file" accept="image/*" style="display: none;" onchange="handleFileSelect(event, 'avatar')">

        <div class="dash-text-info">
          <h1 id="dash-display-name">Summoner</h1>
          <p id="dash-display-username" class="dash-username"></p>
          <p id="dash-display-about">The abyss welcomes you.</p>
        </div>
      </div>
    </div>
    ${body}
  </div>`;
};

// ---------------------------------------------------------------- login + register
const EYE_BUTTON = `<button type="button" class="pw-toggle" onclick="togglePassword(this)" aria-label="Show password">${UI.eye}</button>`;

T.auth = (mode) => {
    const isRegister = mode === 'register';
    return `
  <div class="auth-wrap">
    <div class="auth-card">
      <div class="auth-brand">Ruin</div>
      <h1>${isRegister ? 'Create an Account' : 'Enter the Covenant'}</h1>
      <p class="auth-tagline">FAITH · DECAY · REVENGE · REBIRTH</p>

      <form id="auth-form" onsubmit="${isRegister ? 'handleRegister(event)' : 'handleLogin(event)'}" novalidate>
        ${isRegister ? `
        <div class="auth-field">
          <label for="reg-name">Name</label>
          <input id="reg-name" type="text" placeholder="Name" autocomplete="name" maxlength="40">
        </div>
        <div class="auth-field">
          <label for="reg-username">Username</label>
          <input id="reg-username" type="text" placeholder="Username" autocomplete="username"
                 autocapitalize="none" spellcheck="false" oninput="onUsernameInput(this)">
          <div class="field-hint" id="username-hint">2-24 characters. Letters, emoji, symbols, spaces: anything goes.</div>
        </div>` : ''}
        <div class="auth-field">
          <label for="auth-email">Email</label>
          <input id="auth-email" type="email" placeholder="Email" autocomplete="email">
        </div>
        <div class="auth-field">
          <label for="auth-password">Password</label>
          <div class="pw-wrap">
            <input id="auth-password" type="password" placeholder="Password" autocomplete="${isRegister ? 'new-password' : 'current-password'}">
            ${EYE_BUTTON}
          </div>
          ${isRegister ? '<div class="field-hint">At least 8 characters</div>' : ''}
        </div>

        <p class="auth-msg" id="auth-msg" role="alert"></p>
        <button class="auth-submit" id="auth-submit" type="submit">${isRegister ? 'Sign up' : 'Sign in'}</button>
      </form>

      <!-- shown instead of the form after sign-up, or when a login needs the email confirmed -->
      <div class="auth-success" id="auth-success" style="display: none;">
        <div class="auth-success-icon">${UI.mail}</div>
        <h2>Check your inbox</h2>
        <p>We sent a confirmation link to <b id="auth-success-email"></b>.<br>Open it, then come back and sign in.</p>
        <button class="auth-secondary" type="button" id="resend-btn" onclick="resendConfirmation()">Resend email</button>
        <p class="auth-msg" id="resend-msg" role="status"></p>
        <a class="auth-secondary-link" href="${pageUrl('login')}">Go to sign in</a>
      </div>

      <p class="auth-switch">
        ${isRegister
        ? `Already have an account? <a href="${pageUrl('login')}">Sign in</a>`
        : `Don't have an account? <a href="${pageUrl('register')}">Sign up</a>`}
      </p>
      <p class="auth-quote">Some sins never die.<br>They learn to wear a different face.</p>
    </div>
  </div>`;
};


// ---------------------------------------------------------------- section banner (home page)
// icon, title, small subtitle, accent colour, optional id for the subtitle (script.js fills in a count there)
T.banner = (icon, title, sub, accent, subId, moreKey, moreHref) => `
  <div class="section-banner" style="--accent: ${accent}">
    <span class="sb-icon" aria-hidden="true">${icon}</span>
    <div class="sb-text"><h2 class="sb-title">${title}</h2><span class="sb-sub"${subId ? ` id="${subId}"` : ''}>${sub}</span></div>
    ${moreKey ? `<a class="see-all" href="${moreHref || pageUrl(moreKey)}">See all ›</a>` : ''}
  </div>`;

// ---------------------------------------------------------------- footer + legal pages
// !!! SET THIS to your Discord server invite link (for example 'https://discord.gg/xxxxxx').
// The legal pages and the footer send visitors there for content requests, privacy requests and copyright notices.
// While it is empty, the legal pages show a red warning so you cannot forget.
const DISCORD_URL = 'https://discord.gg/msvnt4JxHJ';
const contactLink = (text = 'our Discord server') => DISCORD_URL
    ? `<a href="${DISCORD_URL}" target="_blank" rel="noopener noreferrer">${text}</a>`
    : '<i>(Discord link not set)</i>';

T.footer = () => `
  <footer class="site-footer">
    <div class="footer-grid">
      <div class="footer-brand">
        <a class="logo" href="${pageUrl('')}">RUIN.TO</a>
        <p>A dark place to find your next movie night. Browse, save and keep track of what you watch.</p>
      </div>
      <div class="footer-col">
        <h4>Browse</h4>
        <a href="${pageUrl('')}">Home</a>
        ${GENRE_CARDS.map(([key, label]) => `<a href="${pageUrl(key)}">${label}</a>`).join('')}
      </div>
      <div class="footer-col">
        <h4>Services</h4>
        ${NETWORKS.slice(0, 6).map(n => `<a href="${pageUrl(n.key)}">${n.name}</a>`).join('')}
      </div>
      <div class="footer-col">
        <h4>About</h4>
        <a href="${pageUrl('about')}">About us</a>
        <a href="${pageUrl('privacy')}">Privacy Policy</a>
        <a href="${pageUrl('privacy')}#cookies">Cookie Policy</a>
        <a href="${pageUrl('terms')}">Terms of Service</a>
        <a href="${pageUrl('dmca')}">DMCA</a>
        <a href="#" id="install-link" hidden onclick="installApp(); return false;">Install app</a>
        ${DISCORD_URL ? `<a href="${DISCORD_URL}" target="_blank" rel="noopener noreferrer">Contact us (Discord)</a>` : ''}
      </div>
    </div>
    <div class="footer-bottom">
      <p>© ${THIS_YEAR} RUIN.TO. All rights reserved.</p>
      <p class="tmdb-credit">
        <a href="https://www.themoviedb.org" target="_blank" rel="noopener noreferrer" aria-label="TMDB"><img src="${APP_BASE}assets/tmdb-logo.svg" alt="TMDB" height="14" onerror="this.replaceWith(document.createTextNode('TMDB'))"></a>
        This product uses the TMDB API but is not endorsed or certified by TMDB.
      </p>
    </div>
  </footer>`;

// The text of the legal pages. Short and written for visitors: what they get, what is kept about them, the house rules.
// They are templates, not legal advice: have a lawyer check them before you take the site public or make money from it.
const LEGAL_DOCS = {
    about: {
        title: 'About', html: () => `
    <p>RUIN.TO is a home for people who like their movies dark, loud and unforgettable. Find your next movie night, keep track of what you have watched, and save the ones you cannot wait to see.</p>
    <h2>What you will find here</h2>
    <ul>
      <li><b>Movies</b> across every mood: action, horror, sci-fi, comedy, animation, crime and more.</li>
      <li><b>Anime</b>, from long-running favourites to the newest releases.</li>
      <li><b>Streaming-service pages</b> to browse titles from Netflix, Disney+, Max, Hulu, Prime Video, Apple TV+ and others.</li>
      <li><b>Epic sagas</b> such as Marvel, Star Wars, Tolkien and Wizarding World, gathered in one place.</li>
      <li><b>Smart filters</b> by genre, year, rating and country, plus search.</li>
      <li><b>Your own library:</b> a watch history so you can pick up where you left off, a <b>Liked</b> list for the ones you will rewatch, and a <b>Watch later</b> list for movie nights.</li>
    </ul>
    <h2>More is coming</h2>
    <p>New categories, more anime and new features are on the way.</p>
    <h2>Want something added?</h2>
    <p>Looking for a title, a category or a feature you cannot find? Tell us on ${contactLink()} and we will do our best.</p>
    <p class="legal-updated">Movie information and images are provided by TMDB. This product uses the TMDB API but is not endorsed or certified by TMDB.</p>`
    },

    privacy: {
        title: 'Privacy Policy', html: () => `
    <p class="legal-updated">Last updated: ${new Date().toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'long',
            day: 'numeric'
        })}</p>

    <h2>1. Overview</h2>
    <p>Welcome to RUIN.TO. We want you to enjoy your movie nights knowing your information is handled with care. This policy explains what is private, what we save, how we use it and what you can do about it.</p>

    <h2>2. What stays private</h2>
    <ul>
      <li>Your <b>password</b> is never visible to us or to anyone else.</li>
      <li>Your <b>watch history</b>, <b>Liked</b> list and <b>Watch later</b> list can only be seen by you.</li>
      <li>We do not sell your personal information.</li>
      <li>We do not use your information to build advertising profiles.</li>
    </ul>

    <h2>3. Information we save</h2>
    <p>You can browse RUIN.TO without an account, and then we save nothing about you. If you create an account, we save only what is needed to run it:</p>
    <ul>
      <li>Your email address and username.</li>
      <li>The profile details you choose to add: a display name, an "about" note, and your avatar and banner pictures.</li>
      <li>The movies you start watching, and the ones you add to Liked and Watch later, so they are waiting for you when you come back.</li>
    </ul>

    <h2 id="cookies">4. Information stored in your browser</h2>
    <p>To keep you signed in and to make pages load faster, RUIN.TO keeps small pieces of information in your browser:</p>
    <ul>
      <li><b>Sign-in:</b> so you do not have to log in on every page. Signing out removes it.</li>
      <li><b>Temporary page data:</b> short-lived information that speeds up the home page and disappears when you close the tab.</li>
    </ul>
    <p>This information stays on your device, and you can remove it at any time from your browser's settings.</p>

    <h2>5. How we use your information</h2>
    <p>We use it only to run your account and your lists, to keep your sign-in working, and to keep RUIN.TO safe. We do not use it for anything else.</p>

    <h2>6. Sharing</h2>
    <p>We do not sell or rent your personal information. We share it only with the service providers that help us run RUIN.TO, who may use it only for that purpose, or when the law requires it.</p>

    <h2>7. Other websites and services</h2>
    <p>RUIN.TO features content and links from partners and external services. They follow their own privacy practices, which we do not control, so please read them before sharing personal information with them.</p>

    <h2>8. Protecting your information</h2>
    <p>Information moving between your browser and RUIN.TO is encrypted (HTTPS), and each account can only reach its own data. No method of storing or sending information over the internet is completely secure, so we cannot promise absolute security.</p>

    <h2>9. Your choices and rights</h2>
    <ul>
      <li>Remove any item from your watch history, Liked or Watch later lists from your profile whenever you like.</li>
      <li>Clear or block the information stored in your browser through your browser's settings (some features may stop working).</li>
      <li>Ask to see, correct or delete your account and its information by contacting us on ${contactLink()}.</li>
    </ul>

    <h2>10. Children</h2>
    <p>RUIN.TO is not meant for children under thirteen, and we do not knowingly collect their information. If you believe a child has given us information, tell us and we will remove it.</p>

    <h2>11. International visitors</h2>
    <p>RUIN.TO can be visited from anywhere, so your information may be processed in countries other than your own. If you live in the European Economic Area, you may have additional rights under the GDPR, such as access, correction and deletion. If you live in California, we do not sell personal information as defined by the CCPA. To use any of these rights, contact us on ${contactLink()}.</p>

    <h2>12. Changes to this policy</h2>
    <p>We may update this policy from time to time. The date at the top shows the latest version, so please check it now and then.</p>

    <h2>13. Contact</h2>
    <p>Questions about your privacy? Reach us on ${contactLink()}.</p>

    <h2>14. Agreement</h2>
    <p>By using RUIN.TO you accept this Privacy Policy. If you do not agree with it, please stop using the site.</p>`
    },

    dmca: {
        title: 'Copyright Notice (DMCA)', html: () => `
    <p class="legal-updated">Last updated: ${new Date().toLocaleDateString('en-US', {year: 'numeric', month: 'long'})}</p>
    <p>RUIN.TO respects the rights of creators and owners. If you are a copyright owner, or you act for one, and you believe something on RUIN.TO infringes your rights, please tell us and we will look into it.</p>
    <h2>How to send a notice</h2>
    <p>Contact us on ${contactLink()} and include:</p>
    <ul>
      <li>Your name and how we can reach you.</li>
      <li>The work you say has been infringed.</li>
      <li>The page on RUIN.TO where the problem is (copy the address from your browser).</li>
      <li>A statement that you believe in good faith that the use is not authorised by the owner, the owner's agent or the law.</li>
      <li>A statement that the information in your notice is accurate and that you are the owner, or are allowed to act for the owner.</li>
    </ul>
    <h2>What happens next</h2>
    <p>We review each notice. If it is valid, we remove or block the item as soon as we reasonably can.</p>
    <h2>Repeat issues</h2>
    <p>We may suspend accounts that repeatedly misuse RUIN.TO.</p>
    <h2>False notices</h2>
    <p>Please send a notice only if you are sure it is accurate. Knowingly sending a false notice can have legal consequences.</p>`
    },

    terms: {
        title: 'Terms of Service', html: () => `
    <p class="legal-updated">Last updated: ${new Date().toLocaleDateString('en-US', {year: 'numeric', month: 'long'})}</p>
    <p>By using RUIN.TO you agree to these rules. If you do not agree, please do not use the site.</p>
    <h2>Using RUIN.TO</h2>
    <ul>
      <li>RUIN.TO is provided "as is". We cannot promise that it will always be available, accurate or free of errors.</li>
      <li>Titles, descriptions and availability can change or be wrong. Check details before you rely on them.</li>
      <li>Content on RUIN.TO comes from partners and external services. We do not guarantee that it is available, safe or of any particular quality, and you are responsible for making sure that watching it is lawful where you live.</li>
    </ul>
    <h2>Your account</h2>
    <ul>
      <li>Keep your password private. You are responsible for what happens on your account.</li>
      <li>Pick a username that is not offensive and does not pretend to be someone else.</li>
      <li>Do not try to break, overload or gain unauthorised access to the site or to other people's accounts.</li>
    </ul>
    <h2>Copyright</h2>
    <p>We respect the rights of creators. If you believe something on RUIN.TO is a problem, read our <a href="${pageUrl('dmca')}">copyright notice (DMCA)</a>.</p>
    <h2>Liability</h2>
    <p>To the extent the law allows, RUIN.TO and its owner are not responsible for any loss or damage that comes from using the site or from content reached through it.</p>
    <h2>Changes and ending use</h2>
    <p>We may change these rules or the site at any time, and we may suspend accounts that break these rules. Continuing to use RUIN.TO means you accept the updated rules.</p>
    <h2>Contact</h2>
    <p>Questions? Reach us on ${contactLink()}.</p>`
    }
};

T.legal = doc => {
    const d = LEGAL_DOCS[doc] || LEGAL_DOCS.about;
    return `
  <article class="legal-page">
    <h1>${d.title}</h1>
    ${DISCORD_URL ? '' : '<p class="legal-warning">⚠ Owner notice: no Discord link is set yet. Open <code>components.js</code> and fill in <code>DISCORD_URL</code>.</p>'}
    ${d.html()}
  </article>`;
};