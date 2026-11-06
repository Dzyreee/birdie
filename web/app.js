/* Birdie mobile app: Splash, Browse and Place.
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
  const TYPES = { library: 'Library', cafe: 'Café', cowork: 'Coworking', study_room: 'Study room' };
  const CATS = [['all', 'All'], ['library', 'Libraries'], ['cafe', 'Cafés'], ['cowork', 'Coworking'], ['study_room', 'Study rooms']];
  const SORTS = [['near', 'Nearest'], ['free', 'Most seats free'], ['late', 'Open late']];
  const SEGS = [['all', 'All seats'], ['outlet', 'Outlet'], ['window', 'Window']];
  const LOGO = 'assets/logo-512.jpg';

  const params = new URLSearchParams(location.search);
  const app = document.getElementById('app');

  const state = {
    mock: false,      // true when there's no backend and data comes from mock.js
    online: true,     // false while the API can't be reached
    venues: null,     // GET api/venues
    venue: null,      // GET api/venues/{id} for the open place
    screen: 'browse', // 'browse' or 'place'
    venueId: null,
    cat: 'all',
    sort: 'near',
    query: '',
    seg: 'all',
    sel: null,        // seat_id of the chair whose sheet is open
    browseScroll: 0,
    fromBrowse: false,
  };

  // ---------- Small helpers ----------

  const $ = sel => document.querySelector(sel);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fold = s => String(s ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const typeLabel = t => TYPES[t] || t;
  const kindLabel = v => `${typeLabel(v.type)}, ${v.area}`;
  const sourceLabel = s => s.charAt(0).toUpperCase() + s.slice(1);
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  function heldFor(since) {
    const ms = Date.now() - Date.parse(since);
    if (!Number.isFinite(ms) || ms < 60000) return 'under a minute';
    const m = Math.floor(ms / 60000);
    return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
  }

  // Replace an element's HTML only when it changed, keeping its sideways scroll position.
  function setHTML(el, html) {
    if (!el || el._html === html) return;
    const x = el.scrollLeft;
    el.innerHTML = html;
    el._html = html;
    el.scrollLeft = x;
  }

  // ---------- Icons ----------

  const svg = (w, h, vb, body, extra = '') =>
    `<svg width="${w}" height="${h}" viewBox="${vb}" fill="none" aria-hidden="true" focusable="false" ${extra}>${body}</svg>`;
  const line = (width = 2) => `stroke="currentColor" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round"`;

  const ICON = {
    all: () => svg(18, 18, '0 0 26 26',
      '<rect x="3" y="3" width="8" height="8" rx="2.5"/><rect x="15" y="3" width="8" height="8" rx="2.5"/><rect x="3" y="15" width="8" height="8" rx="2.5"/><rect x="15" y="15" width="8" height="8" rx="2.5"/>', line(2.4)),
    library: () => svg(18, 18, '0 0 28 26',
      '<path d="M14 6C11 3.5 7 3 3 3.5V21c4-.5 8 0 11 2.5C17 21 21 20.5 25 21V3.5C21 3 17 3.5 14 6Z"/><path d="M14 6v17"/>', line(2.4)),
    cafe: () => svg(18, 18, '0 0 28 26',
      '<path d="M4 9h15v6a6 6 0 0 1-6 6h-3a6 6 0 0 1-6-6V9Z"/><path d="M19 11h2a3 3 0 0 1 0 6h-2.5"/><path d="M9 2.5v3M13.5 2.5v3"/>', line(2.4)),
    cowork: () => svg(18, 18, '0 0 28 26',
      '<rect x="5" y="4" width="18" height="12" rx="2"/><path d="M2 20h24"/>', line(2.4)),
    study_room: () => svg(18, 18, '0 0 28 26',
      '<path d="M8 3.5v9h12"/><path d="M8 12.5v10M20 12.5v10"/><path d="M8 17h12"/>', line(2.4)),
    search: () => svg(18, 18, '0 0 20 20',
      '<circle cx="9" cy="9" r="6.5"/><path d="M14 14l4 4"/>', line(2)),
    pin: () => svg(15, 15, '0 0 24 24',
      '<path d="M12 21s-6.5-5.6-6.5-10.5a6.5 6.5 0 0 1 13 0C18.5 15.4 12 21 12 21Z"/><circle cx="12" cy="10.5" r="2.3"/>', line(2)),
    car: () => svg(16, 16, '0 0 24 24',
      '<path d="M5 12l1.6-4.4A2 2 0 0 1 8.5 6.3h7a2 2 0 0 1 1.9 1.3L19 12"/><path d="M4 12h16a1 1 0 0 1 1 1v4H3v-4a1 1 0 0 1 1-1Z"/><path d="M6 17v1.5M18 17v1.5"/><path d="M7 14.5h1M16 14.5h1"/>', line(1.9)),
    clock: () => svg(15, 15, '0 0 24 24',
      '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>', line(2)),
    back: () => svg(11, 18, '0 0 12 20',
      '<path d="M10 2L2 10l8 8"/>', line(2.6)),
    close: () => svg(11, 11, '0 0 12 12',
      '<path d="M1 1l10 10M11 1L1 11"/>', line(2.2)),
    entrance: () => svg(10, 10, '0 0 10 10',
      '<path d="M5 9V1M1.5 4.5L5 1l3.5 3.5"/>', line(1.6)),
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

  function setOnline(on) {
    state.online = on;
    document.querySelectorAll('[data-live]').forEach(el => {
      el.classList.toggle('is-offline', !on);
      el.querySelector('[data-live-text]').textContent = on ? 'Live' : 'Reconnecting…';
    });
  }

  const liveBadge = () => '<span class="live" data-live><i class="dot"></i><span data-live-text>Live</span></span>';

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
        const list = await get('api/venues');
        state.venues = list;
        if (state.screen === 'browse') updateBrowse();
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

  // ---------- Seat dots (one per seat: free, then held, then taken) ----------

  function dotsHTML(counts, { max, cols }) {
    const total = counts.total || 0;
    let n = total;
    let free = counts.free;
    let held = counts.held;
    if (total > max) {
      const k = max / total;
      n = max;
      free = Math.round(counts.free * k);
      held = Math.round(counts.held * k);
      if (counts.free > 0 && free === 0) free = 1;
      if (free + held > n) held = n - free;
    }
    const taken = Math.max(0, n - free - held);
    const style = cols ? ` style="grid-template-columns:repeat(${cols},1fr)"` : '';
    return `<span class="dots"${style} aria-hidden="true">` +
      '<i class="d-free"></i>'.repeat(free) + '<i class="d-held"></i>'.repeat(held) + '<i></i>'.repeat(taken) +
      '</span>';
  }

  const thumbDots = c => {
    const n = Math.min(c.total || 0, 64);
    return dotsHTML(c, { max: 64, cols: Math.max(1, Math.ceil(Math.sqrt(n))) });
  };

  const distance = v => (v.drive_minutes === 0
    ? `<span class="fact">${ICON.pin()}You're here</span>`
    : `<span class="fact">${ICON.car()}${v.drive_minutes} min</span>`);

  const simTag = v => (v.source === 'live' ? '' : `<span class="tag-sim">${esc(sourceLabel(v.source))}</span>`);

  // ---------- Browse ----------

  function showBrowse() {
    state.screen = 'browse';
    state.venueId = null;
    state.sel = null;
    state.fromBrowse = false;
    removeSheet(false);
    renderBrowse();
    window.scrollTo(0, state.browseScroll);
    kick();
  }

  function renderBrowse() {
    app.innerHTML = `
      <main class="browse">
        <header class="band">
          <div class="topbar">
            <div class="brand"><img src="${LOGO}" alt="" width="36" height="36"><span class="wordmark">Birdie</span></div>
            <span class="place-tag">${ICON.pin()}Msheireb</span>
          </div>
          <label class="search">
            ${ICON.search()}
            <input id="q" type="search" placeholder="Search libraries, cafés, coworks" aria-label="Search places"
              autocomplete="off" autocapitalize="off" spellcheck="false" enterkeyhint="search">
          </label>
          <nav class="rail cats" id="cats" aria-label="Kinds of place"></nav>
          <section class="free-now" id="freeNow" hidden>
            <div class="free-now-head"><h2>Free right now</h2>${liveBadge()}</div>
            <div class="rail cards" id="cards"></div>
          </section>
        </header>
        <section class="list">
          <div class="list-head">
            <h2 id="listTitle">All places</h2>
            <div class="sorts" id="sorts" role="group" aria-label="Sort places"></div>
          </div>
          <div class="rows" id="rows"></div>
        </section>
        <p class="note" id="note"></p>
      </main>`;
    const q = $('#q');
    q.value = state.query;
    q.addEventListener('input', () => { state.query = q.value; updateBrowse(); });
    q.addEventListener('keydown', e => { if (e.key === 'Enter') q.blur(); });
    updateBrowse();
    setOnline(state.online);
  }

  function updateBrowse() {
    if (state.screen !== 'browse' || !$('#rows')) return;
    const venues = state.venues || [];

    const present = new Set(venues.map(v => v.type));
    const cats = CATS.filter(([k]) => k === 'all' || present.has(k));
    if (!cats.some(([k]) => k === state.cat)) state.cat = 'all';
    setHTML($('#cats'), cats.map(([k, label]) => {
      const on = k === state.cat;
      return `<button class="cat press${on ? ' is-on' : ''}" data-act="cat" data-v="${k}" aria-pressed="${on}">${ICON[k]()}${label}</button>`;
    }).join(''));

    const q = fold(state.query.trim());
    const inCat = v => state.cat === 'all' || v.type === state.cat;

    const featured = venues.filter(v => inCat(v) && v.counts.free > 0)
      .sort((a, b) => b.counts.free - a.counts.free)
      .slice(0, 5);
    $('#freeNow').hidden = featured.length === 0 || q !== '';
    setHTML($('#cards'), featured.map(v => `
      <button class="card press" data-act="open" data-v="${esc(v.venue_id)}" aria-label="${esc(v.name)}, ${v.counts.free} free">
        ${dotsHTML(v.counts, { max: 36 })}
        <span class="card-count">${v.counts.free}<span>free</span></span>
        <span class="card-name">${esc(v.name)}</span>
        <span class="card-foot">${distance(v)}${simTag(v)}</span>
      </button>`).join(''));

    let list = venues.filter(v => inCat(v) && (!q || fold(`${v.name} ${v.area} ${typeLabel(v.type)} ${v.type}`).includes(q)));
    if (state.sort === 'late') list = list.filter(v => v.open_late);
    list.sort(state.sort === 'free'
      ? (a, b) => b.counts.free - a.counts.free || a.drive_minutes - b.drive_minutes
      : (a, b) => a.drive_minutes - b.drive_minutes);

    $('#listTitle').textContent = state.cat === 'all' ? 'All places' : CATS.find(c => c[0] === state.cat)[1];
    setHTML($('#sorts'), SORTS.map(([k, label]) => {
      const on = k === state.sort;
      return `<button class="sort press${on ? ' is-on' : ''}" data-act="sort" data-v="${k}" aria-pressed="${on}">${label}</button>`;
    }).join(''));

    let rows;
    if (!state.venues) rows = `<p class="empty">${state.online ? 'Loading places…' : 'Can’t reach Birdie. Trying again…'}</p>`;
    else if (!list.length) rows = `<p class="empty">${q ? 'No places match that search.' : 'No places open late in this category.'}</p>`;
    else rows = list.map(row).join('');
    setHTML($('#rows'), rows);
    $('#note').textContent = state.mock ? 'Demo data: no backend connected' : '';
  }

  function row(v) {
    const { free, total } = v.counts;
    const full = free === 0;
    return `
      <button class="row press${full ? ' is-full' : ''}" data-act="open" data-v="${esc(v.venue_id)}">
        <span class="thumb">${thumbDots(v.counts)}</span>
        <span class="row-body">
          <span class="row-name">${esc(v.name)}</span>
          <span class="row-kind">${esc(kindLabel(v))}</span>
          <span class="row-facts">
            <span class="row-free">${full ? 'Full right now' : `${free} of ${total} free`}</span>
            ${distance(v)}${simTag(v)}
          </span>
        </span>
      </button>`;
  }

  // ---------- Place ----------

  let chairEls = new Map();
  let tableNames = new Map();
  let lastStatus = new Map();

  // Changes when the floor plan or the set of seats changes, so the plan is rebuilt.
  const layoutKey = v => JSON.stringify([v.floor_plan, v.seats.map(s => [s.seat_id, s.plan_x, s.plan_y, s.plan_rot])]);

  function placeBand(v) {
    const facts = [
      v.drive_minutes === 0 ? `<span class="fact">${ICON.pin()}You're here</span>` : `<span class="fact">${ICON.car()}${v.drive_minutes} min drive</span>`,
      v.open_until ? `<span class="fact">${ICON.clock()}${esc(v.open_until)}</span>` : '',
    ].join('');
    const chips = (v.source === 'live' ? '' : `<span class="chip chip-sim">${esc(sourceLabel(v.source))}</span>`) +
      (v.amenities || []).map(a => `<span class="chip">${esc(a)}</span>`).join('');
    return `
      <header class="band">
        <div class="place-top">
          <button class="back press" data-act="back" aria-label="Back to places">${ICON.back()}</button>
          ${v.source === 'live' ? liveBadge() : ''}
        </div>
        <div class="place-head">
          <h1>${esc(v.name)}</h1>
          <span class="place-kind">${esc(kindLabel(v))}</span>
          <div class="place-facts">${facts}</div>
          ${chips ? `<div class="chips">${chips}</div>` : ''}
        </div>
      </header>`;
  }

  function openPlace(id) {
    const cached = state.venue && state.venue.venue_id === id;
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
    tableNames = new Map(plan.tables.map(t => [t.table_id, t.name]));
    lastStatus = new Map();

    app.innerHTML = `
      <main class="place" id="place">
        ${placeBand(v)}
        <div class="place-body">
          <div class="count">
            <h2 id="headline"></h2>
            <p id="breakdown"></p>
          </div>
          <div class="seg" id="seg" role="group" aria-label="Filter seats">
            ${SEGS.map(([k, label]) => `<button data-act="seg" data-v="${k}">${label}</button>`).join('')}
          </div>
          <div class="plan-wrap" id="planWrap">
            <div class="plan" id="plan" style="width:${plan.width}px;height:${plan.height}px">
              ${plan.window_top ? '<div class="window-strip"></div>' : ''}
              ${(plan.fixtures || []).map(fixtureHTML).join('')}
              ${plan.tables.map(tableHTML).join('')}
              ${v.seats.map(chairHTML).join('')}
              <div class="entrance">${ICON.entrance()}Entrance</div>
            </div>
          </div>
          <div class="legend">
            <span><i class="l-free"></i>Free</span>
            <span><i class="l-taken"></i>Taken</span>
            <span><i class="l-held"></i>Held by a bag</span>
          </div>
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
    const counts = { free: 0, held: 0, taken: 0 };
    let freeMatching = 0;

    // Drop the selection when that seat was taken meanwhile or is hidden by the filter.
    const sel = state.sel && v.seats.find(x => x.seat_id === state.sel);
    if (!sel || !matchesSeg(sel) || (sel.status !== 'free' && sel.status !== 'held')) state.sel = null;

    v.seats.forEach(s => {
      const el = chairEls.get(s.seat_id);
      if (!el) return;
      const ok = matchesSeg(s);
      counts[s.status] = (counts[s.status] || 0) + 1;
      if (s.status === 'free' && ok) freeMatching += 1;
      const tappable = ok && (s.status === 'free' || s.status === 'held');
      const changed = lastStatus.has(s.seat_id) && lastStatus.get(s.seat_id) !== s.status;
      lastStatus.set(s.seat_id, s.status);

      el.className = 'chair' +
        (s.status === 'free' ? ' is-free' : s.status === 'held' ? ' is-held' : '') +
        (ok ? '' : ' is-dim') +
        (state.sel === s.seat_id ? ' is-sel' : '');
      if (changed && ok) {
        void el.offsetWidth; // restart the ring animation
        el.classList.add('is-changed');
      }
      el.setAttribute('aria-label', `Seat ${s.seat_id}, ${s.status === 'held' ? 'held by a bag' : s.status}`);
      el.setAttribute('aria-disabled', String(!tappable));
    });

    $('#headline').textContent = freeMatching > 0
      ? plural(freeMatching, 'seat free', 'seats free')
      : counts.free === 0 ? 'Full right now' : 'None free here';
    $('#breakdown').textContent = breakdown(counts, v.seats.length);

    document.querySelectorAll('#seg button').forEach(b => {
      const on = b.dataset.v === state.seg;
      b.classList.toggle('is-on', on);
      b.setAttribute('aria-pressed', String(on));
    });

    updateSheet();
  }

  function breakdown(c, total) {
    if (c.free === total) return `All ${total} seats are free.`;
    const parts = [];
    if (c.taken) parts.push(`${c.taken} taken`);
    if (c.held) parts.push(`${c.held} held by ${c.held === 1 ? 'a bag' : 'bags'}`);
    return `${parts.join(' and ')}, out of ${total}.`;
  }

  function onChair(id) {
    const s = state.venue && state.venue.seats.find(x => x.seat_id === id);
    if (!s || !matchesSeg(s) || (s.status !== 'free' && s.status !== 'held')) return;
    state.sel = id;
    updatePlace();
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
    const held = s.status === 'held';
    const table = tableNames.get(s.table_id) || `Table ${s.table_id}`;
    const chips = [];
    if (held) chips.push(table);
    if (s.has_window) chips.push('By the window');
    if (s.has_outlet) chips.push('Outlet');
    el.setAttribute('aria-label', `Seat ${s.seat_id}`);

    setHTML(el, `
      <div class="sheet-handle"></div>
      <div class="sheet-row">
        <div class="sheet-tile ${held ? 'is-held' : 'is-free'}">${esc(s.seat_id)}</div>
        <div class="sheet-text">
          <span class="sheet-title">Seat ${esc(s.seat_id)} is ${held ? 'held' : 'free'}</span>
          <span class="sheet-sub">${held ? `Held by a bag for ${esc(heldFor(s.since))}` : esc(table)}</span>
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
    el.innerHTML = `<img src="${LOGO}" alt=""><span class="splash-word">Birdie</span><span class="splash-line">Live study seats in Doha</span>`;
    document.body.appendChild(el);
    const timers = [
      setTimeout(() => el.classList.add('is-in'), 40),
      setTimeout(() => el.classList.add('is-out'), 1700),
      setTimeout(done, 2000),
    ];
    function done() {
      timers.forEach(clearTimeout);
      el.remove();
    }
    el.addEventListener('click', done);
  }

  // ---------- Routing and events ----------

  function route() {
    const m = location.hash.match(/^#\/place\/(.+)$/);
    if (m) openPlace(decodeURIComponent(m[1]));
    else showBrowse();
  }
  window.addEventListener('hashchange', route);

  document.addEventListener('click', e => {
    const t = e.target.closest('[data-act]');
    if (!t) return;
    const v = t.dataset.v;
    switch (t.dataset.act) {
      case 'cat': state.cat = v; updateBrowse(); break;
      case 'sort': state.sort = v; updateBrowse(); break;
      case 'open':
        state.browseScroll = window.scrollY;
        location.hash = `#/place/${encodeURIComponent(v)}`;
        state.fromBrowse = true;
        break;
      case 'back':
        if (state.fromBrowse) history.back();
        else location.hash = '';
        break;
      case 'seg': state.seg = v; state.sel = null; updatePlace(); break;
      case 'chair': onChair(v); break;
      case 'close': state.sel = null; updatePlace(); break;
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
