/* Birdie mobile app: Explore, Saved, About, and a Place screen with the live floor plan.
 *
 * Reads the read-only API in CLAUDE.md section 7.2 and polls it every 2 seconds:
 *   GET api/venues               list of venues with seat counts
 *   GET api/venues/{venue_id}    one venue with its floor plan and live seats
 * Without a backend (or with ?mock=1) it uses the same-shaped data from mock.js.
 * Add ?nosplash to skip the splash while developing.
 */
(() => {
  'use strict';

  const POLL_MS = 2000;
  const SAVED_KEY = 'birdie:saved';
  const TYPES = { library: 'Library', cafe: 'Café', cowork: 'Coworking', study_room: 'Study room' };
  const CATS = [['all', 'All'], ['library', 'Libraries'], ['cafe', 'Cafés'], ['cowork', 'Coworking'], ['study_room', 'Study rooms']];
  const SORTS = [['near', 'Nearest'], ['free', 'Most study spaces'], ['late', 'Open late']];
  const SEGS = [['all', 'All seats'], ['outlet', 'Outlet'], ['window', 'Window']];
  const TABS = [['home', '#/', 'Explore'], ['saved', '#/saved', 'Saved'], ['about', '#/about', 'About']];

  // Place photos shipped with the app. A venue's own `photo` URL from the API wins if it has one.
  const PHOTOS = {
    'nestwork-msheireb': 'assets/places/nestwork',
    qnl: 'assets/places/qnl',
    'qu-library': 'assets/places/qu-library',
  };
  const photoOf = v => (v.photo ? { full: v.photo, thumb: v.photo }
    : PHOTOS[v.venue_id] ? { full: `${PHOTOS[v.venue_id]}.jpg`, thumb: `${PHOTOS[v.venue_id]}-thumb.jpg` } : null);

  const params = new URLSearchParams(location.search);
  const app = document.getElementById('app');

  const state = {
    mock: false,      // true when there's no backend and data comes from mock.js
    online: true,     // false while the API can't be reached
    venues: null,     // GET api/venues
    venue: null,      // GET api/venues/{id} for the open place
    screen: 'home',   // 'home', 'saved', 'about' or 'place'
    venueId: null,
    cat: 'all',
    sort: 'near',
    query: '',
    seg: 'all',
    sel: null,        // seat_id of the chair whose sheet is open
    fcSel: null,      // index of the tapped bar in the forecast chart
    homeScroll: 0,
    fromList: false,
    saved: loadSaved(),
  };

  // ---------- Small helpers ----------

  const $ = sel => document.querySelector(sel);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fold = s => String(s ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const typeLabel = t => TYPES[t] || t;
  const kindLabel = v => `${typeLabel(v.type)}, ${v.area}`;
  const studyCount = v => v.counts?.usable_study_spaces ?? v.counts?.free ?? 0;
  const rawSeatState = s => s.seat_state || s.state || 'UNKNOWN';
  const seatState = s => ({ free: 'FREE', held: 'HELD', taken: 'OCCUPIED', checking: 'UNKNOWN', unknown: 'UNKNOWN' })[s.status]
    || ({ UNAVAILABLE: 'OCCUPIED', REVIEW_REQUIRED: 'HELD' })[rawSeatState(s)] || rawSeatState(s);
  const studyAvailable = s => s.usable_for_studying === undefined
    ? seatState(s) === 'FREE' : s.usable_for_studying === true;
  const availabilityGroup = s => {
    if (studyAvailable(s)) return 'available';
    const key = seatState(s);
    if (key === 'HELD' || s.availability_reason === 'workspace_blocked') return 'held';
    if (key === 'OCCUPIED' || ['seat_unavailable', 'table_unavailable'].includes(s.availability_reason)) return 'taken';
    return 'checking';
  };
  const sourceLabel = source => ({ live: 'Live camera', recorded: 'Recorded demo', simulated: 'Simulated' }[source] || 'Availability demo');
  function seatLabel(s) {
    const group = availabilityGroup(s);
    if (group === 'available') return 'Available for studying';
    if (group === 'held') return rawSeatState(s) === 'REVIEW_REQUIRED' ? 'Held / staff review' : 'Held by belongings';
    if (group === 'taken') return 'Taken';
    return ({
      OCCUPIED: 'Taken', UNKNOWN: 'Checking',
    })[seatState(s)] || ({
      seat_not_linked_to_table: 'Not mapped to a table',
      camera_calibration_incomplete: 'Desk area not calibrated',
      chair_not_visible: 'Chair not verified',
      workspace_uncertain: 'Desk area needs checking',
      workspace_blocked: 'Desk area blocked',
      table_unavailable: 'Table unavailable',
      private_table_in_use_or_unverified: 'Private table needs checking',
      detection_confidence_too_low: 'Detection needs checking',
    })[s.availability_reason] || 'Not verified for studying';
  }
  function filteredStudyCount(v, matches) {
    if (state.seg === 'all') return studyCount(v);
    if (!v.tables) return v.seats.filter(s => matches(s) && studyAvailable(s)).length;
    return v.tables.reduce((n, table) => {
      const seats = v.seats.filter(s => table.seat_ids.includes(s.seat_id) && matches(s));
      if (!seats.length || !table.usable_for_studying) return n;
      if (table.table_type === 'private' || !table.is_shareable) return n + (table.usable_study_spaces ? 1 : 0);
      return n + seats.filter(studyAvailable).length;
    }, 0);
  }
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const clock = iso => new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Qatar' });

  // "About 6 likely free when you arrive", from the API's forecast at the venue's drive time.
  function arrivalLine(v) {
    const a = v.forecast && v.forecast.arrival;
    if (!a || !v.drive_minutes) return '';
    return a.expected_free > 0 ? `About ${a.expected_free} likely free when you arrive` : 'Likely full when you arrive';
  }

  function heldFor(since) {
    const ms = Date.now() - Date.parse(since);
    if (!Number.isFinite(ms) || ms < 60000) return 'under a minute';
    const m = Math.floor(ms / 60000);
    return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
  }

  function greeting() {
    const h = new Date().getHours();
    return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
  }

  // Replace an element's HTML only when it changed, keeping its sideways scroll position.
  function setHTML(el, html) {
    if (!el || el._html === html) return;
    const x = el.scrollLeft;
    el.innerHTML = html;
    el._html = html;
    el.scrollLeft = x;
  }

  // Saved places live in this browser only.
  function loadSaved() {
    try { return new Set(JSON.parse(localStorage.getItem(SAVED_KEY) || '[]')); } catch { return new Set(); }
  }
  function storeSaved() {
    try { localStorage.setItem(SAVED_KEY, JSON.stringify([...state.saved])); } catch { /* private mode: keep in memory */ }
  }

  // ---------- Icons ----------

  const svg = (w, h, vb, body, extra = '') =>
    `<svg width="${w}" height="${h}" viewBox="${vb}" fill="none" aria-hidden="true" focusable="false" ${extra}>${body}</svg>`;
  const line = (width = 2) => `stroke="currentColor" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round"`;

  const TYPE_ICON = {
    all: '<rect x="3" y="3" width="8" height="8" rx="2.5"/><rect x="15" y="3" width="8" height="8" rx="2.5"/><rect x="3" y="15" width="8" height="8" rx="2.5"/><rect x="15" y="15" width="8" height="8" rx="2.5"/>',
    library: '<path d="M13 5.5C10.2 3.2 6.5 2.7 2.8 3.2V20c3.7-.5 7.4 0 10.2 2.3 2.8-2.3 6.5-2.8 10.2-2.3V3.2C19.5 2.7 15.8 3.2 13 5.5Z"/><path d="M13 5.5v16.8"/>',
    cafe: '<path d="M3.5 9h14v6a6 6 0 0 1-6 6h-2a6 6 0 0 1-6-6V9Z"/><path d="M17.5 11h1.8a2.8 2.8 0 0 1 0 5.6h-2.2"/><path d="M8 2.5v3M12.5 2.5v3"/>',
    cowork: '<rect x="4.5" y="4" width="17" height="11.5" rx="2"/><path d="M1.5 19.5h23"/>',
    study_room: '<path d="M7 3v9h12"/><path d="M7 12v10M19 12v10"/><path d="M7 16.5h12"/>',
  };
  const typeIcon = (type, size = 26) => svg(size, size, '0 0 26 26', TYPE_ICON[type] || TYPE_ICON.all, line(2.1));

  const ICON = {
    search: () => svg(22, 22, '0 0 20 20', '<circle cx="8.5" cy="8.5" r="6"/><path d="M13 13l4.5 4.5"/>', line(2)),
    chevron: () => svg(14, 9, '0 0 14 9', '<path d="M1.5 1.5L7 7l5.5-5.5"/>', line(2.4)),
    pin: () => svg(15, 15, '0 0 24 24', '<path d="M12 21s-6.5-5.6-6.5-10.5a6.5 6.5 0 0 1 13 0C18.5 15.4 12 21 12 21Z"/><circle cx="12" cy="10.5" r="2.3"/>', line(2)),
    car: () => svg(16, 16, '0 0 24 24', '<path d="M5 12l1.6-4.4A2 2 0 0 1 8.5 6.3h7a2 2 0 0 1 1.9 1.3L19 12"/><path d="M4 12h16a1 1 0 0 1 1 1v4H3v-4a1 1 0 0 1 1-1Z"/><path d="M6 17v1.5M18 17v1.5"/><path d="M7 14.5h1M16 14.5h1"/>', line(1.9)),
    clock: () => svg(15, 15, '0 0 24 24', '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>', line(2)),
    back: () => svg(11, 18, '0 0 12 20', '<path d="M10 2L2 10l8 8"/>', line(2.6)),
    close: () => svg(11, 11, '0 0 12 12', '<path d="M1 1l10 10M11 1L1 11"/>', line(2.2)),
    entrance: () => svg(10, 10, '0 0 10 10', '<path d="M5 9V1M1.5 4.5L5 1l3.5 3.5"/>', line(1.6)),
    heart: () => svg(20, 20, '0 0 24 24', '<path d="M12 20.5s-7.5-4.6-9.2-9.6C1.6 7.3 3.9 4 7.4 4c2 0 3.6 1.1 4.6 2.7C13 5.1 14.6 4 16.6 4c3.5 0 5.8 3.3 4.6 6.9-1.7 5-9.2 9.6-9.2 9.6Z"/>', line(2)),
    explore: () => svg(24, 24, '0 0 24 24', '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5 5-2Z"/>', line(2)),
    trend: () => svg(16, 16, '0 0 24 24', '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>', line(2.2)),
    info: () => svg(24, 24, '0 0 24 24', '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5"/><path d="M12 7.6v.1"/>', line(2.2)),
  };

  // ---------- API ----------

  async function get(path) {
    if (state.mock) {
      const m = path.match(/^api\/venues(?:\/(.+))?$/);
      return m && m[1] ? window.BirdieMock.venue(decodeURIComponent(m[1])) : window.BirdieMock.venues();
    }
    const res = await fetch(path, { cache: 'no-store', headers: { Accept: 'application/json' } });
    const isJson = (res.headers.get('content-type') || '').includes('json');
    if (!res.ok || !isJson) {
      throw Object.assign(new Error(`${path}: HTTP ${res.status}`), { status: res.status, notJson: res.ok && !isJson });
    }
    return res.json();
  }

  // A small pill at the top while the API can't be reached.
  function setOnline(on) {
    state.online = on;
    let el = document.getElementById('offline');
    if (!el) {
      el = document.createElement('div');
      el.id = 'offline';
      el.className = 'offline';
      el.setAttribute('role', 'status');
      el.textContent = 'Reconnecting…';
      document.body.appendChild(el);
    }
    el.hidden = on;
  }

  // ---------- Polling ----------

  let timer = null;
  let gen = 0;

  async function refresh() {
    try {
      if (state.screen === 'place' && state.venueId) {
        const id = state.venueId;
        const v = await get(`api/venues/${encodeURIComponent(id)}`);
        if (state.screen !== 'place' || state.venueId !== id) return;
        const rebuild = !state.venue || state.venue.venue_id !== id || !$('#plan') || layoutKey(state.venue) !== layoutKey(v);
        state.venue = v;
        if (rebuild) renderPlace(); else updatePlace();
      } else {
        state.venues = await get('api/venues');
        if (state.screen === 'home') updateHome();
        if (state.screen === 'saved') updateSaved();
      }
      setOnline(true);
    } catch (err) {
      if (err.status === 404 && state.screen === 'place') { location.hash = ''; return; }
      setOnline(false);
    }
  }

  async function loop(g) {
    if (g !== gen) return;
    if (!document.hidden) await refresh();
    if (g !== gen) return;
    timer = setTimeout(() => loop(g), POLL_MS);
  }

  // Refresh now and restart the 2-second cycle.
  function kick() {
    clearTimeout(timer);
    gen += 1;
    loop(gen);
  }

  document.addEventListener('visibilitychange', () => { if (!document.hidden) kick(); });

  // ---------- Shared pieces ----------

  function dotsHTML(counts, { max, cols }) {
    const total = counts.total || 0;
    let n = total;
    let free = counts.free;
    let held = counts.held_or_review ?? counts.held;
    if (total > max) {
      const k = max / total;
      n = max;
      free = Math.round(counts.free * k);
      held = Math.round((counts.held_or_review ?? counts.held) * k);
      if (counts.free > 0 && free === 0) free = 1;
      if (free + held > n) held = n - free;
    }
    const taken = Math.max(0, n - free - held);
    const style = cols ? ` style="grid-template-columns:repeat(${cols},1fr)"` : '';
    return `<span class="dots"${style} aria-hidden="true">` +
      '<i class="d-free"></i>'.repeat(free) + '<i class="d-held"></i>'.repeat(held) + '<i></i>'.repeat(taken) +
      '</span>';
  }

  const thumb = v => {
    const photo = photoOf(v);
    if (photo) return `<span class="thumb is-photo"><img src="${esc(photo.thumb)}" alt="" loading="lazy" decoding="async"></span>`;
    const n = Math.min(v.counts.total || 0, 64);
    return `<span class="thumb">${dotsHTML({ ...v.counts, free: studyCount(v) }, { max: 64, cols: Math.max(1, Math.ceil(Math.sqrt(n))) })}</span>`;
  };

  const distance = (v, long = false) => (v.drive_minutes === 0
    ? `<span class="fact">${ICON.pin()}You're here</span>`
    : `<span class="fact">${ICON.car()}${v.drive_minutes} min${long ? ' drive' : ''}</span>`);

  function row(v) {
    const spaces = studyCount(v);
    const full = spaces === 0;
    return `
      <button class="row press${full ? ' is-full' : ''}" data-act="open" data-v="${esc(v.venue_id)}">
        ${thumb(v)}
        <span class="row-body">
          <span class="row-name">${esc(v.name)}</span>
          <span class="row-kind">${esc(kindLabel(v))} · ${esc(sourceLabel(v.source))}</span>
          <span class="row-facts">
            <span class="row-free">${full ? 'No verified study spaces' : `${spaces} verified study ${spaces === 1 ? 'space' : 'spaces'}`}</span>
            ${distance(v)}
          </span>
          <span class="row-kind">${v.counts.total || 0} mapped seats</span>
        </span>
      </button>`;
  }

  const tabbar = active => `
    <nav class="tabbar" aria-label="Main">
      ${TABS.map(([k, href, label]) => `
        <a class="tab${k === active ? ' is-on' : ''}" href="${href}"${k === active ? ' aria-current="page"' : ''}>
          ${k === 'home' ? ICON.explore() : k === 'saved' ? ICON.heart() : ICON.info()}<span>${label}</span>
        </a>`).join('')}
    </nav>`;

  // ---------- Explore ----------

  function showTab(tab) {
    const wasHome = state.screen === 'home';
    state.screen = tab;
    state.venueId = null;
    state.sel = null;
    state.fromList = false;
    removeSheet(false);
    if (tab === 'home') { renderHome(); window.scrollTo(0, wasHome ? window.scrollY : state.homeScroll); }
    else { (tab === 'saved' ? renderSaved : renderAbout)(); window.scrollTo(0, 0); }
    kick();
  }

  function renderHome() {
    app.innerHTML = `
      <main class="screen home">
        <header class="band">
          <p class="loc">Seats near <b>Msheireb</b> ${ICON.chevron()}</p>
          <label class="search">
            ${ICON.search()}
            <input id="q" type="search" placeholder="Search libraries, cafés, coworks" aria-label="Search places"
              autocomplete="off" autocapitalize="off" spellcheck="false" enterkeyhint="search">
          </label>
        </header>
        <nav class="rail tiles" id="tiles" aria-label="Kinds of place"></nav>
        <section class="intro" id="intro">
          <h1 class="hello"><span>${greeting()},</span> where are you studying?</h1>
          <div id="best"></div>
        </section>
        <section class="free-now" id="freeNow" hidden>
          <div class="sec-head"><h2>Verified study spaces</h2></div>
          <div class="rail cards" id="cards"></div>
        </section>
        <section class="list">
          <div class="sec-head"><h2 id="listTitle">All places</h2></div>
          <div class="sorts" id="sorts" role="group" aria-label="Sort places"></div>
          <div class="rows" id="rows"></div>
        </section>
        <p class="note" id="note"></p>
      </main>
      ${tabbar('home')}`;
    const q = $('#q');
    q.value = state.query;
    q.addEventListener('input', () => { state.query = q.value; updateHome(); });
    q.addEventListener('keydown', e => { if (e.key === 'Enter') q.blur(); });
    updateHome();
    setOnline(state.online);
  }

  // Rank by verified usable study spaces, not empty chairs.
  function bestBet(venues) {
    const open = venues.filter(v => studyCount(v) > 0);
    if (!open.length) return null;
    return open.reduce((a, b) => (studyCount(b) / (b.drive_minutes + 10) > studyCount(a) / (a.drive_minutes + 10) ? b : a));
  }

  function updateHome() {
    if (state.screen !== 'home' || !$('#rows')) return;
    const venues = state.venues || [];
    const loaded = !!state.venues;

    const present = new Set(venues.map(v => v.type));
    const cats = CATS.filter(([k]) => k === 'all' || present.has(k));
    if (!cats.some(([k]) => k === state.cat)) state.cat = 'all';
    const inCat = (v, cat = state.cat) => cat === 'all' || v.type === cat;
    setHTML($('#tiles'), cats.map(([k, label]) => {
      const on = k === state.cat;
      const free = venues.filter(v => inCat(v, k)).reduce((n, v) => n + studyCount(v), 0);
      const badge = loaded ? `<span class="tile-badge">${free ? `${free} available` : 'None verified'}</span>` : '';
      return `<button class="tile press${on ? ' is-on' : ''}" data-act="cat" data-v="${k}" aria-pressed="${on}">
        ${badge}${typeIcon(k, 34)}<span class="tile-label">${label}</span></button>`;
    }).join(''));

    const q = fold(state.query.trim());
    const pool = venues.filter(v => inCat(v));

    const best = bestBet(pool);
    $('#intro').hidden = !best || q !== '';
    setHTML($('#best'), best ? `
      <article class="best">
        <div class="best-head">
          <span class="best-icon">${typeIcon(best.type, 22)}</span>
          <span class="best-name">${esc(best.name)}<small>${esc(kindLabel(best))}</small></span>
        </div>
        <div class="best-body">
          ${thumb(best)}
          <div class="best-text">
            <strong>${plural(studyCount(best), 'study space', 'study spaces')}</strong>
            ${distance(best, true)}
            ${arrivalLine(best) ? `<span class="best-eta">${ICON.trend()}${esc(arrivalLine(best))}</span>` : ''}
          </div>
          <button class="btn press" data-act="open" data-v="${esc(best.venue_id)}">See seats</button>
        </div>
      </article>` : '');

    const featured = pool.filter(v => studyCount(v) > 0).sort((a, b) => studyCount(b) - studyCount(a)).slice(0, 5);
    $('#freeNow').hidden = featured.length === 0 || q !== '';
    setHTML($('#cards'), featured.map(v => `
      <button class="card press" data-act="open" data-v="${esc(v.venue_id)}" aria-label="${esc(v.name)}, ${studyCount(v)} verified study spaces">
        ${photoOf(v) ? `<span class="card-photo"><img src="${esc(photoOf(v).thumb)}" alt="" loading="lazy" decoding="async"></span>` : dotsHTML({ ...v.counts, free: studyCount(v) }, { max: 36 })}
        <span class="card-count">${studyCount(v)}<span>spaces</span></span>
        <span class="card-name">${esc(v.name)}</span>
        <span class="card-foot">${distance(v)}</span>
      </button>`).join(''));

    let list = pool.filter(v => !q || fold(`${v.name} ${v.area} ${typeLabel(v.type)} ${v.type}`).includes(q));
    if (state.sort === 'late') list = list.filter(v => v.open_late);
    list.sort(state.sort === 'free'
      ? (a, b) => studyCount(b) - studyCount(a) || a.drive_minutes - b.drive_minutes
      : (a, b) => a.drive_minutes - b.drive_minutes);

    $('#listTitle').textContent = q ? 'Results' : state.cat === 'all' ? 'All places' : CATS.find(c => c[0] === state.cat)[1];
    setHTML($('#sorts'), SORTS.map(([k, label]) => {
      const on = k === state.sort;
      return `<button class="sort press${on ? ' is-on' : ''}" data-act="sort" data-v="${k}" aria-pressed="${on}">${label}</button>`;
    }).join(''));

    let rows;
    if (!loaded) rows = `<p class="empty">${state.online ? 'Loading places…' : 'Can’t reach Birdie. Trying again…'}</p>`;
    else if (!list.length) rows = `<p class="empty">${q ? 'No places match that search.' : 'Nothing open late in this category.'}</p>`;
    else rows = list.map(row).join('');
    setHTML($('#rows'), rows);
    $('#note').textContent = state.mock ? 'Demo data: no backend connected' : '';
  }

  // ---------- Saved ----------

  function renderSaved() {
    app.innerHTML = `
      <main class="screen">
        <header class="band band-title">
          <h1>Saved places</h1>
          <p>Your usual spots, with live seats.</p>
        </header>
        <section class="list"><div class="rows" id="rows"></div></section>
      </main>
      ${tabbar('saved')}`;
    updateSaved();
  }

  function updateSaved() {
    if (state.screen !== 'saved' || !$('#rows')) return;
    const list = (state.venues || []).filter(v => state.saved.has(v.venue_id)).sort((a, b) => a.drive_minutes - b.drive_minutes);
    setHTML($('#rows'), !state.venues
      ? '<p class="empty">Loading places…</p>'
      : list.length ? list.map(row).join('')
        : '<p class="empty"><strong>No saved places yet</strong>Tap the heart on a place to keep it here.</p>');
  }

  // ---------- About ----------

  function renderAbout() {
    app.innerHTML = `
      <main class="screen">
        <header class="band band-title">
          <h1>How Birdie works</h1>
          <p>Know there's a seat before you drive.</p>
        </header>
        <div class="about">
          <section>
            <h2>From camera to your phone</h2>
            <ol class="steps">
              <li><b>1</b><span>A venue camera or recorded demo clip is checked frame by frame.</span></li>
              <li><b>2</b><span>A vision model checks people and belongings against the configured seat and desk areas.</span></li>
              <li><b>3</b><span>Birdie counts a study space only when the seat and its workspace are verified usable.</span></li>
            </ol>
          </section>
          <section>
            <h2>What the colours mean</h2>
            <div class="states">
              <div class="state"><i class="sw-free"></i><div><strong>Free</strong><span>Nobody there and nothing on it.</span></div></div>
              <div class="state"><i class="sw-taken"></i><div><strong>Taken</strong><span>Someone is sitting there, or just stepped away.</span></div></div>
              <div class="state"><i class="sw-held"></i><div><strong>Held by a bag</strong><span>Things left on the seat with nobody there for a long time.</span></div></div>
              <div class="state"><i class="sw-checking"></i><div><strong>Checking</strong><span>Unclear evidence is not counted as available.</span></div></div>
            </div>
          </section>
          <section class="panel">
            <h2>Your privacy</h2>
            <p>Birdie detects people and belongings at configured seats; it does not identify people. This demo shows seat states from a recorded clip or simulated venue data.</p>
          </section>
          <section>
            <h2>Where does this demo data come from?</h2>
            <p>Nestwork Msheireb uses a recorded camera clip in this demo. The other listed venues are simulated and are not live availability feeds.</p>
          </section>
        </div>
      </main>
      ${tabbar('about')}`;
  }

  // ---------- Place ----------

  let chairEls = new Map();
  let tableNames = new Map();
  let lastStatus = new Map();

  // Changes when the floor plan or the set of seats changes, so the plan is rebuilt.
  const layoutKey = v => JSON.stringify([v.floor_plan, v.seats.map(s => [s.seat_id, s.plan_x, s.plan_y, s.plan_rot])]);

  function placeBand(v) {
    const saved = state.saved.has(v.venue_id);
    const photo = photoOf(v);
    const facts = distance(v, true) + (v.open_until ? `<span class="fact">${ICON.clock()}${esc(v.open_until)}</span>` : '');
    const chips = (v.amenities || []).map(a => `<span class="chip">${esc(a)}</span>`).join('');
    const buttons = `
        <div class="place-top">
          <button class="round-btn press" data-act="back" aria-label="Back">${ICON.back()}</button>
          <button class="round-btn press" data-act="save" data-v="${esc(v.venue_id)}" aria-pressed="${saved}" aria-label="Save place">${ICON.heart()}</button>
        </div>`;
    return `
      ${photo ? `<div class="hero"><img src="${esc(photo.full)}" alt="">${buttons}</div>` : ''}
      <header class="band${photo ? ' under-hero' : ''}">
        ${photo ? '' : buttons}
        <div class="place-head">
          <h1>${esc(v.name)}</h1>
          <span class="place-kind">${esc(kindLabel(v))} · ${esc(sourceLabel(v.source))}</span>
          <div class="place-facts">${facts}</div>
          ${chips ? `<div class="chips">${chips}</div>` : ''}
        </div>
      </header>`;
  }

  function openPlace(id) {
    const cached = state.venue && state.venue.venue_id === id;
    if (state.screen === 'home') state.homeScroll = window.scrollY;
    state.screen = 'place';
    state.venueId = id;
    state.seg = 'all';
    state.sel = null;
    removeSheet(false);
    if (cached) renderPlace();
    else {
      state.venue = null;
      const summary = (state.venues || []).find(v => v.venue_id === id);
      app.innerHTML = summary
        ? `<main class="place">${placeBand(summary)}<p class="empty">Loading seats…</p></main>`
        : '<p class="loading">Loading…</p>';
      setOnline(state.online);
    }
    window.scrollTo(0, 0);
    kick();
  }

  function renderPlace() {
    const v = state.venue;
    const plan = v.floor_plan;
    tableNames = new Map((plan.tables || []).map(t => [t.table_id, t.name]));
    lastStatus = new Map();
    state.fcSel = null;

    app.innerHTML = `
      <main class="place" id="place">
        ${placeBand(v)}
        <div class="place-body">
          <div class="count">
            <h2 id="headline"></h2>
            <p id="breakdown"></p>
            <p class="eta" id="eta" hidden></p>
          </div>
          <div class="seg" id="seg" role="group" aria-label="Filter seats">
            ${SEGS.map(([k, label]) => `<button data-act="seg" data-v="${k}">${label}</button>`).join('')}
          </div>
          <div class="plan-wrap" id="planWrap">
            <div class="plan" id="plan" style="width:${plan.width}px;height:${plan.height}px">
              ${plan.window_top ? '<div class="window-strip"></div>' : ''}
              ${(plan.fixtures || []).map(fixtureHTML).join('')}
              ${(plan.tables || []).map(tableHTML).join('')}
              ${v.seats.map(chairHTML).join('')}
              <div class="entrance">${ICON.entrance()}Entrance</div>
            </div>
          </div>
          <div class="legend">
            <span><i class="sw-free"></i>Available for study</span>
            <span><i class="sw-taken"></i>Taken</span>
            <span><i class="sw-held"></i>Held / staff review</span>
            <span><i class="sw-checking"></i>Checking</span>
          </div>
          <section class="fc" id="fc" hidden aria-labelledby="fcTitle">
            <div class="fc-head"><h3 id="fcTitle">Next 3 hours</h3><span>Forecast</span></div>
            <p class="fc-cap" id="fcCap" aria-live="polite"></p>
            <div class="fc-chart" id="fcChart" role="group" aria-label="Likely free study spaces, every 30 minutes"></div>
          </section>
        </div>
      </main>`;

    chairEls = new Map([...app.querySelectorAll('.chair')].map(el => [el.dataset.v, el]));
    fitPlan();
    updatePlace();
    setOnline(state.online);
  }

  const px = n => `${Math.round(n * 10) / 10}px`;

  const fixtureHTML = f =>
    `<div class="fixture" style="left:${px(f.x)};top:${px(f.y)};width:${px(f.w)};height:${px(f.h)}">${esc(f.label)}</div>`;

  function tableHTML(t) {
    if (t.shape === 'round') {
      return `<div class="table" style="left:${px(t.cx - t.r)};top:${px(t.cy - t.r)};width:${px(2 * t.r)};height:${px(2 * t.r)};border-radius:999px">${esc(t.table_id)}</div>`;
    }
    const thin = t.h < 24;
    return `<div class="table" style="left:${px(t.x)};top:${px(t.y)};width:${px(t.w)};height:${px(t.h)};border-radius:${thin ? 6 : 10}px">${thin ? '' : esc(t.table_id)}</div>`;
  }

  const chairHTML = s =>
    `<button class="chair" data-act="chair" data-v="${esc(s.seat_id)}" style="left:${px(s.plan_x - 17)};top:${px(s.plan_y - 17)};transform:rotate(${s.plan_rot}deg)">` +
    '<span class="chair-in"><span class="chair-back"></span><span class="chair-seat"></span></span></button>';

  // Fit the plan to the screen width (it is drawn on a 362-point grid).
  function fitPlan() {
    const wrap = $('#planWrap');
    const plan = $('#plan');
    if (!wrap || !plan || !state.venue) return;
    const { width, height } = state.venue.floor_plan;
    const k = Math.min(1.2, wrap.clientWidth / width);
    plan.style.transform = k !== 1 ? `scale(${k})` : '';
    wrap.style.height = `${height * k}px`;
  }
  window.addEventListener('resize', fitPlan);

  const matchesSeg = s => state.seg === 'all' || (state.seg === 'outlet' && s.has_outlet) || (state.seg === 'window' && s.has_window);

  function updatePlace() {
    if (state.screen !== 'place' || !state.venue || !$('#plan')) return;
    const v = state.venue;
    const counts = { available: 0, held: 0, taken: 0, checking: 0 };
    const freeMatching = filteredStudyCount(v, matchesSeg);

    // Drop the selection when that seat was taken meanwhile or is hidden by the filter.
    const sel = state.sel && v.seats.find(x => x.seat_id === state.sel);
    if (!sel || !matchesSeg(sel)) state.sel = null;

    v.seats.forEach(s => {
      const el = chairEls.get(s.seat_id);
      if (!el) return;
      const ok = matchesSeg(s);
      const display = availabilityGroup(s);
      counts[display] += 1;
      const tappable = ok;
      const changed = lastStatus.has(s.seat_id) && lastStatus.get(s.seat_id) !== display;
      lastStatus.set(s.seat_id, display);

      el.className = 'chair' +
        (display === 'available' ? ' is-free' : display === 'held' ? ' is-held' : display === 'checking' ? ' is-checking' : '') +
        (ok ? '' : ' is-dim') +
        (state.sel === s.seat_id ? ' is-sel' : '');
      if (changed && ok) {
        void el.offsetWidth; // restart the ring animation
        el.classList.add('is-changed');
      }
      el.setAttribute('aria-label', `Seat ${s.seat_id}, ${seatLabel(s)}`);
      el.setAttribute('aria-disabled', String(!tappable));
    });

    $('#headline').textContent = freeMatching > 0
      ? plural(freeMatching, 'verified study space', 'verified study spaces')
      : 'No verified study spaces right now';
    const unmapped = v.counts?.unmapped_seats ?? 0;
    $('#breakdown').textContent = `${counts.taken} taken · ${counts.held} held or review · ${counts.checking} checking` +
      (unmapped ? ` · ${unmapped} seats await calibration` : '');

    document.querySelectorAll('#seg button').forEach(b => {
      const on = b.dataset.v === state.seg;
      b.classList.toggle('is-on', on);
      b.setAttribute('aria-pressed', String(on));
    });

    updateForecast(v);
    updateSheet();
  }

  // The forecast: one line under the headline, and a bar per 30 minutes for the next 3 hours.
  function updateForecast(v) {
    const f = v.forecast;
    const steps = (f && f.timeline) || [];
    const eta = $('#eta');
    const box = $('#fc');
    if (!eta || !box) return;

    let line = '';
    if (f && f.arrival && v.drive_minutes) {
      const a = f.arrival;
      line = a.expected_free > 0
        ? `<b>About ${a.expected_free}</b> likely free when you arrive in ${v.drive_minutes}&nbsp;min`
        : `<b>Likely full</b> when you arrive in ${v.drive_minutes}&nbsp;min`;
    } else if (steps.length > 2) {
      const change = steps[2].expected_free - steps[0].expected_free;
      const big = Math.max(2, Math.round((v.counts?.total || 0) * 0.1));
      line = change <= -big ? '<b>Filling up</b> over the next hour'
        : change >= big ? '<b>Freeing up</b> over the next hour' : '<b>About the same</b> for the next hour';
    }
    eta.hidden = !line;
    setHTML(eta, line ? `${ICON.trend()}<span>${line}</span>` : '');

    box.hidden = steps.length === 0;
    if (!steps.length) return;
    // Default to the bar closest to when you'd arrive.
    const near = Math.min(steps.length - 1, Math.round((v.drive_minutes || 0) / 30));
    const sel = state.fcSel ?? near;
    const max = Math.max(1, ...steps.map(p => p.expected_free));
    const label = (q, i) => (i === 0 ? 'Now' : q.minutes < 60 ? `${q.minutes}m` : `${Math.floor(q.minutes / 60)}h${q.minutes % 60 ? '30' : ''}`);
    const p = steps[sel];
    $('#fcCap').innerHTML = `<b>${sel === 0 ? 'Now' : clock(p.at)}</b> · ${sel === 0
      ? plural(p.expected_free, 'verified study space', 'verified study spaces')
      : p.expected_free > 0 ? `about ${p.expected_free} likely free (${p.low} to ${p.high})` : 'likely full'}`;
    setHTML($('#fcChart'), steps.map((q, i) => `
      <button class="fc-bar${i === sel ? ' is-sel' : ''}${i === 0 ? ' is-now' : ''}" data-act="fc" data-v="${i}"
        aria-pressed="${i === sel}" aria-label="${i === 0 ? 'Now' : `At ${clock(q.at)}`}: about ${q.expected_free} free">
        <span class="fc-val">${q.expected_free}</span>
        <span class="fc-track"><span class="fc-col" style="height:${Math.max(3, (q.expected_free / max) * 100)}%"></span></span>
        <span class="fc-t">${esc(label(q, i))}</span>
      </button>`).join(''));
  }

  function onChair(id) {
    const s = state.venue && state.venue.seats.find(x => x.seat_id === id);
    if (!s || !matchesSeg(s)) return;
    state.sel = id;
    updatePlace();
  }

  function toggleSave(id, btn) {
    if (state.saved.has(id)) state.saved.delete(id); else state.saved.add(id);
    storeSaved();
    if (btn) btn.setAttribute('aria-pressed', String(state.saved.has(id)));
  }

  // ---------- Seat sheet ----------

  function removeSheet(animate) {
    const el = $('#sheet');
    const place = $('#place');
    if (place) place.classList.remove('has-sheet');
    if (!el) return;
    el.id = '';
    if (!animate) { el.remove(); return; }
    el.classList.add('is-closing');
    el.addEventListener('transitionend', () => el.remove(), { once: true });
    setTimeout(() => el.remove(), 320);
  }

  function updateSheet() {
    const s = state.sel && state.venue.seats.find(x => x.seat_id === state.sel);
    if (!s) { removeSheet(true); return; }

    let el = $('#sheet');
    if (!el) {
      el = document.createElement('div');
      el.id = 'sheet';
      el.className = 'sheet';
      el.setAttribute('role', 'dialog');
      document.body.appendChild(el);
      $('#place').classList.add('has-sheet');
    }
    const group = availabilityGroup(s);
    const held = group === 'held';
    const available = group === 'available';
    const table = tableNames.get(s.table_id) || `Table ${s.table_id}`;
    const chips = [];
    if (s.table_id) chips.push(table);
    if (s.has_window) chips.push('By the window');
    if (s.has_outlet) chips.push('Outlet');
    el.setAttribute('aria-label', `Seat ${s.seat_id}`);

    setHTML(el, `
      <div class="sheet-handle"></div>
      <div class="sheet-row">
        <div class="sheet-tile ${available ? 'is-free' : held ? 'is-held' : group === 'checking' ? 'is-checking' : ''}">${esc(s.seat_id)}</div>
        <div class="sheet-text">
          <span class="sheet-title">${esc(seatLabel(s))}</span>
          <span class="sheet-sub">${held && s.since ? `Held for ${esc(heldFor(s.since))}` : esc(s.availability_reason || table)}</span>
          ${chips.length ? `<div class="sheet-chips">${chips.map(c => `<span>${esc(c)}</span>`).join('')}</div>` : ''}
        </div>
        <button class="sheet-close" data-act="close" aria-label="Close"><span>${ICON.close()}</span></button>
      </div>`);
  }

  // ---------- Splash ----------

  function splash() {
    const el = document.createElement('div');
    el.className = 'splash';
    el.setAttribute('role', 'presentation');
    el.innerHTML = '<img src="assets/logo-512.jpg" alt="" width="120" height="120">' +
      '<span class="splash-word">Birdie</span><span class="splash-line">Verified study spaces in Doha</span>';
    document.body.appendChild(el);
    const timers = [
      setTimeout(() => el.classList.add('is-in'), 40),
      setTimeout(() => el.classList.add('is-out'), 1400),
      setTimeout(done, 1700),
    ];
    function done() {
      timers.forEach(clearTimeout);
      el.remove();
    }
    el.addEventListener('click', done);
  }

  // ---------- Routing and events ----------

  function route() {
    const h = location.hash;
    const m = h.match(/^#\/place\/(.+)$/);
    if (m) openPlace(decodeURIComponent(m[1]));
    else if (h === '#/saved') showTab('saved');
    else if (h === '#/about') showTab('about');
    else showTab('home');
  }
  window.addEventListener('hashchange', route);

  document.addEventListener('click', e => {
    const t = e.target.closest('[data-act]');
    if (!t) return;
    const v = t.dataset.v;
    switch (t.dataset.act) {
      case 'cat': state.cat = v === state.cat ? 'all' : v; updateHome(); break;
      case 'sort': state.sort = v; updateHome(); break;
      case 'open':
        location.hash = `#/place/${encodeURIComponent(v)}`;
        state.fromList = true;
        break;
      case 'back':
        if (state.fromList) history.back();
        else location.hash = '';
        break;
      case 'save': toggleSave(v, t); break;
      case 'seg': state.seg = v; state.sel = null; updatePlace(); break;
      case 'chair': onChair(v); break;
      case 'close': state.sel = null; updatePlace(); break;
      case 'fc': state.fcSel = Number(v); if (state.venue) updateForecast(state.venue); break;
      default: break;
    }
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && state.sel) { state.sel = null; updatePlace(); }
  });

  // ---------- Start ----------

  async function start() {
    if (!params.has('nosplash')) splash();
    state.mock = params.has('mock') || location.protocol === 'file:';
    if (!state.mock) {
      try {
        state.venues = await get('api/venues');
      } catch (err) {
        // No API on this server (404 or an HTML page): use the mock data. Network errors just retry.
        if (err.status === 404 || err.notJson) state.mock = true;
        else state.online = false;
      }
    }
    route();
  }

  start();
})();
