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
    ground: '#c4dfa0', yard: '#dcd9cf', verge: '#9fcf78', turf: '#86bf5f', turfDark: '#5f9a43',
    soil: '#a8703f', soilDark: '#7d5130', rock: '#8a7d6e', rockDark: '#625849',
    grass: '#9ed37c', wood: '#7dbf63', pitch: '#8cc96f', water: '#8fc6ec', paved: '#cdd1d7',
    road: '#62666e', roadLine: '#f5f5f5', pave: '#d9dbdf', kerb: '#b9bdc4', path: '#f2ede1', pathEdge: '#d6cfbd',
    rail: '#b2aca2', railLine: '#6f6a63', railTie: '#8d877e',
    trunk: '#8c6a48', glass: '#4f6f92', glassLit: '#7fa3c9', door: '#7a5238',
    pin: '#2196f3', pinText: '#ffffff', text: '#6b6b6b',
  };
  // a house's walls (render, brick, stone...) and roofs ([lit, shaded]: tiles, slate...)
  const HOUSE_WALLS = ['#f4ead2', '#f8f6f0', '#ead0a8', '#c9765a', '#b9876a', '#e8dcc2', '#dfe2e6', '#d7a184'];
  const ROOFS = [['#ea8253', '#c8643c'], ['#ea8253', '#c8643c'], ['#7d8996', '#5f6a77'], ['#a3694c', '#83513b'],
    ['#d65a4c', '#ae4339'], ['#5f646b', '#474b51'], ['#e39a5c', '#c27d43']];
  // other buildings: walls [lit, shaded], roof
  const KIND = {
    flats: [['#f3f4f6', '#d1d5db', '#c3c8d0'], ['#efe6d6', '#d4c7b0', '#b9b1a3'], ['#e9eef3', '#c7d0da', '#aab4c0'], ['#d9a98c', '#b98a6e', '#9aa1a9']],
    commercial: [['#f4f4f2', '#d3d5d8', '#b7bdc6'], ['#f2ece1', '#d6cdbd', '#b5aea3'], ['#e6edf2', '#c6d0d8', '#a9b3bd']],
    industrial: [['#e3e7ed', '#c1c7d0', '#a8b0bc'], ['#dfe6dc', '#bfcabb', '#a3ad9f'], ['#e9e2d3', '#cbc2ae', '#aaa293'], ['#d8e2ee', '#b5c3d3', '#97a6b8']],
    small: [['#e8e3d8', '#c9c2b4', '#a9a8a4'], ['#d9cfc0', '#b8ad9c', '#8f8a84']],
    civic: [['#f3ede1', '#d9ceb8', '#bba98f'], ['#e9d6c4', '#cbb39d', '#a4927f']],
    large: [['#eef0f2', '#cfd3d9', '#bcc2cb'], ['#f1ebe0', '#d4cab9', '#b8b0a3']],
  };
  const HOME = {walls: ['#e3f1fd', '#b7d8f5'], roof: ['#42a5f5', '#1e88e5'], flat: '#64b5f6'};
  const SHOPS = ['#e53935', '#1e88e5', '#43a047', '#fdd835', '#8e24aa', '#fb8c00', '#00897b', '#d81b60'];
  const CARS = ['#e53935', '#f5f5f5', '#212121', '#1e88e5', '#9e9e9e', '#fdd835', '#43a047', '#3949ab', '#fb8c00', '#cfd8dc'];
  const GREENS = [['#5fb04d', '#3e8b39', '#8fd170'], ['#4e9f43', '#357a31', '#7cc461'], ['#72bb57', '#4f9a3f', '#a3dc84'],
    ['#3f8f3d', '#2b6b2b', '#62b058'], ['#8cc04e', '#6a9a37', '#b5dc7c']];
  const ELEV = 35 * Math.PI / 180;  // how high above the ground it's looked at from
  const SE = Math.sin(ELEV), CE = Math.cos(ELEV);
  const PAVE = 2.8;  // the pavement each side of a street, m

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
  // a repeatable 0..1 for a building or place (so it looks the same every time)
  function rnd(a, b = 0, salt = 0) {
    let h = (Math.imul(Math.floor(a * 13) | 0, 73856093) ^ Math.imul(Math.floor(b * 17) | 0, 19349663) ^ Math.imul(salt + 1, 83492791)) >>> 0;
    h = Math.imul(h ^ (h >>> 15), 2246822519) >>> 0;
    h = Math.imul(h ^ (h >>> 13), 3266489917) >>> 0;
    return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
  }
  const pick = (arr, r) => arr[Math.floor(r * arr.length) % arr.length];

  /* The torn edge of the chunk: points every few metres round a rounded square, pulled in by a
   * wavy, jagged amount with the odd bite out of it, anticlockwise: [x, y, how deep the earth goes
   * there, how much of that is soil (the rest rock)]. The same for the same place. */
  function outline(H, seed) {
    const R = 34, step = 4, L = 2 * H - 2 * R, perim = 4 * L + 2 * Math.PI * R;
    const ph = [1, 2, 3, 4].map((i) => rnd(seed, i, 30 + i) * 6.28);
    // the rounded square's point and inward direction, s metres round it (anticlockwise from the bottom left)
    const at = (s) => {
      const seg = L + Math.PI * R / 2;
      const k = Math.floor(s / seg) % 4, t = s - k * seg;
      const c = [[-H + R, -H], [H, -H + R], [H - R, H], [-H, H - R]][k];  // where side k starts
      const d = [[1, 0], [0, 1], [-1, 0], [0, -1]][k];
      const inw = [-d[1], d[0]];  // (left of the way round: inwards)
      if (t <= L) return [c[0] + d[0] * t, c[1] + d[1] * t, inw[0], inw[1]];
      // the corner after side k: a quarter circle round its centre
      const cx = c[0] + d[0] * L + inw[0] * R, cy = c[1] + d[1] * L + inw[1] * R;
      const a0 = Math.atan2(-inw[1], -inw[0]), a = a0 + (t - L) / R;
      return [cx + Math.cos(a) * R, cy + Math.sin(a) * R, -Math.cos(a), -Math.sin(a)];
    };
    const out = [];
    for (let s = 0; s < perim - step / 2; s += step) {
      const [x, y, nx, ny] = at(s);
      const n = 0.5 + 0.24 * Math.sin(s / 43 + ph[0]) + 0.16 * Math.sin(s / 15 + ph[1]);
      let inset = 1.5 + 13 * Math.pow(Math.max(0, n), 1.6) + 2.6 * rnd(s, seed, 35);  // (jagged)
      const bite = Math.floor(s / 26);
      if (rnd(bite, seed, 36) < 0.1) inset += 7 * Math.sin(Math.PI * (s - bite * 26) / 26);
      const depth = 13 + 5 * Math.sin(s / 23 + ph[2]) + 7 * rnd(s, seed, 37);  // (a ragged underside)
      out.push([x + nx * inset, y + ny * inset, depth, 0.45 + 0.2 * Math.sin(s / 29 + ph[3])]);
    }
    return out;
  }

  function insideRing(x, y, ring) {
    let hit = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i], [xj, yj] = ring[j];
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) hit = !hit;
    }
    return hit;
  }

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

  // How lit a face is from its outward direction (0 lit .. 1 shaded): light from the left
  function shadeOf(V, nx, ny) {
    const [ax, aw] = V.n(nx, ny), len = Math.hypot(ax, aw) || 1;
    return Math.max(0, Math.min(1, (ax / len + 1) / 2));
  }

  /* The walls of a footprint (anticlockwise) that face the viewer, back ones first:
   * [{d, svg, p, q, len}]. extraTop[i]: a point above edge i's top (a gable). deco(p, q, len, lit)
   * adds windows and doors on a wall. */
  function walls(V, ring, z0, z1, cols, extraTop, deco) {
    const out = [];
    for (let i = 0; i < ring.length; i++) {
      const p = ring[i], q = ring[(i + 1) % ring.length];
      const [, aw] = V.n(q[1] - p[1], -(q[0] - p[0]));
      if (aw >= -1e-6) continue;  // facing away
      const t = shadeOf(V, q[1] - p[1], -(q[0] - p[0]));
      const shade = mix(cols[0], cols[1], t);
      const face = [V.p(p[0], p[1], z0), V.p(q[0], q[1], z0), V.p(q[0], q[1], z1), V.p(p[0], p[1], z1)];
      if (extraTop && extraTop[i]) face.splice(3, 0, extraTop[i]);
      let svg = poly(face, shade, ` stroke="${mix(shade, '#000000', 0.1)}" stroke-width=".25" stroke-linejoin="round"`);
      const len = Math.hypot(q[0] - p[0], q[1] - p[1]);
      if (deco) svg += deco(p, q, len, t, i);
      out.push({d: V.d((p[0] + q[0]) / 2, (p[1] + q[1]) / 2), svg});
    }
    return out.sort((a, b) => b.d - a.d).map((w) => w.svg).join('');
  }

  // A rectangle on a wall, from along a to b (0..1) and z0 to z1, in a colour
  function onWall(V, p, q, a, b, z0, z1, fill) {
    const at = (t, z) => V.p(p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t, z);
    return poly([at(a, z0), at(b, z0), at(b, z1), at(a, z1)], fill);
  }

  // Windows on a wall: rows (one a storey from z0, each storey sh high), every `every` m
  function windows(V, p, q, len, z0, storeys, sh, ww, wh, every, lit, skipMid) {
    const n = Math.floor((len - 0.8) / every);
    if (n < 1 || len < 2.2) return '';
    const fill = mix(C.glassLit, C.glass, lit);
    let svg = '';
    for (let s = 0; s < storeys; s++) {
      const zb = z0 + s * sh + (sh - wh) * 0.55;
      for (let j = 0; j < n; j++) {
        if (skipMid && s === 0 && j === Math.floor(n / 2)) continue;
        const c = (j + 0.5) / n, half = ww / 2 / len;
        svg += onWall(V, p, q, c - half, c + half, zb, zb + wh, fill);
      }
    }
    return svg;
  }

  function gableRoof(V, rect, h, rh, roof, hip) {
    const [A, B, Cc, D] = rect, top = h + rh;
    const lng = Math.hypot(B[0] - A[0], B[1] - A[1]), sh = Math.hypot(Cc[0] - B[0], Cc[1] - B[1]);
    const ux = (B[0] - A[0]) / lng, uy = (B[1] - A[1]) / lng;
    let Ra = [(D[0] + A[0]) / 2, (D[1] + A[1]) / 2], Rb = [(B[0] + Cc[0]) / 2, (B[1] + Cc[1]) / 2];
    if (hip) {
      const inset = Math.min(sh / 2, lng / 2 - 0.3);
      Ra = [Ra[0] + ux * inset, Ra[1] + uy * inset]; Rb = [Rb[0] - ux * inset, Rb[1] - uy * inset];
    }
    const faces = [[A, B, Rb, Ra], [Cc, D, Ra, Rb]];
    if (hip) faces.push([B, Cc, Rb], [D, A, Ra]);
    const svg = faces.map((s) => {
      const t = shadeOf(V, s[1][1] - s[0][1], -(s[1][0] - s[0][0]));
      const [, aw] = V.n(s[1][1] - s[0][1], -(s[1][0] - s[0][0]));
      const col = mix(roof[0], roof[1], Math.min(1, t * 0.6 + (aw > 0 ? 0.4 : 0)));
      const face = s.map((pt, i) => V.p(pt[0], pt[1], i < 2 ? h : top));
      return [V.d((s[0][0] + s[1][0]) / 2, (s[0][1] + s[1][1]) / 2), poly(face, col, ` stroke="${mix(col, '#000000', 0.15)}" stroke-width=".3" stroke-linejoin="round"`)];
    }).sort((a, b) => b[0] - a[0]).map((x) => x[1]).join('');
    const r1 = V.p(Ra[0], Ra[1], top), r2 = V.p(Rb[0], Rb[1], top);
    return {svg: svg + `<line x1="${f(r1[0])}" y1="${f(r1[1])}" x2="${f(r2[0])}" y2="${f(r2[1])}" stroke="${roof[1]}" stroke-width=".5"/>`,
      top: [(r1[0] + r2[0]) / 2, Math.min(r1[1], r2[1])], Ra, Rb, ux, uy, sh};
  }

  // A box: centre, angle (radians), length, width, from z0 to z1, walls [lit, shaded], top colour
  function box(V, cx, cy, ang, L, W, z0, z1, cols, topCol) {
    const ux = Math.cos(ang), uy = Math.sin(ang), vx = -uy, vy = ux;
    const ring = [[cx - ux * L / 2 - vx * W / 2, cy - uy * L / 2 - vy * W / 2], [cx + ux * L / 2 - vx * W / 2, cy + uy * L / 2 - vy * W / 2],
      [cx + ux * L / 2 + vx * W / 2, cy + uy * L / 2 + vy * W / 2], [cx - ux * L / 2 + vx * W / 2, cy - uy * L / 2 + vy * W / 2]];
    return walls(V, ring, z0, z1, cols) + poly(ring.map(([x, y]) => V.p(x, y, z1)), topCol, ` stroke="${mix(topCol, '#000000', 0.12)}" stroke-width=".2"`);
  }

  function house(V, b, isHome) {
    const id = b.id || 0, h = b.h || 5.8;
    const storeys = Math.max(1, Math.round(h / 2.9)), sh = h / storeys;
    const wall = isHome ? HOME.walls[0] : pick(HOUSE_WALLS, rnd(id, 1));
    const cols = isHome ? HOME.walls : [wall, mix(wall, '#000000', 0.16)];
    const roof = isHome ? HOME.roof : pick(ROOFS, rnd(id, 2));
    const hip = rnd(id, 3) < 0.38;
    const rect = b.rect, [A, B, Cc] = rect;
    const lng = Math.hypot(B[0] - A[0], B[1] - A[1]), short = Math.hypot(Cc[0] - B[0], Cc[1] - B[1]);
    const rh = b.rh || Math.min(4.5, Math.max(1.5, short * 0.38));
    const Ra = [(rect[3][0] + A[0]) / 2, (rect[3][1] + A[1]) / 2], Rb = [(B[0] + Cc[0]) / 2, (B[1] + Cc[1]) / 2];
    const gables = hip ? null : [null, V.p(Rb[0], Rb[1], h + rh), null, V.p(Ra[0], Ra[1], h + rh)];
    let doorDone = false;
    const deco = (p, q, len, lit, i) => {
      if (i % 2 === 1) return len > 4.5 ? windows(V, p, q, len, 0, storeys, sh, 1.0, 1.15, 3.4, lit) : '';  // (the ends)
      let s = windows(V, p, q, len, 0, storeys, sh, 1.15, 1.25, 3.0, lit, !doorDone);
      if (!doorDone) {
        const half = 0.5 / len;
        s += onWall(V, p, q, 0.5 - half, 0.5 + half, 0, 2.1, C.door);
        doorDone = true;
      }
      return s;
    };
    let svg = walls(V, rect, 0, h, cols, gables, deco);
    const r = gableRoof(V, rect, h, rh, roof, hip);
    // a chimney on some, near one end of the ridge
    let chim = '';
    if (rnd(id, 4) < 0.45 && lng > 5) {
      const e = rnd(id, 5) < 0.5 ? 1 : -1, t = 0.3;
      const cx = (r.Ra[0] + r.Rb[0]) / 2 + r.ux * e * lng * t, cy = (r.Ra[1] + r.Rb[1]) / 2 + r.uy * e * lng * t;
      chim = box(V, cx, cy, Math.atan2(r.uy, r.ux), 0.8, 0.6, h + rh * 0.4, h + rh + 0.8, [mix(cols[0], '#9a6b55', 0.5), mix(cols[1], '#6f4b3c', 0.5)], '#6d5a50');
    }
    // (the chimney drawn before the roof if it's behind the ridge from here, after it if in front)
    svg += r.svg + chim;
    return {svg, top: r.top};
  }

  function block(V, b, isHome) {
    const id = b.id || 0, h = b.h || 8, k = b.k;
    const set = isHome ? [HOME.walls[0], HOME.walls[1], HOME.flat] : pick(KIND[k] || KIND.large, rnd(id, 1));
    const cols = [set[0], set[1]];
    const storeys = Math.max(1, Math.round(h / 3.1)), sh = h / storeys;
    const shop = k === 'commercial' ? pick(SHOPS, rnd(id, 6)) : null;
    const deco = (p, q, len, lit) => {
      if (k === 'small') return '';
      if (k === 'industrial') return windows(V, p, q, len, h * 0.62, 1, h * 0.3, 2.4, 0.9, 6, lit);
      if (shop) {
        // a shop front: glass below, a coloured fascia, then windows above
        let s = onWall(V, p, q, 0.04, 0.96, 0.3, 2.6, mix(C.glassLit, C.glass, lit)) + onWall(V, p, q, 0, 1, 2.6, 3.3, mix(shop, '#000000', lit * 0.2));
        if (storeys > 1) s += windows(V, p, q, len, 3.3, storeys - 1, (h - 3.3) / (storeys - 1), 1.4, 1.4, 3.2, lit);
        return s;
      }
      return windows(V, p, q, len, 0, storeys, sh, k === 'flats' ? 1.4 : 1.6, 1.45, k === 'flats' ? 3.0 : 3.6, lit);
    };
    let svg = walls(V, b.p, 0, h, cols, null, deco);
    const roofCol = set[2];
    svg += poly(b.p.map(([x, y]) => V.p(x, y, h)), roofCol, ` stroke="${mix(roofCol, '#000000', 0.22)}" stroke-width=".9" stroke-linejoin="round"`);
    // things on the roof: an air conditioning unit or a stair tower on some bigger ones
    const [cx, cy] = centroid(b.p);
    if (k !== 'small' && Math.abs(b.p.length) && rnd(id, 7) < 0.55) {
      const ang = Math.atan2(b.p[1][1] - b.p[0][1], b.p[1][0] - b.p[0][0]);
      svg += box(V, cx + (rnd(id, 8) - 0.5) * 3, cy + (rnd(id, 9) - 0.5) * 3, ang, 2.6, 1.8, h, h + 1.3, ['#e9ecef', '#c3c8ce'], '#d5d9de');
    }
    return {svg, top: V.p(cx, cy, h + 1.3)};
  }

  function building(V, b, isHome) {
    return b.r === 'gable' && b.rect ? house(V, b, isHome) : block(V, b, isHome);
  }

  // Trees: round (low-poly, two-tone), pointed (stacked cones) or a bush; size from s
  function tree(V, [x, y, s]) {
    s = s || 1;
    const kind = rnd(x, y, 11), g = pick(GREENS, rnd(x, y, 12));
    if (kind < 0.12) {  // a bush
      const r = 1.3 * s, c = V.p(x, y, r * 0.7);
      return `<circle cx="${f(c[0])}" cy="${f(c[1])}" r="${f(r)}" fill="${g[1]}"/><circle cx="${f(c[0] - r * 0.2)}" cy="${f(c[1] - r * 0.25)}" r="${f(r * 0.7)}" fill="${g[0]}"/>`;
    }
    const base = V.p(x, y, 0);
    if (kind < 0.36) {  // a conifer
      const ht = 7 * s, r = 1.9 * s, t0 = V.p(x, y, ht * 0.15);
      let svg = `<line x1="${f(base[0])}" y1="${f(base[1])}" x2="${f(t0[0])}" y2="${f(t0[1])}" stroke="${C.trunk}" stroke-width="${f(r * 0.35)}"/>`;
      for (let i = 0; i < 3; i++) {
        const zb = ht * (0.15 + i * 0.24), zt = zb + ht * 0.45, w = r * (1 - i * 0.22);
        const b0 = V.p(x, y, zb), tp = V.p(x, y, zt);
        svg += poly([[b0[0] - w, b0[1]], [tp[0], tp[1]], [b0[0], b0[1] + w * 0.35]], mix(g[1], '#2c662c', 0.15))
          + poly([[b0[0], b0[1] + w * 0.35], [tp[0], tp[1]], [b0[0] + w, b0[1]]], mix(g[1], '#163b16', 0.45));
      }
      return svg;
    }
    // a round tree
    const r = 2.5 * s, trunkTop = 2.4 * s, t = V.p(x, y, trunkTop), c = V.p(x, y, trunkTop + r * 0.9);
    return `<line x1="${f(base[0])}" y1="${f(base[1])}" x2="${f(t[0])}" y2="${f(t[1])}" stroke="${C.trunk}" stroke-width="${f(Math.max(0.35, r * 0.24))}"/>`
      + `<circle cx="${f(c[0])}" cy="${f(c[1])}" r="${f(r)}" fill="${g[1]}"/>`
      + `<path d="M${f(c[0] - r)} ${f(c[1])}A${f(r)} ${f(r)} 0 0 1 ${f(c[0] + r * 0.6)} ${f(c[1] - r * 0.8)}L${f(c[0] - r * 0.1)} ${f(c[1] + r * 0.2)}Z" fill="${g[0]}"/>`
      + `<circle cx="${f(c[0] - r * 0.42)}" cy="${f(c[1] - r * 0.4)}" r="${f(r * 0.28)}" fill="${g[2]}"/>`;
  }

  // A parked car: a body and a cabin, as boxes
  function car(V, [x, y, ang, ci]) {
    const a = ang * Math.PI / 180, col = CARS[ci % CARS.length];
    return box(V, x, y, a, 4.2, 1.8, 0.25, 1.0, [col, mix(col, '#000000', 0.3)], mix(col, '#ffffff', 0.12))
      + box(V, x - Math.cos(a) * 0.2, y - Math.sin(a) * 0.2, a, 2.2, 1.6, 1.0, 1.55, ['#7d9fc4', '#4d6b8c'], mix(col, '#ffffff', 0.2));
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
    // the chunk of ground, torn out: its earth sides (those facing the viewer, back ones first),
    // then its top, with a lip of turf
    const edge = outline(H, (scene.lat || 0) * 1000 + (scene.lon || 0) * 7000);
    const sides = [];
    for (let i = 0; i < edge.length; i++) {
      const p = edge[i], q = edge[(i + 1) % edge.length];
      const [, aw] = V.n(q[1] - p[1], -(q[0] - p[0]));
      if (aw >= 0) continue;
      const t = shadeOf(V, q[1] - p[1], -(q[0] - p[0]));
      const turf = 0.9, mid = (p[2] + q[2]) / 2;
      const quad = (z0p, z0q, z1p, z1q, col) => poly([V.p(p[0], p[1], z0p), V.p(q[0], q[1], z0q), V.p(q[0], q[1], z1q), V.p(p[0], p[1], z1p)], col, ` stroke="${col}" stroke-width=".4" stroke-linejoin="round"`);
      sides.push([V.d((p[0] + q[0]) / 2, (p[1] + q[1]) / 2),
        quad(-turf, -turf, -p[2], -q[2], mix(C.rock, C.rockDark, t))
        + quad(-turf, -turf, -p[2] * p[3], -q[2] * q[3], mix(C.soil, C.soilDark, t))
        + quad(0, 0, -turf, -turf, mix(C.turf, C.turfDark, t))
        + (mid > 10 && rnd(p[0], p[1], 21) < 0.35 ? (() => {
          // a stone in the earth
          const a = V.p((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, -mid * (0.55 + 0.35 * rnd(p[0], p[1], 23))), r = 0.6 + rnd(p[0], p[1], 22) * 1.2;
          return `<ellipse cx="${f(a[0])}" cy="${f(a[1])}" rx="${f(r)}" ry="${f(r * 0.7)}" fill="${mix(C.rockDark, '#000000', 0.15)}"/>`;
        })() : '')]);
    }
    sides.sort((a, b) => b[0] - a[0]);
    for (const sd of sides) out.push(sd[1]);
    const topPts = edge.map(([x, y]) => V.p(x, y, 0));
    out.push(poly(topPts, C.ground, ` stroke="${C.turf}" stroke-width="1.6" stroke-linejoin="round"`));
    // the ground: areas, water, roads, railways (kept to the board: a road's end doesn't stick out)
    const clip = 'nvclip' + Math.random().toString(36).slice(2, 8);
    out.push(`<clipPath id="${clip}"><polygon points="${pts(topPts)}"/></clipPath><g clip-path="url(#${clip})">`);
    for (const a of scene.areas || []) out.push(poly(a.p.map(([x, y]) => V.p(x, y, 0)), C[a.k] || C.grass));
    for (const w of scene.water || []) out.push(`<path d="${line(V, w.p)}" fill="none" stroke="${C.water}" stroke-width="${f(w.w)}" stroke-linecap="round" stroke-linejoin="round"/>`);
    const roads = scene.roads || [];
    const paths = roads.filter((r) => r.k === 'path'), cars = roads.filter((r) => r.k !== 'path');
    for (const r of paths) out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.pathEdge}" stroke-width="${f(r.w + 0.8)}" stroke-linecap="round" stroke-linejoin="round"/>`);
    for (const r of paths) out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.path}" stroke-width="${f(r.w)}" stroke-linecap="round" stroke-linejoin="round"/>`);
    // streets: a pavement each side (with its kerb), the road, its markings
    const streets = cars.filter((r) => r.k !== 'service');
    for (const r of streets) out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.kerb}" stroke-width="${f(r.w + PAVE * 2 + 0.6)}" stroke-linecap="round" stroke-linejoin="round"/>`);
    for (const r of streets) out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.pave}" stroke-width="${f(r.w + PAVE * 2)}" stroke-linecap="round" stroke-linejoin="round"/>`);
    // (a grass verge between the pavement and the kerb on residential streets)
    for (const r of streets.filter((r) => r.k === 'minor')) out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.verge}" stroke-width="${f(r.w + 2.4)}" stroke-linecap="round" stroke-linejoin="round"/>`);
    for (const r of cars) out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${mix(C.road, '#ffffff', 0.35)}" stroke-width="${f(r.w + 0.5)}" stroke-linecap="round" stroke-linejoin="round"/>`);
    for (const r of cars) out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.road}" stroke-width="${f(r.w)}" stroke-linecap="round" stroke-linejoin="round"/>`);
    for (const r of streets) out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.roadLine}" stroke-width="${r.k === 'major' ? '.45' : '.3'}" stroke-dasharray="${r.k === 'major' ? '4 3' : '2.5 4'}" opacity=".85"/>`);
    for (const r of scene.rails || []) {
      out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.rail}" stroke-width="${f(r.w)}" stroke-linecap="butt" stroke-linejoin="round"/>`);
      out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.railTie}" stroke-width="${f(r.w * 0.55)}" stroke-dasharray=".6 1.4"/>`);
      out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.railLine}" stroke-width=".35"/>`);
    }
    out.push('</g>');
    // the buildings and trees, back to front
    const things = [];
    let pin = null;
    // (only what's on the chunk: a building the torn edge cuts through isn't drawn)
    const on = (x, y) => insideRing(x, y, edge);
    for (const b of scene.buildings || []) {
      const [cx, cy] = centroid(b.p), isHome = home.id != null && b.id === home.id;
      if (!isHome && !b.p.every(([x, y]) => on(x, y))) continue;
      const d = building(V, b, isHome);
      if (isHome) pin = d.top;
      const attrs = opts.pick ? ` data-id="${b.id}" class="bld"` : '';
      things.push([V.d(cx, cy), `<g${attrs}>${d.svg}</g>`]);
    }
    for (const t of scene.trees || []) if (on(t[0], t[1])) things.push([V.d(t[0], t[1]), tree(V, t)]);
    for (const c of scene.cars || []) if (on(c[0], c[1])) things.push([V.d(c[0], c[1]), car(V, c)]);
    things.sort((a, b) => b[0] - a[0]);
    for (const t of things) out.push(t[1]);
    // the pin over your home
    if (!pin) pin = V.p(home.x || 0, home.y || 0, 0);
    if (!opts.hideLabel) {
      // (the same size on the screen however far it's zoomed in)
      const zs = Math.pow(opts.zoom || 1, 0.9);
      const label = esc(opts.label || 'HOME'), fs = H * 0.034 / zs, w = label.length * fs * 0.66 + fs * 1.6, ph = fs * 1.9;
      const top = pin[1] - H * 0.13 / zs;
      out.push(`<line x1="${f(pin[0])}" y1="${f(pin[1])}" x2="${f(pin[0])}" y2="${f(top)}" stroke="${C.pin}" stroke-width="${f(fs * 0.14)}"/>`
        + `<circle cx="${f(pin[0])}" cy="${f(pin[1])}" r="${f(fs * 0.3)}" fill="${C.pin}"/>`
        + `<rect x="${f(pin[0] - w / 2)}" y="${f(top - ph)}" width="${f(w)}" height="${f(ph)}" rx="${f(ph / 2)}" fill="${C.pin}" stroke="#ffffff" stroke-width="${f(fs * 0.12)}"/>`
        + `<text x="${f(pin[0])}" y="${f(top - ph / 2)}" fill="${C.pinText}" font-size="${f(fs)}" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-weight="700" letter-spacing="${f(fs * 0.08)}" text-anchor="middle" dominant-baseline="central">${label}</text>`);
    }
    // the box around it all (for the viewBox)
    const corners = [];
    for (const [x, y, dp] of edge) corners.push(V.p(x, y, 0), V.p(x, y, -dp));
    const xs = corners.map((c) => c[0]), ys = corners.map((c) => c[1]).concat([pin[1] - H * 0.2]);
    const m = H * 0.04, x0 = Math.min(...xs) - m, y0 = Math.min(...ys) - m, w = Math.max(...xs) - x0 + m, h = Math.max(...ys) - y0 + m * 2.2;
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${f(x0)} ${f(y0)} ${f(w)} ${f(h)}" data-box="${f(x0)} ${f(y0)} ${f(w)} ${f(h)}" data-pin="${f(pin[0])} ${f(pin[1] - H * 0.06 / Math.pow(opts.zoom || 1, 0.9))}" data-zoom="${opts.zoom || 1}" preserveAspectRatio="xMidYMid meet" style="width:100%;height:100%;display:block" role="img" aria-label="The streets around your home">${out.join('')}</svg>`;
  }

  /* Fits the drawing to its box: all of it where the box is about its shape; in a much narrower
   * (or flatter) box, e.g. a phone held upright, closer in around your home (up to MAX_ZOOM),
   * rather than tiny in the middle. Done again as the box changes size. */
  const MAX_ZOOM = 2.4, MAX_TOTAL = 10;
  function fit(el) {
    const svg = el.querySelector('svg');
    if (!svg) return;
    const [x0, y0, w, h] = svg.dataset.box.split(' ').map(Number), [px, py] = svg.dataset.pin.split(' ').map(Number);
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const boxAr = r.width / r.height, ar = w / h;
    // (closer in for a box much narrower or flatter than the drawing, on top of the zoom chosen)
    const shapeZ = Math.min(MAX_ZOOM, Math.max(1, boxAr < ar ? ar / boxAr : boxAr / ar) ** 0.75);
    const z = Math.min(MAX_TOTAL, (Number(svg.dataset.zoom) || 1) * Math.sqrt(shapeZ));
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

  // Zoom (the + and − buttons): steps in from the whole square, remembered on each device
  // (starting at 2.6×: your street and the ones round it, as close as in a game; − shows the whole square)
  const ZOOMS = [1, 1.6, 2.6, 4, 6, 9];
  const ZOOM_DEFAULT = 2;
  const ZOOM_KEY = 'neighbourhood-view-zoom2';
  function zoomStep(delta) {
    let i = ZOOM_DEFAULT;
    try { const v = localStorage.getItem(ZOOM_KEY); if (v !== null && v !== '') i = Number(v) || 0; } catch (e) { /* (not kept) */ }
    if (delta) {
      i = Math.max(0, Math.min(ZOOMS.length - 1, i + delta));
      try { localStorage.setItem(ZOOM_KEY, String(i)); } catch (e) { /* (not kept) */ }
    }
    return ZOOMS[Math.max(0, Math.min(ZOOMS.length - 1, i))];
  }

  window.NeighbourhoodView = {draw, render, fit, zoom: zoomStep, version: VERSION};

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
        <div class="tools"><button data-z="-1" title="Zoom out" aria-label="Zoom out">−</button><button data-z="1" title="Zoom in" aria-label="Zoom in">+</button><button data-r="-1" title="Turn left" aria-label="Turn left">⟲</button><button data-r="1" title="Turn right" aria-label="Turn right">⟳</button></div></ha-card>`;
      this._root.querySelector('.tools').addEventListener('click', (e) => {
        const d = (e.target && e.target.dataset) || {}, r = Number(d.r), z = Number(d.z);
        if (r) setRot((getRot() + r + 4) % 4);
        else if (z) zoomStep(z);
        else return;
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
      render(this._root.querySelector('.map'), s, {rot: getRot(), zoom: zoomStep(0), label: String(label).toUpperCase()});
      this._msg('');
    }
  }

  customElements.define('neighbourhood-view-card', NeighbourhoodViewCard);
  window.customCards = window.customCards || [];
  window.customCards.push({type: 'neighbourhood-view-card', name: 'Neighbourhood View',
    description: 'An isometric drawing of the streets around your home (from the Neighbourhood View add-on)', preview: false});
  console.info(`%c NEIGHBOURHOOD-VIEW-CARD %c ${VERSION} `, 'background:#2196f3;color:#fff', 'background:#eee;color:#333');
})();
