/* Birdie mobile app: Splash, Browse and Place (screens 1 to 3 of design/mobile).
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
  const COLORS = { free: '#2FB86A', taken: '#EF4E4E', held: '#F2A93B' };
  const TYPES = { library: 'Library', cafe: 'Café', cowork: 'Coworking', study_room: 'Study room' };
  const CATS = [['all', 'All'], ['library', 'Libraries'], ['cafe', 'Cafés'], ['cowork', 'Coworking'], ['study_room', 'Study rooms']];
  const SORTS = [['near', 'Nearest'], ['free', 'Most seats free'], ['late', 'Open late']];
  const SEGS = [['all', 'All seats'], ['outlet', 'Outlet'], ['window', 'Window']];

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
  const driveLabel = m => (m === 0 ? "You're here" : `${m} min drive`);
  const sourceLabel = s => (s === 'live' ? 'Live' : s.charAt(0).toUpperCase() + s.slice(1));
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  function seatState(s) {
    if (s.state) return s.state;
    return ({ free: 'FREE', held: 'HELD', taken: 'OCCUPIED' })[s.status] || 'UNKNOWN';
  }

  function seatLabel(s) {
    return ({ FREE: 'Free', OCCUPIED: 'Taken', HELD: 'Held by belongings',
      REVIEW_REQUIRED: 'Staff review required', UNKNOWN: 'Checking', UNAVAILABLE: 'Unavailable' })[seatState(s)];
  }

  // Replace an element's HTML only when it changed, keeping its sideways scroll position.
  function setHTML(el, html) {
    if (!el || el._html === html) return;
    const x = el.scrollLeft;
    el.innerHTML = html;
    el._html = html;
    el.scrollLeft = x;
  }

  function themeColor(c) {
    const m = document.querySelector('meta[name="theme-color"]');
    if (m) m.setAttribute('content', c);
  }

  // ---------- Icons (from the design handoff) ----------

  const svg = (w, h, vb, body, extra = '') =>
    `<svg width="${w}" height="${h}" viewBox="${vb}" fill="none" aria-hidden="true" focusable="false" ${extra}>${body}</svg>`;
  const line = 'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"';

  const ICON = {
    all: (k = 1) => svg(26 * k, 26 * k, '0 0 26 26',
      '<rect x="3" y="3" width="8" height="8" rx="2.5"/><rect x="15" y="3" width="8" height="8" rx="2.5"/><rect x="3" y="15" width="8" height="8" rx="2.5"/><rect x="15" y="15" width="8" height="8" rx="2.5"/>', line),
    library: (k = 1) => svg(28 * k, 26 * k, '0 0 28 26',
      '<path d="M14 6C11 3.5 7 3 3 3.5V21c4-.5 8 0 11 2.5C17 21 21 20.5 25 21V3.5C21 3 17 3.5 14 6Z"/><path d="M14 6v17"/>', line),
    cafe: (k = 1) => svg(28 * k, 26 * k, '0 0 28 26',
      '<path d="M4 9h15v6a6 6 0 0 1-6 6h-3a6 6 0 0 1-6-6V9Z"/><path d="M19 11h2a3 3 0 0 1 0 6h-2.5"/><path d="M9 2.5v3M13.5 2.5v3"/>', line),
    cowork: (k = 1) => svg(28 * k, 26 * k, '0 0 28 26',
      '<rect x="5" y="4" width="18" height="12" rx="2"/><path d="M2 20h24"/>', line),
    study_room: (k = 1) => svg(28 * k, 26 * k, '0 0 28 26',
      '<path d="M8 3.5v9h12"/><path d="M8 12.5v10M20 12.5v10"/><path d="M8 17h12"/>', line),
    chevron: () => svg(12, 8, '0 0 12 8',
      '<path d="M1.5 1.5L6 6l4.5-4.5" stroke="#4B3BFF" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>'),
    search: () => svg(18, 18, '0 0 20 20',
      '<circle cx="9" cy="9" r="6.5" stroke="#4A4D63" stroke-width="2"/><path d="M14 14l4 4" stroke="#4A4D63" stroke-width="2" stroke-linecap="round"/>'),
    back: () => svg(10, 16, '0 0 12 20',
      '<path d="M10 2L2 10l8 8" stroke="#16172E" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>'),
    close: () => svg(11, 11, '0 0 12 12',
      '<path d="M1 1l10 10M11 1L1 11" stroke="#4A4D63" stroke-width="2.2" stroke-linecap="round"/>'),
    entrance: () => svg(10, 10, '0 0 10 10',
      '<path d="M5 9V1M1.5 4.5L5 1l3.5 3.5" stroke="#4A4D63" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'),
    logo: () => svg(80, 80, '0 0 100 100',
      '<path d="M22 84 C20 52 34 24 60 22 C75 21 86 29 89 43 C90.5 50 88 57 82 61 C82.5 55 80 51 75.5 50.5 L69 51 C66 62 61 74 58 84 Z" fill="#FFFFFF"/>' +
      '<path d="M58.5 40 C55 50 52.5 60 51.5 72" stroke="#4B3BFF" stroke-width="5.5" stroke-linecap="round"/>' +
      '<circle cx="64" cy="36" r="6.5" fill="#2FB86A"/>'),
  };
  const typeIcon = (type, k) => (ICON[type] ? ICON[type](k) : '');

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
      el.querySelector('[data-live-text]').textContent = on ? el.dataset.label : 'Reconnecting…';
    });
  }

  const liveBadge = label =>
    `<span class="live" data-live data-label="${esc(label)}"><i class="dot"></i><span data-live-text>${esc(label)}</span></span>`;

  // ---------- Polling ----------

  let timer = null;
  let gen = 0;

  async function refresh() {
    try {
      if (state.screen === 'place' && state.venueId) {
        const id = state.venueId;
        const v = await get(`api/venues/${encodeURIComponent(id)}`);
        if (state.screen !== 'place' || state.venueId !== id) return;
        const rebuild = !state.venue || !$('#plan') || layoutKey(state.venue) !== layoutKey(v);
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

  // ---------- Browse ----------

  function showBrowse() {
    state.screen = 'browse';
    state.venueId = null;
    state.sel = null;
    state.fromBrowse = false;
    removeSheet();
    renderBrowse();
    window.scrollTo(0, state.browseScroll);
    kick();
  }

  function renderBrowse() {
    app.innerHTML = `
      <main class="browse">
        <div class="browse-top">
          <div class="loc">
            <span class="loc-k">Seats near</span>
            <span class="loc-v">Msheireb ${ICON.chevron()}</span>
          </div>
          <label class="search">
            ${ICON.search()}
            <input id="q" type="search" placeholder="Search libraries, cafés, coworks" aria-label="Search places"
              autocomplete="off" autocapitalize="off" spellcheck="false" enterkeyhint="search">
          </label>
        </div>
        <nav class="rail cats" id="cats" aria-label="Categories"></nav>
        <section class="featured" id="featured" hidden>
          <div class="featured-head">
            <h2 class="sec-title">Free right now</h2>
            ${liveBadge('Live')}
          </div>
          <div class="rail cards" id="cards"></div>
        </section>
        <section class="list">
          <h2 class="sec-title" id="listTitle">All places</h2>
          <div class="sorts" id="sorts" role="group" aria-label="Sort places"></div>
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
      return `<button class="cat${on ? ' is-on' : ''}" data-act="cat" data-v="${k}" aria-pressed="${on}">
        <span class="cat-tile">${ICON[k](1)}</span><span class="cat-label">${label}</span></button>`;
    }).join(''));

    const q = fold(state.query.trim());
    const inCat = v => state.cat === 'all' || v.type === state.cat;

    const featured = venues.filter(v => inCat(v) && v.counts.free > 0)
      .sort((a, b) => b.counts.free - a.counts.free)
      .slice(0, 5);
    $('#featured').hidden = featured.length === 0 || q !== '';
    setHTML($('#cards'), featured.map(v => `
      <button class="card" data-act="open" data-v="${esc(v.venue_id)}">
        <span class="card-num">
          <span class="card-free">${v.counts.free}</span>
          <span class="card-k">${v.counts.free === 1 ? 'seat free' : 'seats free'}</span>
        </span>
        <span class="card-place">
          <span class="card-name">${esc(v.name)}</span>
          <span class="card-drive">${esc(driveLabel(v.drive_minutes))}${v.source === 'live' ? '' : ' · ' + esc(sourceLabel(v.source))}</span>
        </span>
      </button>`).join(''));

    let list = venues.filter(v => inCat(v) && (!q || fold(`${v.name} ${v.area} ${typeLabel(v.type)} ${v.type}`).includes(q)));
    if (state.sort === 'late') list = list.filter(v => v.open_late);
    list.sort(state.sort === 'free'
      ? (a, b) => b.counts.free - a.counts.free || a.drive_minutes - b.drive_minutes
      : (a, b) => a.drive_minutes - b.drive_minutes);

    $('#listTitle').textContent = state.cat === 'all' ? 'All places' : CATS.find(c => c[0] === state.cat)[1];
    setHTML($('#sorts'), SORTS.map(([k, label]) => {
      const on = k === state.sort;
      return `<button class="sort${on ? ' is-on' : ''}" data-act="sort" data-v="${k}" aria-pressed="${on}">${label}</button>`;
    }).join(''));
    setHTML($('#rows'), !state.venues
      ? `<p class="empty">${state.online ? 'Loading places…' : 'Can’t reach Birdie. Retrying…'}</p>`
      : list.length ? list.map(row).join('') : '<p class="empty">No places match that search.</p>');
    $('#note').textContent = state.mock ? 'Demo data: no backend connected' : '';
  }

  function row(v) {
    const { free, held, total } = v.counts;
    const unknown = v.counts.unknown || 0;
    const taken = v.counts.taken ?? Math.max(0, total - free - held - unknown);
    const full = free === 0 && unknown === 0;
    const availability = free > 0 ? `${free} of ${total} free` : unknown > 0
      ? `No seats marked free · ${unknown} checking` : 'No seats marked free';
    const seg = (cls, n) => (n > 0 ? `<i class="${cls}" style="flex:${n} 1 0"></i>` : '');
    return `
      <button class="row${full ? ' is-full' : ''}" data-act="open" data-v="${esc(v.venue_id)}">
        <span class="thumb">${typeIcon(v.type, 1.15)}</span>
        <span class="row-body">
          <span class="row-name">${esc(v.name)}</span>
          <span class="row-meta">${esc(typeLabel(v.type))} · ${esc(v.area)}${v.source === 'live' ? '' : ` <span class="chip chip-sim">${esc(sourceLabel(v.source))}</span>`}</span>
          <span class="row-free">
            <i class="dot" style="background:${free > 0 ? COLORS.free : full ? COLORS.taken : '#7C8190'}"></i>${availability}
            <span class="row-drive">· ${esc(driveLabel(v.drive_minutes))}</span>
          </span>
          <span class="bar">${seg('b-free', free)}${seg('b-held', held)}${seg('b-taken', taken)}${seg('b-unknown', unknown)}</span>
        </span>
      </button>`;
  }

  // ---------- Place ----------

  let chairEls = new Map();
  let tableNames = new Map();

  // Changes when the floor plan or the set of seats changes, so the plan is rebuilt.
  const layoutKey = v => JSON.stringify([v.floor_plan || null, v.seats.map(s => [s.seat_id, s.plan_x, s.plan_y, s.plan_rot])]);
  const hasPlanPosition = s => Number.isFinite(s.plan_x) && Number.isFinite(s.plan_y);

  function openPlace(id) {
    const cached = state.venue && state.venue.venue_id === id;
    state.screen = 'place';
    state.venueId = id;
    state.seg = 'all';
    state.sel = null;
    removeSheet();
    if (cached) renderPlace();
    else {
      state.venue = null;
      app.innerHTML = '<p class="loading">Loading…</p>';
    }
    window.scrollTo(0, 0);
    kick();
  }

  function renderPlace() {
    const v = state.venue;
    const plan = v.floor_plan;
    tableNames = new Map((plan?.tables || []).map(t => [t.table_id, t.name]));
    const meta = [typeLabel(v.type), v.area, driveLabel(v.drive_minutes), v.open_until].filter(Boolean).map(esc).join(' · ');
    const live = v.source === 'live';

    app.innerHTML = `
      <main class="place" id="place">
        <div class="hero">
          ${typeIcon(v.type, 2)}
          <button class="back" data-act="back" aria-label="Back">${ICON.back()}</button>
        </div>
        <div class="place-body">
          <div class="place-head">
            <h1>${esc(v.name)}</h1>
            <span class="place-meta">${meta}</span>
            <div class="amenities">
              ${live ? '' : `<span class="chip chip-sim">${esc(sourceLabel(v.source))}</span>`}
              ${(v.amenities || []).map(a => `<span class="chip">${esc(a)}</span>`).join('')}
            </div>
          </div>
          <div class="divider"></div>
          <div class="headline-row">
            <span class="headline" id="headline"></span>
            ${live ? liveBadge('Live') : ''}
          </div>
          <div class="seg" id="seg" role="group" aria-label="Filter seats">
            ${SEGS.map(([k, label]) => `<button data-act="seg" data-v="${k}">${label}</button>`).join('')}
          </div>
          ${plan ? `<div class="plan-wrap" id="planWrap">
            <div class="plan" id="plan" style="width:${plan.width}px;height:${plan.height}px">
              ${plan.window_top ? '<div class="window-strip"></div>' : ''}
              ${(plan.fixtures || []).map(fixtureHTML).join('')}
              ${(plan.tables || []).map(tableHTML).join('')}
              ${v.seats.filter(hasPlanPosition).map(chairHTML).join('')}
              ${plan.entrance === false ? '' : `<div class="entrance">${ICON.entrance()}Entrance</div>`}
            </div>
          </div>${plan.label ? `<p class="plan-caption">${esc(plan.label)}</p>` : ''}` : ''}
          <div class="seat-status-list" id="seatStatusList" aria-label="Seat statuses"></div>
          <div class="legend">
            <span><i style="background:${COLORS.free}"></i>Free</span>
            <span><i style="background:${COLORS.taken}"></i>Taken</span>
            <span><i style="background:${COLORS.held}"></i>Held</span>
            <span><i style="background:#8A8C98"></i>Checking</span>
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
    `<span class="chair-back"></span><span class="chair-seat"></span><span class="chair-id">${esc(s.seat_id)}</span></button>`;

  // Scale the 362-point plan down on narrow phones.
  function fitPlan() {
    const wrap = $('#planWrap');
    const plan = $('#plan');
    if (!wrap || !plan || !state.venue) return;
    const { width, height } = state.venue.floor_plan;
    const k = Math.min(1, wrap.clientWidth / width);
    plan.style.transform = k < 1 ? `scale(${k})` : '';
    wrap.style.height = `${height * k}px`;
  }
  window.addEventListener('resize', fitPlan);

  const matchesSeg = s => state.seg === 'all' || (state.seg === 'outlet' && s.has_outlet) || (state.seg === 'window' && s.has_window);

  function updatePlace() {
    if (state.screen !== 'place' || !state.venue || (!$('#plan') && !$('#seatStatusList'))) return;
    const v = state.venue;
    const plan = Boolean(v.floor_plan && $('#plan'));
    let free = 0;
    let freeMatching = 0;

    // Drop the selection when that seat was taken meanwhile or is hidden by the filter.
    const sel = state.sel && v.seats.find(x => x.seat_id === state.sel);
    if (!sel || !matchesSeg(sel) || !['FREE', 'HELD'].includes(seatState(sel))) state.sel = null;

    v.seats.forEach(s => {
      const el = chairEls.get(s.seat_id);
      const ok = matchesSeg(s);
      const status = seatState(s);
      if (status === 'FREE') { free += 1; if (ok) freeMatching += 1; }
      if (plan && el) {
        el.className = 'chair' +
          (status === 'FREE' ? ' is-free' : status === 'HELD' ? ' is-held' :
            status === 'UNKNOWN' ? ' is-unknown' : status === 'UNAVAILABLE' ? ' is-unavailable' : '') +
          (ok ? '' : ' is-dim') + (state.sel === s.seat_id ? ' is-sel' : '');
        el.setAttribute('aria-label', `${s.seat_id}, ${seatLabel(s)}`);
        el.setAttribute('aria-disabled', String(!(ok && ['FREE', 'HELD'].includes(status))));
      }
    });

    if ($('#seatStatusList')) {
      setHTML($('#seatStatusList'), v.seats.filter(s => matchesSeg(s) && (!plan || !hasPlanPosition(s))).map(s => {
        const status = seatState(s);
        return `<div class="seat-status seat-${status.toLowerCase()}">
          <span class="seat-status-id">${esc(s.seat_id)}</span>
          <span class="seat-status-label">${esc(seatLabel(s))}</span></div>`;
      }).join(''));
    }

    const unknown = v.counts?.unknown ?? v.seats.filter(s => seatState(s) === 'UNKNOWN').length;
    $('#headline').textContent = freeMatching > 0
      ? plural(freeMatching, 'seat free', 'seats free')
      : free > 0 ? 'No seats match this filter'
        : unknown > 0 ? 'Availability is being checked' : 'No seats marked free';

    document.querySelectorAll('#seg button').forEach(b => {
      const on = b.dataset.v === state.seg;
      b.classList.toggle('is-on', on);
      b.setAttribute('aria-pressed', String(on));
    });

    updateSheet();
  }

  function onChair(id) {
    const s = state.venue && state.venue.seats.find(x => x.seat_id === id);
    if (!s || !matchesSeg(s) || !['FREE', 'HELD'].includes(seatState(s))) return;
    state.sel = id;
    updatePlace();
  }

  // ---------- Seat sheet ----------

  function removeSheet() {
    const el = $('#sheet');
    if (el) el.remove();
    const place = $('#place');
    if (place) place.classList.remove('has-sheet');
  }

  function updateSheet() {
    const s = state.sel && state.venue.seats.find(x => x.seat_id === state.sel);
    if (!s) {
      removeSheet();
      return;
    }

    let el = $('#sheet');
    if (!el) {
      el = document.createElement('div');
      el.id = 'sheet';
      el.className = 'sheet';
      el.setAttribute('role', 'dialog');
      document.body.appendChild(el);
      $('#place').classList.add('has-sheet');
    }
    const held = seatState(s) === 'HELD';
    el.setAttribute('aria-label', `Seat ${s.seat_id}`);
    const chips = s.table_id ? [tableNames.get(s.table_id) || `Table ${s.table_id}`] : [];
    if (s.has_window) chips.push('Window');
    if (s.has_outlet) chips.push('Outlet');

    setHTML(el, `
      <div class="sheet-handle"></div>
      <div class="sheet-row">
        <div class="sheet-tile" style="background:${held ? COLORS.held : COLORS.free}">${esc(s.seat_id)}</div>
        <div class="sheet-text">
          <span class="sheet-title">${held ? `Seat ${esc(s.seat_id)} is held by a bag` : `Seat ${esc(s.seat_id)} is free`}</span>
          ${held ? `<span class="sheet-sub">Unavailable because belongings are present</span>` : ''}
          <div class="sheet-chips">${chips.map(c => `<span class="chip">${esc(c)}</span>`).join('')}</div>
        </div>
        <button class="sheet-close" data-act="close" aria-label="Close">${ICON.close()}</button>
      </div>`);
  }

  // ---------- Splash ----------

  function splash() {
    const el = document.createElement('div');
    el.className = 'splash';
    el.setAttribute('role', 'presentation');
    el.innerHTML = `<div class="splash-mark">${ICON.logo()}<span class="splash-word">Birdie</span></div>`;
    document.body.appendChild(el);
    themeColor('#4B3BFF');
    const timers = [
      setTimeout(() => el.classList.add('is-in'), 60),
      setTimeout(() => el.classList.add('is-out'), 1700),
      setTimeout(done, 2200),
    ];
    function done() {
      timers.forEach(clearTimeout);
      el.remove();
      themeColor('#F6F1E7');
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
