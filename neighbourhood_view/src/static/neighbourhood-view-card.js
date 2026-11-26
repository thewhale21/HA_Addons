/* Neighbourhood View: the drawing of the streets around your home (an isometric picture, as SVG),
 * used by the add-on's own page (window.NeighbourhoodView.render) and as a dashboard card
 * (custom:neighbourhood-view-card), which reads the map from the add-on through Home Assistant's
 * ingress, as the add-on's page does.
 *
 * The scene it draws is made by the add-on (src/scene.py): metres from your home, x east, y north.
 */
(() => {
  const VERSION = '__VERSION__';

  // ---------- colours ----------
  const C = {
    ground: '#e6e9df', sideA: '#dcaa6c', sideB: '#c99256',
    grass: '#a9d98e', wood: '#8ccb76', pitch: '#9bd284', water: '#93c8ec', paved: '#cfd3d8',
    road: '#676b73', roadEdge: '#f4f1ea', roadLine: '#f3f3f3', path: '#f6f1e4', pathEdge: '#d9d2c0',
    rail: '#b2aca2', railLine: '#6f6a63', railTie: '#8d877e',
    tree: '#5fb04d', treeDark: '#3e8b39', treeLight: '#8fd170', trunk: '#8c6a48',
    pin: '#2196f3', pinText: '#ffffff', text: '#6b6b6b',
  };
  // walls (lit, shaded), roof (flat), roof slopes (lit, shaded)
  const KIND = {
    house: ['#f5ecd6', '#dccfb1', '#c9c3b8', '#ea8253', '#c8643c'],
    flats: ['#f3f4f6', '#d1d5db', '#c3c8d0'],
    commercial: ['#f4f4f2', '#d3d5d8', '#b7bdc6'],
    industrial: ['#e3e7ed', '#c1c7d0', '#a8b0bc'],
    small: ['#e8e3d8', '#c9c2b4', '#a9a8a4'],
    civic: ['#f3ede1', '#d9ceb8', '#bba98f'],
    large: ['#eef0f2', '#cfd3d9', '#bcc2cb'],
    home: ['#e3f1fd', '#b7d8f5', '#64b5f6', '#42a5f5', '#1e88e5'],
  };
  const ELEV = 35 * Math.PI / 180;  // how high above the ground it's looked at from
  const SE = Math.sin(ELEV), CE = Math.cos(ELEV);
  const BASE = 9;  // the board's thickness, m

  function view(rot) {
    const a = (30 + 90 * ((rot || 0) % 4)) * Math.PI / 180, ca = Math.cos(a), sa = Math.sin(a);
    return {
      // screen x, y (y down) of a point x, y metres at height z
      p: (x, y, z = 0) => [x * ca - y * sa, -(x * sa + y * ca) * SE - z * CE],
      // how far away (bigger: further back, drawn first)
      d: (x, y) => x * sa + y * ca,
      // a direction turned to the screen: [across, away]
      n: (nx, ny) => [nx * ca - ny * sa, nx * sa + ny * ca],
    };
  }

  const f = (v) => (Math.round(v * 10) / 10).toString();
  const pts = (arr) => arr.map(([x, y]) => f(x) + ',' + f(y)).join(' ');
  const poly = (arr, fill, extra = '') => `<polygon points="${pts(arr)}" fill="${fill}"${extra}/>`;
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

  // a colour between two (t 0..1)
  function mix(a, b, t) {
    const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
    const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
    return '#' + pa.map((v, i) => Math.round(v + (pb[i] - v) * t).toString(16).padStart(2, '0')).join('');
  }

  function centroid(p) {
    let a = 0, x = 0, y = 0;
    for (let i = 0; i < p.length; i++) {
      const [x1, y1] = p[i], [x2, y2] = p[(i + 1) % p.length], c = x1 * y2 - x2 * y1;
      a += c; x += (x1 + x2) * c; y += (y1 + y2) * c;
    }
    if (Math.abs(a) < 1e-6) return [p.reduce((s, q) => s + q[0], 0) / p.length, p.reduce((s, q) => s + q[1], 0) / p.length];
    return [x / (3 * a), y / (3 * a)];
  }

  // The walls of a footprint (anticlockwise) that face the viewer, back ones first: [[depth, svg]]
  function walls(V, ring, z0, z1, cols, extraTop) {
    const out = [];
    for (let i = 0; i < ring.length; i++) {
      const p = ring[i], q = ring[(i + 1) % ring.length];
      const [ax, aw] = V.n(q[1] - p[1], -(q[0] - p[0]));
      if (aw >= -1e-6) continue;  // facing away
      const len = Math.hypot(ax, aw) || 1;
      const shade = mix(cols[0], cols[1], Math.max(0, Math.min(1, (ax / len + 1) / 2)));
      const face = [V.p(p[0], p[1], z0), V.p(q[0], q[1], z0), V.p(q[0], q[1], z1), V.p(p[0], p[1], z1)];
      if (extraTop && extraTop[i]) face.splice(3, 0, extraTop[i]);
      out.push([V.d((p[0] + q[0]) / 2, (p[1] + q[1]) / 2), poly(face, shade, ' stroke="' + shade + '" stroke-width=".3"')]);
    }
    return out.sort((a, b) => b[0] - a[0]);
  }

  function building(V, b, isHome) {
    const cols = isHome ? KIND.home : (KIND[b.k] || KIND.large);
    const h = b.h || 6;
    let svg = '';
    if (b.r === 'gable' && b.rect) {
      const [A, B, Cc, D] = b.rect, rh = b.rh || 2.5, top = h + rh;
      const Ra = [(D[0] + A[0]) / 2, (D[1] + A[1]) / 2], Rb = [(B[0] + Cc[0]) / 2, (B[1] + Cc[1]) / 2];
      // the gable ends: the short walls (B→C and D→A) go up to the ridge
      const gables = [null, V.p(Rb[0], Rb[1], top), null, V.p(Ra[0], Ra[1], top)];
      svg += walls(V, b.rect, 0, h, cols, gables).map((w) => w[1]).join('');
      const roofLit = cols[3] || cols[2], roofDark = cols[4] || cols[2];
      const slopes = [[A, B, Rb, Ra], [Cc, D, Ra, Rb]].map((s) => {
        const [nx, nw] = V.n(s[1][1] - s[0][1], -(s[1][0] - s[0][0]));
        const len = Math.hypot(nx, nw) || 1;
        const col = mix(roofLit, roofDark, Math.max(0, Math.min(1, (nx / len + 1) / 2 * 0.6 + (nw > 0 ? 0.4 : 0))));
        const face = [V.p(s[0][0], s[0][1], h), V.p(s[1][0], s[1][1], h), V.p(s[2][0], s[2][1], top), V.p(s[3][0], s[3][1], top)];
        return [V.d((s[0][0] + s[1][0]) / 2, (s[0][1] + s[1][1]) / 2), poly(face, col, ` stroke="${col}" stroke-width=".3"`)];
      }).sort((a, b) => b[0] - a[0]);
      svg += slopes.map((s) => s[1]).join('');
      // the ridge
      const r1 = V.p(Ra[0], Ra[1], top), r2 = V.p(Rb[0], Rb[1], top);
      svg += `<line x1="${f(r1[0])}" y1="${f(r1[1])}" x2="${f(r2[0])}" y2="${f(r2[1])}" stroke="${roofDark}" stroke-width=".5"/>`;
      return {svg, top: [(r1[0] + r2[0]) / 2, Math.min(r1[1], r2[1])]};
    }
    svg += walls(V, b.p, 0, h, cols).map((w) => w[1]).join('');
    const roof = b.p.map(([x, y]) => V.p(x, y, h));
    svg += poly(roof, cols[2], ` stroke="${mix(cols[2], '#000000', 0.12)}" stroke-width=".4"`);
    const [cx, cy] = centroid(b.p);
    return {svg, top: V.p(cx, cy, h)};
  }

  function tree(V, [x, y, s]) {
    const r = 2.6 * (s || 1), trunkTop = 2.6 * (s || 1);
    const base = V.p(x, y, 0), t = V.p(x, y, trunkTop), c = V.p(x, y, trunkTop + r * 0.9);
    return `<line x1="${f(base[0])}" y1="${f(base[1])}" x2="${f(t[0])}" y2="${f(t[1])}" stroke="${C.trunk}" stroke-width="${f(r * 0.28)}"/>`
      + `<circle cx="${f(c[0])}" cy="${f(c[1])}" r="${f(r)}" fill="${C.treeDark}"/>`
      + `<circle cx="${f(c[0] - r * 0.22)}" cy="${f(c[1] - r * 0.22)}" r="${f(r * 0.78)}" fill="${C.tree}"/>`
      + `<circle cx="${f(c[0] - r * 0.4)}" cy="${f(c[1] - r * 0.42)}" r="${f(r * 0.3)}" fill="${C.treeLight}"/>`;
  }

  function line(V, p, z = 0) {
    return 'M' + p.map(([x, y]) => { const q = V.p(x, y, z); return f(q[0]) + ' ' + f(q[1]); }).join('L');
  }

  /**
   * The drawing as SVG text. opts: {rot: 0-3 (quarter turns), label: the pin's text, pick: true
   * (buildings can be clicked: data-id), hideLabel}
   */
  function draw(scene, opts = {}) {
    const V = view(opts.rot || 0), H = scene.half || 250, home = scene.home || {};
    const out = [];
    // the board: its sides (those facing the viewer), then its top
    const sq = [[-H, -H], [H, -H], [H, H], [-H, H]];
    for (let i = 0; i < 4; i++) {
      const p = sq[i], q = sq[(i + 1) % 4];
      const [ax, aw] = V.n(q[1] - p[1], -(q[0] - p[0]));
      if (aw >= 0) continue;
      out.push(poly([V.p(p[0], p[1], 0), V.p(q[0], q[1], 0), V.p(q[0], q[1], -BASE), V.p(p[0], p[1], -BASE)], ax < 0 ? C.sideA : C.sideB));
    }
    const topPts = sq.map(([x, y]) => V.p(x, y, 0));
    out.push(poly(topPts, C.ground));
    // the ground: areas, water, roads, railways (kept to the board: a road's end doesn't stick out)
    const clip = 'nvclip' + Math.random().toString(36).slice(2, 8);
    out.push(`<clipPath id="${clip}"><polygon points="${pts(topPts)}"/></clipPath><g clip-path="url(#${clip})">`);
    for (const a of scene.areas || []) out.push(poly(a.p.map(([x, y]) => V.p(x, y, 0)), C[a.k] || C.grass));
    for (const w of scene.water || []) out.push(`<path d="${line(V, w.p)}" fill="none" stroke="${C.water}" stroke-width="${f(w.w)}" stroke-linecap="round" stroke-linejoin="round"/>`);
    const roads = scene.roads || [];
    const paths = roads.filter((r) => r.k === 'path'), cars = roads.filter((r) => r.k !== 'path');
    for (const r of paths) out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.pathEdge}" stroke-width="${f(r.w + 0.8)}" stroke-linecap="round" stroke-linejoin="round"/>`);
    for (const r of paths) out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.path}" stroke-width="${f(r.w)}" stroke-linecap="round" stroke-linejoin="round"/>`);
    for (const r of cars) out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.roadEdge}" stroke-width="${f(r.w + 3)}" stroke-linecap="round" stroke-linejoin="round"/>`);
    for (const r of cars) out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.road}" stroke-width="${f(r.w)}" stroke-linecap="round" stroke-linejoin="round"/>`);
    for (const r of cars.filter((r) => r.k === 'major')) out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.roadLine}" stroke-width=".5" stroke-dasharray="4 4"/>`);
    for (const r of scene.rails || []) {
      out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.rail}" stroke-width="${f(r.w)}" stroke-linecap="butt" stroke-linejoin="round"/>`);
      out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.railTie}" stroke-width="${f(r.w * 0.55)}" stroke-dasharray=".6 1.4"/>`);
      out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.railLine}" stroke-width=".35"/>`);
    }
    out.push('</g>');
    // the buildings and trees, back to front
    const things = [];
    let pin = null;
    for (const b of scene.buildings || []) {
      const [cx, cy] = centroid(b.p), isHome = home.id != null && b.id === home.id;
      const d = building(V, b, isHome);
      if (isHome) pin = d.top;
      const attrs = opts.pick ? ` data-id="${b.id}" class="bld"` : '';
      things.push([V.d(cx, cy), `<g${attrs}>${d.svg}</g>`]);
    }
    for (const t of scene.trees || []) things.push([V.d(t[0], t[1]), tree(V, t)]);
    things.sort((a, b) => b[0] - a[0]);
    for (const t of things) out.push(t[1]);
    // the pin over your home
    if (!pin) pin = V.p(home.x || 0, home.y || 0, 0);
    if (!opts.hideLabel) {
      const label = esc(opts.label || 'HOME'), fs = H * 0.034, w = label.length * fs * 0.66 + fs * 1.6, ph = fs * 1.9;
      const top = pin[1] - H * 0.13;
      out.push(`<line x1="${f(pin[0])}" y1="${f(pin[1])}" x2="${f(pin[0])}" y2="${f(top)}" stroke="${C.pin}" stroke-width="${f(fs * 0.14)}"/>`
        + `<circle cx="${f(pin[0])}" cy="${f(pin[1])}" r="${f(fs * 0.3)}" fill="${C.pin}"/>`
        + `<rect x="${f(pin[0] - w / 2)}" y="${f(top - ph)}" width="${f(w)}" height="${f(ph)}" rx="${f(ph / 2)}" fill="${C.pin}" stroke="#ffffff" stroke-width="${f(fs * 0.12)}"/>`
        + `<text x="${f(pin[0])}" y="${f(top - ph / 2)}" fill="${C.pinText}" font-size="${f(fs)}" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-weight="700" letter-spacing="${f(fs * 0.08)}" text-anchor="middle" dominant-baseline="central">${label}</text>`);
    }
    // the box around it all (for the viewBox)
    const corners = [];
    for (const [x, y] of sq) corners.push(V.p(x, y, 0), V.p(x, y, -BASE));
    const xs = corners.map((c) => c[0]), ys = corners.map((c) => c[1]).concat([pin[1] - H * 0.2]);
    const m = H * 0.04, x0 = Math.min(...xs) - m, y0 = Math.min(...ys) - m, w = Math.max(...xs) - x0 + m, h = Math.max(...ys) - y0 + m * 2.2;
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${f(x0)} ${f(y0)} ${f(w)} ${f(h)}" data-box="${f(x0)} ${f(y0)} ${f(w)} ${f(h)}" data-pin="${f(pin[0])} ${f(pin[1] - H * 0.06)}" preserveAspectRatio="xMidYMid meet" style="width:100%;height:100%;display:block" role="img" aria-label="The streets around your home">${out.join('')}</svg>`;
  }

  /* Fits the drawing to its box: all of it where the box is about its shape; in a much narrower
   * (or flatter) box, e.g. a phone held upright, closer in around your home (up to MAX_ZOOM),
   * rather than tiny in the middle. Done again as the box changes size. */
  const MAX_ZOOM = 2.4;
  function fit(el) {
    const svg = el.querySelector('svg');
    if (!svg) return;
    const [x0, y0, w, h] = svg.dataset.box.split(' ').map(Number), [px, py] = svg.dataset.pin.split(' ').map(Number);
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const boxAr = r.width / r.height, ar = w / h;
    const z = Math.min(MAX_ZOOM, Math.max(1, boxAr < ar ? ar / boxAr : boxAr / ar) ** 0.75);
    let vw, vh;
    if (boxAr < ar) { vw = w / z; vh = vw / boxAr; } else { vh = h / z; vw = vh * boxAr; }
    const clampTo = (c, size, lo, full) => (size >= full ? lo + (full - size) / 2 : Math.min(lo + full - size, Math.max(lo, c - size / 2)));
    svg.setAttribute('viewBox', `${f(clampTo(px, vw, x0, w))} ${f(clampTo(py, vh, y0, h))} ${f(vw)} ${f(vh)}`);
  }

  function render(el, scene, opts) {
    // (OpenStreetMap's credit, as its licence asks: in a corner of the box, whatever the zoom)
    el.innerHTML = draw(scene, opts) + '<div style="position:absolute;left:10px;bottom:6px;font:11px/1.2 sans-serif;color:rgba(255,255,255,.55);pointer-events:none">\u00a9 OpenStreetMap contributors</div>';
    if (getComputedStyle(el).position === 'static') el.style.position = 'relative';
    fit(el);
    if (!el._nvObserver && window.ResizeObserver) {
      el._nvObserver = new ResizeObserver(() => fit(el));
      el._nvObserver.observe(el);
    }
  }

  window.NeighbourhoodView = {draw, render, fit, version: VERSION};

  // ---------- the dashboard card ----------
  if (!window.customElements || customElements.get('neighbourhood-view-card')) return;

  const ROT_KEY = 'neighbourhood-view-rot';
  const getRot = () => { try { return Number(localStorage.getItem(ROT_KEY)) || 0; } catch (e) { return 0; } };
  const setRot = (r) => { try { localStorage.setItem(ROT_KEY, String(r)); } catch (e) { /* (not kept) */ } };

  class NeighbourhoodViewCard extends HTMLElement {
    setConfig(config) {
      this._config = {...(config || {})};
      if (this._root) this._size();
    }

    static getStubConfig() { return {}; }

    getCardSize() { return 10; }

    getGridOptions() { return {columns: 'full', rows: 8, min_rows: 4}; }

    set isPanel(v) { this._panel = !!v; if (this._root) this._size(); }

    set hass(hass) {
      this._hass = hass;
      if (!this._root) this._build();
      if (!this._started && hass) {
        this._started = true;
        this._load();
        this._timer = setInterval(() => this._load(), 30 * 60000);
      }
    }

    disconnectedCallback() { clearInterval(this._timer); this._started = false; }

    connectedCallback() { if (this._hass && !this._started) this.hass = this._hass; }

    _build() {
      this._root = this.attachShadow({mode: 'open'});
      this._root.innerHTML = `<style>
        :host { display: block; }
        ha-card { display: block; position: relative; overflow: hidden; height: 100%; box-sizing: border-box;
          background: var(--nv-background, var(--ha-card-background, var(--card-background-color, #111))); }
        .map { position: absolute; inset: 0; }
        .msg { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; text-align: center;
          padding: 24px; color: var(--secondary-text-color, #999); font: 14px/1.4 var(--paper-font-body1_-_font-family, sans-serif); }
        .tools { position: absolute; right: 10px; bottom: 10px; display: flex; gap: 6px; }
        .tools button { width: 34px; height: 34px; border-radius: 50%; border: none; cursor: pointer; font-size: 17px; line-height: 1;
          background: rgba(0,0,0,.35); color: #fff; backdrop-filter: blur(4px); }
        .tools button:hover { background: rgba(0,0,0,.55); }
      </style><ha-card><div class="map"></div><div class="msg">Reading the map…</div>
        <div class="tools"><button data-r="-1" title="Turn left" aria-label="Turn left">⟲</button><button data-r="1" title="Turn right" aria-label="Turn right">⟳</button></div></ha-card>`;
      this._root.querySelector('.tools').addEventListener('click', (e) => {
        const r = Number(e.target.dataset && e.target.dataset.r);
        if (!r) return;
        setRot((getRot() + r + 4) % 4);
        this._draw();
      });
      this._size();
    }

    // As tall as the screen (less the header) in a panel view, else config.height or 4:3
    _size() {
      const card = this._root.querySelector('ha-card');
      const h = this._config && this._config.height;
      if (h) { this.style.height = ''; card.style.height = /^\d+$/.test(String(h)) ? h + 'px' : h; card.style.aspectRatio = ''; return; }
      if (this._panel) { this.style.height = 'calc(100vh - var(--header-height, 56px))'; card.style.height = '100%'; card.style.aspectRatio = ''; card.style.borderRadius = '0'; return; }
      this.style.height = '100%';
      card.style.height = '100%';
      card.style.minHeight = '240px';
      card.style.aspectRatio = '4 / 3';
    }

    _msg(text) {
      const m = this._root.querySelector('.msg');
      m.textContent = text || '';
      m.style.display = text ? 'flex' : 'none';
    }

    // The add-on's address through ingress (as its own page in the sidebar), or config.url
    async _base() {
      if (this._config.url) return this._config.url.replace(/\/?$/, '/');
      if (this._ingress && Date.now() - this._ingressAt < 10 * 60000) return this._ingress;
      const ws = (endpoint, method = 'get') => this._hass.callWS({type: 'supervisor/api', endpoint, method});
      let slug = this._config.addon;
      if (!slug) {
        const list = await ws('/addons');
        const a = ((list && list.addons) || []).find((x) => /(^|_)neighbourhood_view$/.test(x.slug));
        if (!a) throw new Error("The Neighbourhood View add-on isn't installed.");
        slug = a.slug;
      }
      const info = await ws(`/addons/${slug}/info`);
      if (info.state !== 'started') throw new Error('The Neighbourhood View add-on isn\'t running.');
      const session = await ws('/ingress/session', 'post');
      document.cookie = `ingress_session=${session.session};path=/api/hassio_ingress/;SameSite=Strict${location.protocol === 'https:' ? ';Secure' : ''}`;
      this._ingress = info.ingress_url.replace(/\/?$/, '/');
      this._ingressAt = Date.now();
      return this._ingress;
    }

    async _load() {
      try {
        const base = await this._base();
        const r = await fetch(base + 'api/scene', {credentials: 'same-origin', cache: 'no-store'});
        if (!r.ok) throw new Error(`The add-on answered ${r.status}`);
        const d = await r.json();
        if (!d.scene) { this._scene = null; this._msg(d.message || 'Set your postcode and house number in the Neighbourhood View add-on.'); return; }
        this._scene = d.scene;
        this._draw();
      } catch (e) {
        const admin = this._hass && this._hass.user && this._hass.user.is_admin;
        this._msg((e && e.message ? e.message : String(e)) + (admin === false ? ' (The card needs an administrator account to read the add-on.)' : ''));
      }
    }

    _draw() {
      if (!this._scene) return;
      const s = this._scene, label = this._config.label || (s.number ? `NO. ${s.number}` : 'HOME');
      render(this._root.querySelector('.map'), s, {rot: getRot(), label: String(label).toUpperCase()});
      this._msg('');
    }
  }

  customElements.define('neighbourhood-view-card', NeighbourhoodViewCard);
  window.customCards = window.customCards || [];
  window.customCards.push({type: 'neighbourhood-view-card', name: 'Neighbourhood View',
    description: 'An isometric drawing of the streets around your home (from the Neighbourhood View add-on)', preview: false});
  console.info(`%c NEIGHBOURHOOD-VIEW-CARD %c ${VERSION} `, 'background:#2196f3;color:#fff', 'background:#eee;color:#333');
})();
