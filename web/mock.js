/* Mock backend for building the app before the real API exists.
 *
 * It answers exactly like the API in CLAUDE.md section 7.2, so switching to the real backend needs no
 * code changes. The app uses it when the server has no /api (for example when web/ is served with
 * `python3 -m http.server`) or when the URL has ?mock=1. All of this data is invented.
 */
window.BirdieMock = (() => {
  'use strict';

  const OFF = 17; // distance from a table edge to the centre of its chairs, in plan points

  // Floor plans from the design handoff. `chairs` says how many chairs sit on each side
  // (t, b, l, r) or around a round table (n); it is only used here to generate seats.
  const LAYOUTS = {
    library: {
      height: 490, window_top: true,
      tables: [
        { table_id: 'W', name: 'Window bar', shape: 'rect', x: 24, y: 22, w: 314, h: 16, chairs: { b: 8 }, window: true, outlet: true },
        { table_id: 'A', name: 'Table A', shape: 'rect', x: 34, y: 118, w: 130, h: 46, chairs: { t: 3, b: 3 }, outlet: true },
        { table_id: 'B', name: 'Table B', shape: 'rect', x: 198, y: 118, w: 130, h: 46, chairs: { t: 3, b: 3 } },
        { table_id: 'C', name: 'Round table C', shape: 'round', cx: 96, cy: 272, r: 30, chairs: { n: 4 } },
        { table_id: 'D', name: 'Round table D', shape: 'round', cx: 266, cy: 272, r: 30, chairs: { n: 4 }, outlet: true },
        { table_id: 'E', name: 'Booth E', shape: 'rect', x: 60, y: 366, w: 56, h: 72, chairs: { l: 2, r: 2 }, outlet: true },
        { table_id: 'F', name: 'Booth F', shape: 'rect', x: 246, y: 366, w: 56, h: 72, chairs: { l: 2, r: 2 }, outlet: true },
      ],
      fixtures: [{ label: 'Books', x: 152, y: 370, w: 58, h: 64 }],
    },
    cafe: {
      height: 430, window_top: true,
      tables: [
        { table_id: 'W', name: 'Window bar', shape: 'rect', x: 24, y: 22, w: 314, h: 16, chairs: { b: 6 }, window: true },
        { table_id: 'R', name: 'Café table R', shape: 'round', cx: 72, cy: 150, r: 22, chairs: { n: 3 }, outlet: true },
        { table_id: 'S', name: 'Café table S', shape: 'round', cx: 181, cy: 150, r: 22, chairs: { n: 3 } },
        { table_id: 'T', name: 'Café table T', shape: 'round', cx: 290, cy: 150, r: 22, chairs: { n: 3 } },
        { table_id: 'L', name: 'Long table', shape: 'rect', x: 60, y: 240, w: 242, h: 44, chairs: { t: 5, b: 5 }, outlet: true },
      ],
      fixtures: [{ label: 'Counter', x: 210, y: 340, w: 128, h: 40 }],
    },
    cowork: {
      height: 430, window_top: true,
      tables: [
        { table_id: 'D', name: 'Desk row D', shape: 'rect', x: 40, y: 44, w: 282, h: 40, chairs: { t: 5, b: 5 }, outlet: true, window: true },
        { table_id: 'E', name: 'Desk row E', shape: 'rect', x: 40, y: 172, w: 282, h: 40, chairs: { t: 5, b: 5 }, outlet: true },
        { table_id: 'P', name: 'Focus pod', shape: 'rect', x: 24, y: 290, w: 60, h: 34, chairs: { b: 1 }, outlet: true, single: true },
        { table_id: 'Q', name: 'Focus pod', shape: 'rect', x: 108, y: 290, w: 60, h: 34, chairs: { b: 1 }, outlet: true, single: true },
        { table_id: 'R', name: 'Focus pod', shape: 'rect', x: 194, y: 290, w: 60, h: 34, chairs: { b: 1 }, outlet: true, single: true },
        { table_id: 'S', name: 'Focus pod', shape: 'rect', x: 278, y: 290, w: 60, h: 34, chairs: { b: 1 }, outlet: true, single: true },
      ],
      fixtures: [],
    },
    study: {
      height: 360, window_top: false,
      tables: [
        { table_id: 'G', name: 'Table G', shape: 'rect', x: 40, y: 50, w: 120, h: 56, chairs: { t: 3, b: 3 }, outlet: true },
        { table_id: 'H', name: 'Table H', shape: 'rect', x: 202, y: 50, w: 120, h: 56, chairs: { t: 3, b: 3 } },
        { table_id: 'I', name: 'Round table I', shape: 'round', cx: 181, cy: 240, r: 34, chairs: { n: 6 } },
      ],
      fixtures: [],
    },
  };

  // Doha venues. Nestwork is a recorded demo replay; the rest are simulated.
  const VENUES = [
    { venue_id: 'nestwork-msheireb', name: 'Nestwork Msheireb', area: 'Msheireb Downtown', type: 'cowork', lat: 25.2867, lon: 51.5265,
      source: 'recorded', drive_minutes: 0, open_until: 'Open till 22:00', open_late: true, amenities: ['Wi-Fi', 'Outlets', 'Coffee'],
      zones: ['open'], layout: 'cowork', pFree: 0.45, pHeld: 0.08, seed: 11 },
    { venue_id: 'qnl', name: 'Qatar National Library', area: 'Education City', type: 'library', lat: 25.3147, lon: 51.4405,
      source: 'simulated', drive_minutes: 15, open_until: 'Open till 22:00', open_late: true,
      amenities: ['Quiet zone', "Women's section", 'Wi-Fi', 'Outlets'], zones: ['quiet', 'open', 'women'], layout: 'library', pFree: 0.42, pHeld: 0.1, seed: 7 },
    { venue_id: 'qu-library', name: 'Qatar University Library', area: 'Qatar University', type: 'library', lat: 25.377, lon: 51.49,
      source: 'simulated', drive_minutes: 25, open_until: 'Open till 21:00', open_late: false,
      amenities: ['Quiet zone', "Women's section", 'Printing'], zones: ['quiet', 'women'], layout: 'library', pFree: 0.25, pHeld: 0.12, seed: 9 },
    { venue_id: 'qahwa-corner', name: 'Qahwa Corner', area: 'Lusail', type: 'cafe', lat: 25.42, lon: 51.49,
      source: 'simulated', drive_minutes: 25, open_until: 'Open till 01:00', open_late: true,
      amenities: ['Wi-Fi', 'Family section', 'Food'], zones: ['family', 'terrace'], layout: 'cafe', pFree: 0.3, pHeld: 0.08, seed: 21 },
    { venue_id: 'corniche-cup', name: 'Corniche Cup', area: 'West Bay', type: 'cafe', lat: 25.322, lon: 51.53, // invented
      source: 'simulated', drive_minutes: 10, open_until: 'Open till 23:00', open_late: true,
      amenities: ['Wi-Fi', 'Outlets', 'Terrace'], zones: ['open', 'terrace'], layout: 'cafe', pFree: 0.18, pHeld: 0.1, seed: 3 },
    { venue_id: 'nakheel-study', name: 'Nakheel Study Rooms', area: 'Al Sadd', type: 'study_room', lat: 25.285, lon: 51.5, // invented
      source: 'simulated', drive_minutes: 12, open_until: 'Open till 00:00', open_late: true,
      amenities: ['Quiet zone', 'Outlets'], zones: ['quiet'], layout: 'study', pFree: 0.35, pHeld: 0.06, seed: 14 },
    { venue_id: 'waab-study-hall', name: 'Al Waab Study Hall', area: 'Al Waab', type: 'study_room', lat: 25.263, lon: 51.45, // invented
      source: 'simulated', drive_minutes: 20, open_until: 'Open till 22:00', open_late: false,
      amenities: ['Quiet zone', "Women's section"], zones: ['quiet', 'women'], layout: 'study', pFree: 0, pHeld: 0, seed: 5 },
  ];

  const round1 = n => Math.round(n * 10) / 10;

  function seatsFor(layout) {
    const seats = [];
    layout.tables.forEach(t => {
      let i = 0;
      const add = (x, y, rot) => {
        i += 1;
        seats.push({
          seat_id: t.single ? t.table_id : t.table_id + i, table_id: t.table_id,
          has_outlet: !!t.outlet, has_window: !!t.window, plan_x: round1(x), plan_y: round1(y), plan_rot: round1(rot),
        });
      };
      const c = t.chairs;
      if (t.shape === 'round') {
        for (let k = 0; k < c.n; k++) {
          const a = -Math.PI / 2 + (2 * Math.PI * k) / c.n;
          add(t.cx + (t.r + OFF) * Math.cos(a), t.cy + (t.r + OFF) * Math.sin(a), (a * 180) / Math.PI + 90);
        }
      } else {
        for (let k = 0; k < (c.t || 0); k++) add(t.x + (t.w * (k + 0.5)) / c.t, t.y - OFF, 0);
        for (let k = 0; k < (c.b || 0); k++) add(t.x + (t.w * (k + 0.5)) / c.b, t.y + t.h + OFF, 180);
        for (let k = 0; k < (c.l || 0); k++) add(t.x - OFF, t.y + (t.h * (k + 0.5)) / c.l, -90);
        for (let k = 0; k < (c.r || 0); k++) add(t.x + t.w + OFF, t.y + (t.h * (k + 0.5)) / c.r, 90);
      }
    });
    return seats;
  }

  // The API's floor plan: tables without the generator-only fields.
  function planFor(layout) {
    return {
      width: 362, height: layout.height, window_top: layout.window_top,
      tables: layout.tables.map(({ chairs, window, outlet, single, ...t }) => t),
      fixtures: layout.fixtures.map(f => ({ ...f })),
    };
  }

  function rng(seed) {
    let a = seed;
    return () => {
      a |= 0; a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // Live state: venue_id -> seats with status and since.
  const now = () => Date.now();
  const live = {};
  VENUES.forEach(v => {
    const r = rng(v.seed);
    live[v.venue_id] = seatsFor(LAYOUTS[v.layout]).map(s => {
      const x = r();
      const status = x < v.pFree ? 'free' : x < v.pFree + v.pHeld ? 'held' : 'taken';
      return { ...s, status, since: new Date(now() - Math.floor(r() * 50 * 60000)).toISOString() };
    });
  });

  // Random seat changes, so the mock feels live.
  function tick() {
    const pool = VENUES.filter(v => v.pFree > 0);
    const v = pool[Math.floor(Math.random() * pool.length)];
    const seats = live[v.venue_id];
    const s = seats[Math.floor(Math.random() * seats.length)];
    const x = Math.random();
    let next = s.status;
    if (s.status === 'free') next = 'taken';
    else if (s.status === 'taken') next = x < 0.4 ? 'free' : x < 0.52 ? 'held' : 'taken';
    else next = x < 0.5 ? 'free' : 'taken';
    if (next !== s.status) { s.status = next; s.since = new Date().toISOString(); }
  }
  setInterval(tick, 1300);

  function summary(v) {
    const seats = live[v.venue_id];
    const counts = { free: 0, taken: 0, held: 0, total: seats.length };
    seats.forEach(s => { counts[s.status] += 1; });
    const { layout, pFree, pHeld, seed, ...fields } = v;
    return { ...fields, counts };
  }

  const clone = x => JSON.parse(JSON.stringify(x));

  return {
    // GET /api/venues
    venues: async () => clone(VENUES.map(summary)),
    // GET /api/venues/{venue_id}
    venue: async id => {
      const v = VENUES.find(x => x.venue_id === id);
      if (!v) throw Object.assign(new Error('Venue not found'), { status: 404 });
      return clone({ ...summary(v), floor_plan: planFor(LAYOUTS[v.layout]), seats: live[id] });
    },
  };
})();
