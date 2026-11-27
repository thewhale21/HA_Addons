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
      // which way shadows fall on the ground, per metre of height (the sun's behind, to the left)
      s: [(ca - 0.55 * sa) * 0.75, (-sa - 0.55 * ca) * 0.75],
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
  /* What's being drawn now: night (lights on in windows), how likely a window in the building
   * being drawn is lit (CTX.lit: 0..1), and whether your house's chimney smokes (someone's home). */
  const CTX = {night: false, lit: 0, smoke: false, seed: 0, season: 'summer', snow: false, wet: false, windy: false, hail: false, leaves: 0};
  const SNOW = '#f2f5f9';
  const snowy = (c, k = 0.8) => (CTX.snow ? mix(c, SNOW, k) : c);
  // the season, from the month (Northern Hemisphere): trees turn in autumn, go bare-ish in winter,
  // and some blossom in spring
  function season(month) {
    return [2, 3, 4].includes(month) ? 'spring' : [5, 6, 7].includes(month) ? 'summer' : [8, 9, 10].includes(month) ? 'autumn' : 'winter';
  }
  const AUTUMN = [['#e8a33c', '#c27a22', '#f6c768'], ['#d9672e', '#a84a1f', '#f08f55'], ['#c9442f', '#94301f', '#e56a52'], ['#d8b43a', '#a8891f', '#f0d46a']];
  const WINTER = [['#8f8a6c', '#6e6a52', '#a8a386'], ['#7f7a63', '#615d4a', '#9a957b']];
  const BLOSSOM = [['#f4b6cf', '#d98aac', '#fbd6e4'], ['#f7f1f4', '#dcc9d2', '#ffffff']];
  const LIGHT = '#ffd36b', LIGHT2 = '#ffe9a8';  // (kept bright at night: see nightTint)

  function windows(V, p, q, len, z0, storeys, sh, ww, wh, every, lit, skipMid) {
    const n = Math.floor((len - 0.8) / every);
    if (n < 1 || len < 2.2) return '';
    const glass = mix(C.glassLit, C.glass, lit);
    let svg = '';
    for (let s = 0; s < storeys; s++) {
      const zb = z0 + s * sh + (sh - wh) * 0.55;
      for (let j = 0; j < n; j++) {
        if (skipMid && s === 0 && j === Math.floor(n / 2)) continue;
        const c = (j + 0.5) / n, half = ww / 2 / len;
        const on = CTX.night && CTX.lit > 0 && rnd(p[0] + c * 7, p[1] + s * 3, CTX.seed + j) < CTX.lit;
        svg += onWall(V, p, q, c - half, c + half, zb, zb + wh, on ? (lit > 0.5 ? LIGHT : LIGHT2) : glass);
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
    // (at night: your house lit if someone's home, dark if not; about a third of the others lit)
    CTX.lit = isHome ? (CTX.homeLit ? 0.85 : 0) : (rnd(id, 40) < 0.55 ? 0.45 : 0);
    CTX.seed = id % 997;
    const storeys = Math.max(1, Math.round(h / 2.9)), sh = h / storeys;
    const wall = isHome ? HOME.walls[0] : pick(HOUSE_WALLS, rnd(id, 1));
    const cols = isHome ? HOME.walls : [wall, mix(wall, '#000000', 0.16)];
    const roof = (isHome ? HOME.roof : pick(ROOFS, rnd(id, 2))).map((c) => snowy(c, isHome ? 0.6 : 0.8));
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
    if ((isHome || rnd(id, 4) < 0.45) && lng > 5) {
      const e = rnd(id, 5) < 0.5 ? 1 : -1, t = 0.3;
      const cx = (r.Ra[0] + r.Rb[0]) / 2 + r.ux * e * lng * t, cy = (r.Ra[1] + r.Rb[1]) / 2 + r.uy * e * lng * t;
      chim = box(V, cx, cy, Math.atan2(r.uy, r.ux), 0.8, 0.6, h + rh * 0.4, h + rh + 0.8, [mix(cols[0], '#9a6b55', 0.5), mix(cols[1], '#6f4b3c', 0.5)], '#6d5a50');
      // someone's home: smoke from the chimney (by day; at night the lights say so)
      if (isHome && CTX.smoke) {
        const t = V.p(cx, cy, h + rh + 1);
        for (let k = 0; k < 3; k++) {
          chim += `<circle cx="${f(t[0])}" cy="${f(t[1])}" r="1" fill="#f2f2f2" opacity="0">`
            + `<animate attributeName="cy" from="${f(t[1])}" to="${f(t[1] - 9)}" dur="3.6s" begin="${k * 1.2}s" repeatCount="indefinite"/>`
            + `<animate attributeName="cx" from="${f(t[0])}" to="${f(t[0] + 2.5)}" dur="3.6s" begin="${k * 1.2}s" repeatCount="indefinite"/>`
            + `<animate attributeName="r" from=".7" to="2.6" dur="3.6s" begin="${k * 1.2}s" repeatCount="indefinite"/>`
            + `<animate attributeName="opacity" values="0;.85;0" dur="3.6s" begin="${k * 1.2}s" repeatCount="indefinite"/></circle>`;
        }
      }
    }
    // (the chimney drawn before the roof if it's behind the ridge from here, after it if in front)
    svg += r.svg + roofBits(V, b, rect, h, rh, r, isHome, cols, roof) + chim;
    return {svg, top: r.top};
  }

  /* On the roof face that faces you: your solar panels (glinting while they produce), others'
   * skylights, dormers and satellite dishes; Christmas lights along the eaves in December */
  function roofBits(V, b, rect, h, rh, r, isHome, cols, roof) {
    const [A, B, Cc, D] = rect, id = b.id || 0;
    const [, aw] = V.n(B[1] - A[1], -(B[0] - A[0]));
    // (the face's eave P0→P1 and its ridge Q0→Q1)
    const [P0, P1, Q0, Q1] = aw < 0 ? [A, B, r.Ra, r.Rb] : [Cc, D, r.Rb, r.Ra];
    const FP = (tt, u, dz = 0) => {
      const ex = P0[0] + (P1[0] - P0[0]) * tt, ey = P0[1] + (P1[1] - P0[1]) * tt, rx = Q0[0] + (Q1[0] - Q0[0]) * tt, ry = Q0[1] + (Q1[1] - Q0[1]) * tt;
      return V.p(ex + (rx - ex) * u, ey + (ry - ey) * u, h + rh * u + dz);
    };
    const quad = (t0, t1, u0, u1, dz = 0.05) => [FP(t0, u0, dz), FP(t1, u0, dz), FP(t1, u1, dz), FP(t0, u1, dz)];
    const len = Math.hypot(P1[0] - P0[0], P1[1] - P0[1]);
    let s = '';
    if (isHome && CTX.energy && CTX.energy.solar !== null && CTX.energy.solar !== undefined) {
      s += poly(quad(0.1, 0.9, 0.12, 0.8), '#1f3558', ' stroke="#9bb6d8" stroke-width=".12"');
      for (let k = 1; k < 5; k++) { const a = FP(0.1 + 0.16 * k, 0.12, 0.06), c = FP(0.1 + 0.16 * k, 0.8, 0.06); s += `<line x1="${f(a[0])}" y1="${f(a[1])}" x2="${f(c[0])}" y2="${f(c[1])}" stroke="#5c7fa8" stroke-width=".06"/>`; }
      { const a = FP(0.1, 0.46, 0.06), c = FP(0.9, 0.46, 0.06); s += `<line x1="${f(a[0])}" y1="${f(a[1])}" x2="${f(c[0])}" y2="${f(c[1])}" stroke="#5c7fa8" stroke-width=".06"/>`; }
      if (CTX.energy.solar && !CTX.night) s += poly(quad(0.1, 0.9, 0.12, 0.8, 0.07), '#ffffff', ' opacity="0"').replace('/>', '><animate attributeName="opacity" values="0;0;.55;0" keyTimes="0;.6;.75;1" dur="4s" repeatCount="indefinite"/></polygon>');
    } else if (!isHome) {
      if (rnd(id, 31) < 0.22) s += poly(quad(0.28, 0.4, 0.3, 0.62), '#3d5a78', ' stroke="#e0e0e0" stroke-width=".1"');
      if (rnd(id, 32) < 0.14 && rh >= 2.2 && len > 6) {
        // a dormer: a little wall with a window, and its roof back to the slope
        const zt = h + rh * 0.78, base = (tt) => FP(tt, 0.18), up = (tt) => { const q = base(tt); return [q[0], q[1] - (zt - (h + rh * 0.18)) * CE]; };
        s += poly([base(0.4), base(0.6), up(0.6), up(0.4)], cols[0], ` stroke="${mix(cols[0], '#000000', 0.15)}" stroke-width=".1"`);
        const wi = (tt, k) => { const a = base(tt), c = up(tt); return [a[0] + (c[0] - a[0]) * k, a[1] + (c[1] - a[1]) * k]; };
        s += poly([wi(0.44, 0.2), wi(0.56, 0.2), wi(0.56, 0.75), wi(0.44, 0.75)], CTX.night && rnd(id, 33) < 0.5 ? LIGHT : C.glass);
        s += poly([up(0.38), up(0.62), FP(0.62, 0.78), FP(0.38, 0.78)], roof[1]);
      }
      if (rnd(id, 34) < 0.1) {
        const a = FP(0.86, 0.5, 0.3), c = FP(0.86, 0.5);
        s += `<line x1="${f(a[0])}" y1="${f(a[1])}" x2="${f(c[0])}" y2="${f(c[1])}" stroke="#9aa0a6" stroke-width=".08"/><ellipse cx="${f(a[0])}" cy="${f(a[1])}" rx=".45" ry=".38" fill="#d3d7db" stroke="#9aa0a6" stroke-width=".06"/>`;
      }
    }
    if (CTX.occ && CTX.occ.xmas && (isHome || rnd(id, 35) < 0.4)) {
      // lights along the eaves (twinkling at night)
      const n = Math.max(3, Math.floor(len / 0.6));
      for (let k = 0; k <= n; k++) {
        const q = FP(k / n, 0, -0.1), col = XMAS[(k + id) % 4];
        s += `<circle cx="${f(q[0])}" cy="${f(q[1])}" r="${CTX.night ? '.2' : '.14'}" fill="${col}"${CTX.night && k % 3 === 0 ? `><animate attributeName="opacity" values="1;.25;1" dur="${(1 + rnd(id, k, 36)).toFixed(1)}s" repeatCount="indefinite"/></circle>` : '/>'}`;
      }
      if (CTX.night) { const m = FP(0.5, 0, -0.1); s += `<ellipse cx="${f(m[0])}" cy="${f(m[1])}" rx="${f(len * 0.6)}" ry="1.4" fill="rgb(255,200,120)" opacity=".12"/>`; }
    }
    return s;
  }

  function block(V, b, isHome) {
    const id = b.id || 0, h = b.h || 8, k = b.k;
    CTX.lit = isHome ? (CTX.homeLit ? 0.85 : 0) : k === 'industrial' ? 0.1 : k === 'flats' ? 0.5 : 0.3;
    CTX.seed = id % 997;
    const lm = isHome ? null : b.lm;
    const set = isHome ? [HOME.walls[0], HOME.walls[1], HOME.flat] : lm === 'church' ? ['#e2d8c6', '#bfb29c', '#6b6f75']
      : lm === 'school' ? ['#f0dcc4', '#d1b99f', '#8b9196'] : lm === 'pub' ? ['#f3ead6', '#d7c8a8', '#5f646b'] : pick(KIND[k] || KIND.large, rnd(id, 1));
    const cols = [set[0], set[1]];
    const storeys = Math.max(1, Math.round(h / 3.1)), sh = h / storeys;
    const shop = lm === 'pub' ? '#2e5d3a' : k === 'commercial' && !lm ? pick(SHOPS, rnd(id, 6)) : null;
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
    const roofCol = snowy(set[2]);
    svg += poly(b.p.map(([x, y]) => V.p(x, y, h)), roofCol, ` stroke="${mix(roofCol, '#000000', 0.22)}" stroke-width=".9" stroke-linejoin="round"`);
    // things on the roof: an air conditioning unit or a stair tower on some bigger ones
    const [cx, cy] = centroid(b.p);
    if (lm) svg += landmarkBits(V, b, h, lm, cx, cy);
    else if (k !== 'small' && Math.abs(b.p.length) && rnd(id, 7) < 0.55) {
      const ang = Math.atan2(b.p[1][1] - b.p[0][1], b.p[1][0] - b.p[0][0]);
      svg += box(V, cx + (rnd(id, 8) - 0.5) * 3, cy + (rnd(id, 9) - 0.5) * 3, ang, 2.6, 1.8, h, h + 1.3, ['#e9ecef', '#c3c8ce'], '#d5d9de');
    }
    return {svg, top: V.p(cx, cy, h + 1.3)};
  }

  /* A church's tower and spire, a school's flag, a pub's hanging sign and picnic benches */
  function landmarkBits(V, b, h, lm, cx, cy) {
    const [vx, vy] = b.p[0], [wx, wy] = b.p[1];
    let s = '';
    if (lm === 'church') {
      const tx = cx + (vx - cx) * 0.62, ty = cy + (vy - cy) * 0.62, ang = Math.atan2(wy - vy, wx - vx), T = 4.2, tz = h + 6, sz = tz + 11;
      s += box(V, tx, ty, ang, T, T, 0, tz, ['#e2d8c6', '#bfb29c'], '#c9bda8');
      const c = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([a, bb]) => [tx + (Math.cos(ang) * a - Math.sin(ang) * bb) * T / 2, ty + (Math.sin(ang) * a + Math.cos(ang) * bb) * T / 2]);
      const apex = V.p(tx, ty, sz), faces = [];
      for (let i = 0; i < 4; i++) {
        const p = c[i], q = c[(i + 1) % 4], [, aw] = V.n(q[1] - p[1], -(q[0] - p[0]));
        if (aw < 0) faces.push(poly([V.p(p[0], p[1], tz), V.p(q[0], q[1], tz), apex], mix('#6b6f75', '#3e4248', shadeOf(V, q[1] - p[1], -(q[0] - p[0])))));
      }
      s += faces.join('') + `<line x1="${f(apex[0])}" y1="${f(apex[1])}" x2="${f(apex[0])}" y2="${f(apex[1] - 2.2)}" stroke="#d4af37" stroke-width=".22"/><line x1="${f(apex[0] - 0.7)}" y1="${f(apex[1] - 1.5)}" x2="${f(apex[0] + 0.7)}" y2="${f(apex[1] - 1.5)}" stroke="#d4af37" stroke-width=".22"/>`;
      const cl = V.p(tx, ty, tz - 1.6);
      s += `<circle cx="${f(cl[0])}" cy="${f(cl[1])}" r=".75" fill="#f5f0e0" stroke="#3e4248" stroke-width=".1"/>`;
    } else if (lm === 'school') {
      const a = V.p(wx, wy, h), top = V.p(wx, wy, h + 6);
      const flag = (k) => `M${f(top[0])} ${f(top[1])}q1.2 ${k} 2.6 0v1.6q-1.4 ${-k} -2.6 0z`;
      s += `<line x1="${f(a[0])}" y1="${f(a[1])}" x2="${f(top[0])}" y2="${f(top[1])}" stroke="#9aa0a6" stroke-width=".14"/>`
        + `<path d="${flag(0.5)}" fill="#1e88e5"><animate attributeName="d" values="${flag(0.5)};${flag(-0.5)};${flag(0.5)}" dur="1.6s" repeatCount="indefinite"/></path>`;
    } else if (lm === 'pub') {
      // the sign, on a bracket off the corner
      const L = Math.hypot(wx - vx, wy - vy) || 1, nx = (wy - vy) / L, ny = -(wx - vx) / L;
      const bx = vx + (wx - vx) / L * 1.2 + nx * 1.1, by = vy + (wy - vy) / L * 1.2 + ny * 1.1;
      const w0 = V.p(vx + (wx - vx) / L * 1.2, vy + (wy - vy) / L * 1.2, 4.2), arm = V.p(bx, by, 4.2), b0 = V.p(bx, by, 4.1), b1 = V.p(bx, by, 2.9);
      s += `<line x1="${f(w0[0])}" y1="${f(w0[1])}" x2="${f(arm[0])}" y2="${f(arm[1])}" stroke="#2b2b2b" stroke-width=".14"/>`
        + `<rect x="${f(b0[0] - 0.55)}" y="${f(b0[1])}" width="1.1" height="${f(b1[1] - b0[1])}" fill="#7a1f1f" stroke="#e2b547" stroke-width=".12"/>`
        + `<circle cx="${f(b0[0])}" cy="${f((b0[1] + b1[1]) / 2)}" r=".25" fill="#e2b547"/>`;
      for (let k = 0; k < 2; k++) {
        const px = vx + (wx - vx) / L * (3 + k * 3.2) + nx * 3, py = vy + (wy - vy) / L * (3 + k * 3.2) + ny * 3, ang = Math.atan2(wy - vy, wx - vx);
        s += box(V, px, py, ang, 1.8, 0.8, 0.65, 0.75, ['#a07a52', '#7b5c3e'], '#b08a5f') + box(V, px + nx * 0.75, py + ny * 0.75, ang, 1.8, 0.3, 0.38, 0.45, ['#a07a52', '#7b5c3e'], '#b08a5f')
          + box(V, px - nx * 0.75, py - ny * 0.75, ang, 1.8, 0.3, 0.38, 0.45, ['#a07a52', '#7b5c3e'], '#b08a5f');
      }
    }
    return s;
  }

  function building(V, b, isHome) {
    return b.r === 'gable' && b.rect ? house(V, b, isHome) : block(V, b, isHome);
  }

  // Trees: round (low-poly, two-tone), pointed (stacked cones) or a bush; size from s
  function tree(V, [x, y, s]) {
    s = s || 1;
    const kind = rnd(x, y, 11), turn = rnd(x, y, 13);
    let g = pick(GREENS, rnd(x, y, 12));
    if (kind >= 0.12 && kind < 0.36) { /* (conifers stay green) */ } else if (CTX.season === 'autumn' && turn < 0.6) g = pick(AUTUMN, rnd(x, y, 14));
    else if (CTX.season === 'winter' && turn < 0.65) g = pick(WINTER, rnd(x, y, 14));
    else if (CTX.season === 'spring' && turn < 0.16) g = pick(BLOSSOM, rnd(x, y, 14));
    if (CTX.snow) g = g.map((c) => mix(c, SNOW, 0.45));
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
    // a round tree: in full leaf, turning and thinning (autumn), bare (winter) or in blossom
    const r = 2.5 * s, trunkTop = 2.4 * s, t = V.p(x, y, trunkTop), c = V.p(x, y, trunkTop + r * 0.9);
    const autumn = CTX.season === 'autumn' && turn < 0.6, bare = CTX.season === 'winter' && turn < 0.4;
    const thin = autumn && rnd(x, y, 15) < 0.35, bloom = CTX.season === 'spring' && turn < 0.16;
    let svg = '';
    // (leaves fallen round it, on the grass)
    if (autumn && !CTX.snow) {
      for (let i = 0, n = thin ? 11 : 6; i < n; i++) {
        const a = rnd(x, y, 90 + i) * 6.283, d = r * (0.3 + rnd(y, x, 110 + i) * 1.1), q = V.p(x + Math.cos(a) * d, y + Math.sin(a) * d, 0);
        svg += `<ellipse cx="${f(q[0])}" cy="${f(q[1])}" rx=".42" ry="${f(0.42 * SE)}" fill="${g[i % 3]}"/>`;
      }
    }
    svg += `<line x1="${f(base[0])}" y1="${f(base[1])}" x2="${f(t[0])}" y2="${f(t[1])}" stroke="${C.trunk}" stroke-width="${f(Math.max(0.35, r * 0.24))}"/>`;
    if (bare || thin) {
      // branches (and, thinning, a few clumps of leaves left on them)
      for (let i = 0; i < 5; i++) {
        const a = rnd(x, y, 120 + i) * 6.283, e = V.p(x + Math.cos(a) * r * 0.75, y + Math.sin(a) * r * 0.75, trunkTop + r * (0.8 + rnd(x, y, 130 + i) * 0.9));
        const m = V.p(x + Math.cos(a) * r * 0.3, y + Math.sin(a) * r * 0.3, trunkTop + r * 0.45);
        svg += `<path d="M${f(t[0])} ${f(t[1])}Q${f(m[0])} ${f(m[1])} ${f(e[0])} ${f(e[1])}" fill="none" stroke="${mix(C.trunk, '#3d2c1e', 0.25)}" stroke-width="${f(Math.max(0.18, r * 0.09))}" stroke-linecap="round"/>`;
        if (thin && i % 2 === 0) svg += `<circle cx="${f(e[0])}" cy="${f(e[1])}" r="${f(r * 0.38)}" fill="${g[i % 3]}"/>`;
        if (bare && CTX.snow) svg += `<circle cx="${f(e[0])}" cy="${f(e[1])}" r="${f(r * 0.12)}" fill="${SNOW}"/>`;
      }
      const top = V.p(x, y, trunkTop + r * 1.6);
      svg += `<line x1="${f(t[0])}" y1="${f(t[1])}" x2="${f(top[0])}" y2="${f(top[1])}" stroke="${mix(C.trunk, '#3d2c1e', 0.25)}" stroke-width="${f(Math.max(0.2, r * 0.12))}" stroke-linecap="round"/>`;
    } else {
      svg += `<circle cx="${f(c[0])}" cy="${f(c[1])}" r="${f(r)}" fill="${g[1]}"/>`
        + `<path d="M${f(c[0] - r)} ${f(c[1])}A${f(r)} ${f(r)} 0 0 1 ${f(c[0] + r * 0.6)} ${f(c[1] - r * 0.8)}L${f(c[0] - r * 0.1)} ${f(c[1] + r * 0.2)}Z" fill="${g[0]}"/>`
        + `<circle cx="${f(c[0] - r * 0.42)}" cy="${f(c[1] - r * 0.4)}" r="${f(r * 0.28)}" fill="${g[2]}"/>`;
    }
    // leaves (or petals) falling now and then: more on a windy day, blown further
    if ((autumn || bloom) && !CTX.snow && CTX.leaves > 0 && rnd(x, y, 140) < (CTX.windy ? 0.7 : 0.4)) {
      const drop = base[1] - c[1] + r * 0.6;
      for (let i = 0, n = CTX.windy ? 3 : 2; i < n && CTX.leaves > 0; i++, CTX.leaves--) {
        const sx = c[0] + (rnd(x, y, 150 + i) - 0.5) * r * 1.4, sy = c[1] + (rnd(y, x, 160 + i) - 0.5) * r;
        const dx = (CTX.windy ? 9 : 2.5) * (0.5 + rnd(x, y, 170 + i)), dur = (4 + rnd(x, y, 180 + i) * 4).toFixed(1), begin = (rnd(x, y, 190 + i) * 8).toFixed(1);
        const col = bloom ? g[2] : g[i % 3];
        svg += `<g opacity="0"><animateTransform attributeName="transform" type="translate" values="0 0;${f(dx * 0.4)} ${f(drop * 0.45)};${f(dx * 0.7)} ${f(drop * 0.75)};${f(dx)} ${f(drop)}" dur="${dur}s" begin="${begin}s" repeatCount="indefinite"/>`
          + `<animate attributeName="opacity" values="0;1;1;0" keyTimes="0;.1;.85;1" dur="${dur}s" begin="${begin}s" repeatCount="indefinite"/>`
          + `<path d="M${f(sx - 0.35)} ${f(sy)}Q${f(sx)} ${f(sy - 0.3)} ${f(sx + 0.35)} ${f(sy)}Q${f(sx)} ${f(sy + 0.3)} ${f(sx - 0.35)} ${f(sy)}Z" fill="${col}">`
          + `<animateTransform attributeName="transform" type="rotate" values="0 ${f(sx)} ${f(sy)};180 ${f(sx)} ${f(sy)};360 ${f(sx)} ${f(sy)}" dur="${(1.6 + rnd(x, y, 200 + i)).toFixed(1)}s" repeatCount="indefinite"/></path></g>`;
      }
    }
    return svg;
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

  // The outline round a set of points (convex hull, anticlockwise)
  function hull(P) {
    const p = P.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    if (p.length < 3) return p;
    const cr = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    const lo = [], hi = [];
    for (const q of p) { while (lo.length > 1 && cr(lo[lo.length - 2], lo[lo.length - 1], q) <= 0) lo.pop(); lo.push(q); }
    for (const q of p.slice().reverse()) { while (hi.length > 1 && cr(hi[hi.length - 2], hi[hi.length - 1], q) <= 0) hi.pop(); hi.push(q); }
    return lo.slice(0, -1).concat(hi.slice(0, -1));
  }

  // A street lamp (lit at night)
  function lamp(V, [x, y]) {
    const b = V.p(x, y, 0), t = V.p(x, y, 4.8);
    let s = `<line x1="${f(b[0])}" y1="${f(b[1])}" x2="${f(t[0])}" y2="${f(t[1])}" stroke="#454a52" stroke-width=".34"/>`
      + `<rect x="${f(t[0] - 0.5)}" y="${f(t[1] - 0.45)}" width="1" height=".55" rx=".18" fill="#383c44"/>`;
    if (CTX.night) s += `<circle cx="${f(t[0])}" cy="${f(t[1] + 0.3)}" r="1.6" fill="${LIGHT}" opacity=".35"/><circle cx="${f(t[0])}" cy="${f(t[1] + 0.25)}" r=".45" fill="${LIGHT2}"/>`;
    return s;
  }

  // A chunk of rock floating under the map: a low-poly shard with a turf top, bobbing
  function shard(V, x, y, z, s, seed) {
    const a = rnd(seed, 1, 70) * Math.PI / 2, ring = [0, 1, 2, 3].map((i) => [x + Math.cos(a + i * Math.PI / 2) * s * (0.8 + 0.4 * rnd(seed, i, 71)), y + Math.sin(a + i * Math.PI / 2) * s * (0.8 + 0.4 * rnd(seed, i, 72))]);
    const tip = V.p(x + (rnd(seed, 2, 73) - 0.5) * s, y, z - s * (1.6 + rnd(seed, 3, 74)));
    const faces = [];
    for (let i = 0; i < 4; i++) {
      const p = ring[i], q = ring[(i + 1) % 4], tt = shadeOf(V, q[1] - p[1], -(q[0] - p[0]));
      faces.push([V.d((p[0] + q[0]) / 2, (p[1] + q[1]) / 2), poly([V.p(p[0], p[1], z), V.p(q[0], q[1], z), tip], mix(C.rock, C.rockDark, tt))]);
    }
    faces.sort((m, n) => m[0] - n[0]);  // (the near ones last... drawn after the far)
    faces.reverse();
    const top = poly(ring.map(([u, v]) => V.p(u, v, z)), C.turf, ` stroke="${C.turfDark}" stroke-width=".3"`);
    const d = (4 + rnd(seed, 5, 75) * 3).toFixed(1), amp = (0.8 + rnd(seed, 6, 76)).toFixed(2);
    return {svg: `<g><animateTransform attributeName="transform" type="translate" values="0 0;0 -${amp};0 0" dur="${d}s" repeatCount="indefinite"/>${faces.map((x) => x[1]).join('')}${top}</g>`, low: tip[1]};
  }

  // ---------- the details: gardens, street life, landmarks, your house's energy, occasions ----------
  // (bright colours as rgb(): the night tint only darkens #rrggbb ones, so these stay lit)
  const XMAS = ['rgb(255,70,70)', 'rgb(80,220,110)', 'rgb(90,150,255)', 'rgb(255,210,80)'];
  const FLOWERS = ['#e84a6f', '#f6c945', '#ffffff', '#b46ee0', '#ff8c42', '#e8566c'];
  const CLOTHES = ['#e53935', '#1e88e5', '#fdd835', '#ffffff', '#43a047', '#8e24aa'];
  const SKIN = ['#f1c27d', '#e0ac69', '#c68642', '#8d5524', '#ffdbac'];
  const TOPS = ['#e53935', '#1e88e5', '#43a047', '#fdd835', '#6d4c41', '#37474f', '#eeeeee', '#8e24aa', '#ff7043'];

  // What's on today: Christmas lights (December to Twelfth Night), pumpkins (the week to Halloween),
  // fireworks (Bonfire Night, New Year's Eve and Day)
  function occasion(d) {
    const m = d.getMonth() + 1, day = d.getDate();
    return {xmas: m === 12 || (m === 1 && day <= 6), halloween: m === 10 && day >= 24,
      fireworks: (m === 11 && day >= 4 && day <= 6) || (m === 12 && day === 31) || (m === 1 && day === 1)};
  }

  // Where shadows fall from the real sun (Home Assistant's sun: azimuth, elevation), per metre of height
  function shadowVec(sun) {
    if (!sun || sun.el == null || sun.az == null || sun.el < 1) return null;
    const az = sun.az * Math.PI / 180, k = Math.min(3.5, 1 / Math.tan(Math.max(sun.el, 4) * Math.PI / 180));
    return [-Math.sin(az) * k, -Math.cos(az) * k];
  }

  const plen = (p) => p.reduce((s, q, i) => (i ? s + Math.hypot(q[0] - p[i - 1][0], q[1] - p[i - 1][1]) : 0), 0);
  // A polyline moved sideways by d metres (+: to the left of its way)
  function offsetLine(p, d) {
    return p.map((q, i) => {
      const a = p[Math.max(0, i - 1)], b = p[Math.min(p.length - 1, i + 1)], L = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
      return [q[0] - (b[1] - a[1]) / L * d, q[1] + (b[0] - a[0]) / L * d];
    });
  }
  // The stretch of a polyline from s0 to s1 metres along it
  function stretch(p, s0, s1) {
    const out = [];
    let acc = 0;
    for (let i = 0; i < p.length - 1; i++) {
      const [ax, ay] = p[i], [bx, by] = p[i + 1], L = Math.hypot(bx - ax, by - ay);
      const at = (s) => [ax + (bx - ax) * (s - acc) / L, ay + (by - ay) * (s - acc) / L];
      if (L && acc + L >= s0 && acc <= s1) {
        if (!out.length) out.push(at(Math.max(s0, acc)));
        out.push(at(Math.min(s1, acc + L)));
      }
      acc += L;
    }
    return out;
  }
  const spath = (V, p) => line(V, p);

  // A point in a house's plot: s metres from its middle away from the street, l along the street
  const PW = (P, s, l) => [P.c[0] + P.n[0] * s + P.u[0] * l, P.c[1] + P.n[1] * s + P.u[1] * l];
  const plotQuad = (V, P, s0, s1, l0, l1) => [PW(P, s0, l0), PW(P, s0, l1), PW(P, s1, l1), PW(P, s1, l0)].map(([x, y]) => V.p(x, y, 0));

  // A run of fence, low wall or hedge from a to b
  function boundary(V, a, b, kind) {
    const L = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (L < 0.5) return '';
    const ang = Math.atan2(b[1] - a[1], b[0] - a[0]), cx = (a[0] + b[0]) / 2, cy = (a[1] + b[1]) / 2;
    if (kind === 'hedge') return box(V, cx, cy, ang, L, 0.8, 0, 1.15, [snowy('#4f8f3a', 0.7), snowy('#3b6f2c', 0.7)], snowy('#5fa344', 0.85));
    if (kind === 'wall') return box(V, cx, cy, ang, L, 0.3, 0, 0.7, ['#b5654a', '#8f4e3a'], snowy('#c9b9a5', 0.85));
    return box(V, cx, cy, ang, L, 0.08, 0, 1.3, ['#b48d63', '#94704c'], snowy('#86653f', 0.85));
  }

  // A bed of flowers (bare soil in winter) on the quad q (world points)
  function flowerBed(V, q, seed) {
    let s = poly(q.map(([x, y]) => V.p(x, y, 0)), snowy('#8a6a4a', 0.85));
    if (CTX.season === 'winter' || CTX.snow) return s;
    const n = CTX.season === 'autumn' ? 4 : 10;
    for (let i = 0; i < n; i++) {
      const a = rnd(seed, i, 320), b = rnd(i, seed, 321);
      const x = q[0][0] + (q[1][0] - q[0][0]) * a + (q[3][0] - q[0][0]) * b, y = q[0][1] + (q[1][1] - q[0][1]) * a + (q[3][1] - q[0][1]) * b;
      const p = V.p(x, y, 0.25);
      s += `<circle cx="${f(p[0])}" cy="${f(p[1])}" r=".28" fill="${pick(FLOWERS, rnd(seed, i, 322))}"/>`;
    }
    return s;
  }

  function bush(V, x, y, s, seed) {
    const g = pick(GREENS, rnd(x, y, 330)).map((c) => snowy(c, 0.45)), r = 0.9 * s, c = V.p(x, y, r * 0.7);
    return `<circle cx="${f(c[0])}" cy="${f(c[1])}" r="${f(r)}" fill="${g[1]}"/><circle cx="${f(c[0] - r * 0.25)}" cy="${f(c[1] - r * 0.25)}" r="${f(r * 0.65)}" fill="${g[0]}"/>`;
  }

  function trampoline(V, x, y) {
    const g = V.p(x, y, 0), t = V.p(x, y, 0.8);
    return `<ellipse cx="${f(g[0])}" cy="${f(g[1])}" rx="1.9" ry="${f(1.9 * SE)}" fill="#000000" opacity=".15"/>`
      + `<line x1="${f(g[0] - 1.4)}" y1="${f(g[1])}" x2="${f(t[0] - 1.4)}" y2="${f(t[1])}" stroke="#5f6670" stroke-width=".15"/><line x1="${f(g[0] + 1.4)}" y1="${f(g[1])}" x2="${f(t[0] + 1.4)}" y2="${f(t[1])}" stroke="#5f6670" stroke-width=".15"/>`
      + `<ellipse cx="${f(t[0])}" cy="${f(t[1])}" rx="1.8" ry="${f(1.8 * SE)}" fill="#2f7de1"/><ellipse cx="${f(t[0])}" cy="${f(t[1])}" rx="1.45" ry="${f(1.45 * SE)}" fill="#22252b"/>`;
  }

  function washingLine(V, a, b, seed) {
    const a0 = V.p(a[0], a[1], 0), a1 = V.p(a[0], a[1], 1.9), b0 = V.p(b[0], b[1], 0), b1 = V.p(b[0], b[1], 1.9);
    let s = `<line x1="${f(a0[0])}" y1="${f(a0[1])}" x2="${f(a1[0])}" y2="${f(a1[1])}" stroke="#8d939b" stroke-width=".14"/><line x1="${f(b0[0])}" y1="${f(b0[1])}" x2="${f(b1[0])}" y2="${f(b1[1])}" stroke="#8d939b" stroke-width=".14"/>`
      + `<line x1="${f(a1[0])}" y1="${f(a1[1])}" x2="${f(b1[0])}" y2="${f(b1[1])}" stroke="#e0e0e0" stroke-width=".06"/>`;
    if (CTX.wet || CTX.night) return s;  // (brought in)
    for (let i = 1; i <= 4; i++) {
      const t = i / 5, x = a1[0] + (b1[0] - a1[0]) * t, y = a1[1] + (b1[1] - a1[1]) * t;
      s += `<rect x="${f(x - 0.28)}" y="${f(y)}" width=".56" height="${f(0.55 + rnd(seed, i, 340) * 0.35)}" fill="${pick(CLOTHES, rnd(seed, i, 341))}"/>`;
    }
    return s;
  }

  function pumpkin(V, x, y) {
    const c = V.p(x, y, 0.35);
    let s = `<ellipse cx="${f(c[0])}" cy="${f(c[1])}" rx=".5" ry=".4" fill="#f28c28"/><rect x="${f(c[0] - 0.06)}" y="${f(c[1] - 0.55)}" width=".12" height=".2" fill="#4e7a2a"/>`;
    // (its face lit at night)
    const lit = CTX.night ? 'rgb(255,220,90)' : '#5a3410';
    s += `<path d="M${f(c[0] - 0.3)} ${f(c[1] - 0.08)}l.12 -.12l.1 .12zM${f(c[0] + 0.1)} ${f(c[1] - 0.08)}l.12 -.12l.1 .12zM${f(c[0] - 0.25)} ${f(c[1] + 0.1)}h.5l-.1 .12h-.3z" fill="${lit}"/>`;
    if (CTX.night) s += `<circle cx="${f(c[0])}" cy="${f(c[1])}" r="1.3" fill="rgb(255,170,60)" opacity=".25"/>`;
    return s;
  }

  // Your house's energy: the car charging (a glow and a bolt), the heat pump (puffs when running)
  function chargeGlow(V, x, y) {
    const g = V.p(x, y, 0), t = V.p(x, y, 3.2);
    return `<ellipse cx="${f(g[0])}" cy="${f(g[1])}" rx="3.6" ry="${f(3.6 * SE)}" fill="rgb(80,200,255)" opacity=".3"><animate attributeName="opacity" values=".15;.45;.15" dur="2s" repeatCount="indefinite"/></ellipse>`
      + `<path d="M${f(t[0] + 0.2)} ${f(t[1] - 1)}l-.75 1.05h.55l-.3 .95l.95 -1.25h-.6z" fill="rgb(120,235,255)" stroke="rgb(20,90,140)" stroke-width=".08"><animate attributeName="opacity" values=".5;1;.5" dur="2s" repeatCount="indefinite"/></path>`;
  }

  function heatPump(V, x, y, ang, running) {
    let s = box(V, x, y, ang, 1.1, 0.45, 0, 0.95, ['#eceef1', '#c4c9cf'], '#dde1e5');
    const c = V.p(x, y, 0.5);
    s += `<circle cx="${f(c[0])}" cy="${f(c[1])}" r=".32" fill="#5d636b"/>`;
    if (running) {
      s += `<g><animateTransform attributeName="transform" type="rotate" from="0 ${f(c[0])} ${f(c[1])}" to="360 ${f(c[0])} ${f(c[1])}" dur=".8s" repeatCount="indefinite"/>`
        + `<line x1="${f(c[0] - 0.28)}" y1="${f(c[1])}" x2="${f(c[0] + 0.28)}" y2="${f(c[1])}" stroke="#c9ced4" stroke-width=".1"/><line x1="${f(c[0])}" y1="${f(c[1] - 0.28)}" x2="${f(c[0])}" y2="${f(c[1] + 0.28)}" stroke="#c9ced4" stroke-width=".1"/></g>`;
      const t = V.p(x, y, 1.1);
      for (let k = 0; k < 3; k++) {
        s += `<circle cx="${f(t[0])}" cy="${f(t[1])}" r=".4" fill="#f4f7fa" opacity="0">`
          + `<animate attributeName="cy" from="${f(t[1])}" to="${f(t[1] - 4)}" dur="3s" begin="${k}s" repeatCount="indefinite"/>`
          + `<animate attributeName="r" from=".3" to="1.4" dur="3s" begin="${k}s" repeatCount="indefinite"/>`
          + `<animate attributeName="opacity" values="0;.8;0" dur="3s" begin="${k}s" repeatCount="indefinite"/></circle>`;
      }
    }
    return s;
  }

  /* A house's garden (scene.plots, from src/scene.py _plots): {ground: [svg] (drawn on the ground),
   * things: [[depth, svg]] (with the buildings and trees)}. Front: a path to the door, a driveway
   * (some with a car, or a garage), a hedge or low wall; back: fences or hedges, a patio or a
   * conservatory, a shed, a trampoline, a washing line, bushes, flower beds. Your house: your car on
   * the drive (glowing while charging) and the heat pump. */
  function plotBits(V, P, on, isHome) {
    const ground = [], things = [], id = P.id || 0, r = (k) => rnd(id, k, 300), energy = isHome ? (CTX.energy || {}) : {};
    const thing = (x, y, svg) => { if (svg && on(x, y)) things.push([V.d(x, y), svg]); };
    const angU = Math.atan2(P.u[1], P.u[0]), angN = Math.atan2(P.n[1], P.n[0]);
    const {hl, hf, hb} = P, fr = P.f || 0, bk = P.b || 0, w = Math.max(P.w || hl + 1, hl);
    const sd = r(2) < 0.5 ? 1 : -1;
    // the front
    const drive = fr >= 4.2 && (isHome || r(1) < 0.5), dl = sd * Math.max(0, Math.min(hl * 0.5, w - 1.8));
    const pl = drive ? -sd * Math.min(hl * 0.4, 1.6) : 0;
    if (fr >= 0.8) ground.push(poly(plotQuad(V, P, -hf - fr, -hf, pl - 0.55, pl + 0.55), snowy('#d8d0c0', 0.6)));
    if (drive) {
      ground.push(poly(plotQuad(V, P, -hf - fr, -hf - 0.2, dl - 1.5, dl + 1.5), snowy(r(5) < 0.5 ? '#bdb6aa' : '#d3c7ad', 0.5), ' stroke="#a59e92" stroke-width=".15"'));
      const carHere = isHome ? !!energy.car : r(3) < 0.55;
      if (carHere) {
        const [x, y] = PW(P, -hf - Math.min(fr / 2, 3.2), dl);
        thing(x, y, car(V, [x, y, angN * 180 / Math.PI, Math.floor(r(4) * 10)]) + (isHome && energy.charging ? chargeGlow(V, x, y) : ''));
      }
    } else if (isHome && energy.car) {
      // (no room for a drive: your car at the kerb outside)
      const [x, y] = PW(P, -hf - fr - PAVE - 0.95, 0);
      thing(x, y, car(V, [x, y, angU * 180 / Math.PI, 3]) + (energy.charging ? chargeGlow(V, x, y) : ''));
    }
    // (a garage beside a detached house, at the end of the drive)
    if (!isHome && drive && w - hl >= 3.2 && r(17) < 0.4) {
      const [x, y] = PW(P, -hf + 3, sd * (hl + 1.6));
      thing(x, y, box(V, x, y, angN, 5.6, 2.8, 0, 2.4, ['#ebe5da', '#c9c1b2'], snowy('#8a8f96', 0.8)));
    }
    if (fr >= 1.5 && r(6) < 0.45) {
      // a hedge or low wall along the pavement, with gaps for the path and the drive
      const kind = r(7) < 0.6 ? 'hedge' : 'wall', s = -hf - fr + 0.4, gaps = [[pl - 0.8, pl + 0.8]].concat(drive ? [[dl - 1.7, dl + 1.7]] : []);
      let l0 = -w;
      for (const [g0, g1] of gaps.sort((a, b) => a[0] - b[0]).concat([[w, w]])) {
        if (g0 - l0 > 0.6) { const a = PW(P, s, l0), b = PW(P, s, g0), m = PW(P, s, (l0 + g0) / 2); thing(m[0], m[1], boundary(V, a, b, kind)); }
        l0 = Math.max(l0, g1);
      }
    }
    if (fr >= 1.6 && r(8) < 0.35) {
      // flowers under the front window
      const l0 = -sd * 0.9, l1 = -sd * Math.max(1.2, hl * 0.9);
      ground.push(flowerBed(V, [PW(P, -hf - 1.1, l0), PW(P, -hf - 1.1, l1), PW(P, -hf - 0.2, l1), PW(P, -hf - 0.2, l0)], id + 1));
    }
    if (CTX.occ && CTX.occ.halloween && (isHome || r(16) < 0.35) && fr >= 0.8) {
      const [x, y] = PW(P, -hf - 0.7, pl + 0.95);
      thing(x, y, pumpkin(V, x, y));
    }
    // the back
    if (bk >= 2) {
      const kind = r(9) < 0.25 ? 'hedge' : 'fence', sd2 = r(11) < 0.5 ? 1 : -1;
      for (const l of [w, -w]) {
        const a = PW(P, hb, l), b = PW(P, hb + bk, l), m = PW(P, hb + bk / 2, l);
        thing(m[0], m[1], boundary(V, a, b, kind));
      }
      { const a = PW(P, hb + bk, -w), b = PW(P, hb + bk, w), m = PW(P, hb + bk, 0); thing(m[0], m[1], boundary(V, a, b, kind)); }
      const cons = !isHome && bk >= 6 && r(12) < 0.1, pd = Math.min(3, bk * 0.35);
      if (cons) {
        const [x, y] = PW(P, hb + 1.5, 0);
        thing(x, y, box(V, x, y, angU, Math.max(2.5, hl * 1.1), 3, 0, 2.6, ['#d6ebf5', '#a9c9dc'], snowy('#eef6fa', 0.5)));
      } else if (r(13) < 0.6) {
        ground.push(poly(plotQuad(V, P, hb, hb + pd, -hl * 0.85, hl * 0.85), snowy('#d9d1c1', 0.6), ' stroke="#c4baa6" stroke-width=".12"'));
      }
      if (bk >= 5 && r(15) < 0.4) {
        const s0 = hb + pd + 0.5, s1 = hb + bk - 1.2, l1 = -sd2 * (w - 0.25), l0 = -sd2 * (w - 1.0);
        if (s1 - s0 > 1.5) ground.push(flowerBed(V, [PW(P, s0, l0), PW(P, s0, l1), PW(P, s1, l1), PW(P, s1, l0)], id + 2));
      }
      if (bk >= 7 && r(10) < 0.45) {
        const [x, y] = PW(P, hb + bk - 1.5, sd2 * Math.max(0, w - 1.4));
        thing(x, y, box(V, x, y, angU, 2.2, 1.8, 0, 2.1, ['#9b7a55', '#7d5f40'], snowy('#5d4a3a', 0.85)));
      }
      if (bk >= 8 && r(14) < 0.09) { const [x, y] = PW(P, hb + bk * 0.55, -sd2 * w * 0.35); thing(x, y, trampoline(V, x, y)); }
      if (bk >= 6 && r(18) < 0.08) {
        const a = PW(P, hb + pd + 0.8, -sd2 * Math.max(0, w - 1)), b = PW(P, hb + bk - 1.2, -sd2 * Math.max(0, w - 1)), m = PW(P, hb + bk / 2, -sd2 * (w - 1));
        thing(m[0], m[1], washingLine(V, a, b, id));
      }
      if (r(19) < 0.35) {
        for (let k = 0; k < 2 + Math.floor(r(20) * 2); k++) {
          const [x, y] = PW(P, hb + bk - 1.1, -sd2 * (w - 1.1 - k * 1.3));
          thing(x, y, bush(V, x, y, 0.8 + r(21 + k) * 0.5, id + k));
        }
      }
    }
    // your heat pump, beside the house at the back
    if (isHome && energy.heat !== null && energy.heat !== undefined) {
      const [x, y] = w - hl > 1.2 ? PW(P, hb - 1.2, hl + 0.55) : PW(P, hb + 0.6, hl * 0.55);
      thing(x, y, heatPump(V, x, y, w - hl > 1.2 ? angN : angU, !!energy.heat));
    }
    return {ground, things};
  }

  // Street furniture: a bench, a post box, a bin, a bus stop (a shelter and its sign)
  function furniture(V, x, y, kind, ang) {
    if (kind === 'bench') {
      const bx = x - Math.sin(ang) * 0.25, by = y + Math.cos(ang) * 0.25;
      return box(V, x, y, ang, 1.7, 0.5, 0.35, 0.47, ['#9c7650', '#7b5c3e'], snowy('#b08a5f', 0.8)) + box(V, bx, by, ang, 1.7, 0.08, 0.47, 0.95, ['#9c7650', '#7b5c3e'], '#8a6a46');
    }
    if (kind === 'post_box') return box(V, x, y, 0, 0.55, 0.55, 0, 1.15, ['#d32f2f', '#a52323'], '#2b2b2b');
    if (kind === 'bin') return box(V, x, y, 0, 0.45, 0.45, 0, 0.9, ['#2e7d32', '#1f5f24'], '#1b1b1b');
    if (kind === 'bus_stop') {
      const px = x + Math.cos(ang) * 2, py = y + Math.sin(ang) * 2, a = V.p(px, py, 0), b = V.p(px, py, 2.9);
      return box(V, x, y, ang, 3, 1.2, 0, 2.4, ['#d7e8f2', '#a9c4d4'], snowy('#4a5560', 0.8))
        + `<line x1="${f(a[0])}" y1="${f(a[1])}" x2="${f(b[0])}" y2="${f(b[1])}" stroke="#5f6670" stroke-width=".14"/><circle cx="${f(b[0])}" cy="${f(b[1])}" r=".42" fill="#d32f2f" stroke="#ffffff" stroke-width=".1"/>`;
    }
    return '';
  }

  // Moving things: a car or a bus along a path, people walking, ducks paddling, a train
  function mover(path, dur, begin, sprite, opts2 = '') {
    return `<g>${sprite}<animateMotion path="${path}" dur="${dur.toFixed(1)}s" begin="${begin.toFixed(1)}s" repeatCount="indefinite"${opts2}/></g>`;
  }
  // (as seen from above at an angle: a little flatter than it's long)
  function carSprite(col, len = 4.2, wid = 1.35, glass = '#7d9fc4') {
    const night = CTX.night;
    return `<rect x="${f(-len / 2)}" y="${f(-wid / 2 - 0.4)}" width="${f(len)}" height="${f(wid)}" rx=".45" fill="${col}"/>`
      + `<rect x="${f(-len * 0.24)}" y="${f(-wid / 2 - 0.25)}" width="${f(len * 0.48)}" height="${f(wid - 0.3)}" rx=".3" fill="${glass}"/>`
      + (night ? `<circle cx="${f(len / 2)}" cy="${f(-0.4 - wid * 0.25)}" r=".3" fill="${LIGHT2}"/><circle cx="${f(len / 2)}" cy="${f(-0.4 + wid * 0.25)}" r=".3" fill="${LIGHT2}"/><ellipse cx="${f(len / 2 + 2)}" cy="-.4" rx="2" ry="1" fill="${LIGHT}" opacity=".25"/>` : '');
  }
  function walker(seed) {
    const top = pick(TOPS, rnd(seed, 1, 350)), skin = pick(SKIN, rnd(seed, 2, 351)), dog = rnd(seed, 3, 352) < 0.3;
    return `<line x1="-.12" y1="0" x2="-.12" y2="-.8" stroke="#37474f" stroke-width=".2"/><line x1=".12" y1="0" x2=".12" y2="-.8" stroke="#37474f" stroke-width=".2"/>`
      + `<rect x="-.32" y="-1.65" width=".64" height=".95" rx=".2" fill="${top}"/><circle cx="0" cy="-1.95" r=".3" fill="${skin}"/>`
      + (dog ? `<ellipse cx=".95" cy="-.32" rx=".45" ry=".22" fill="${pick(['#8d6e4c', '#3e2723', '#d7ccc8', '#f5f5f5'], rnd(seed, 4, 353))}"/><circle cx="1.38" cy="-.48" r=".16" fill="#5d4037"/><line x1=".25" y1="-1.1" x2="1.2" y2="-.5" stroke="#555555" stroke-width=".04"/>` : '');
  }
  function duck(seed) {
    const brown = rnd(seed, 1, 360) < 0.5;
    return `<ellipse cx="0" cy="0" rx=".55" ry=".3" fill="${brown ? '#8d6e4c' : '#f5f5f0'}"/><circle cx=".42" cy="-.28" r=".2" fill="${brown ? '#2e7d32' : '#f5f5f0'}"/><path d="M.58 -.3l.22 .05l-.22 .07z" fill="#ff9800"/>`;
  }

  /* A school's playground: tarmac with a court and a hopscotch, beside its first wall */
  function playground(V, b) {
    const [p0, p1] = b.p, L = Math.hypot(p1[0] - p0[0], p1[1] - p0[1]);
    if (L < 6) return '';
    const ux = (p1[0] - p0[0]) / L, uy = (p1[1] - p0[1]) / L, nx = uy, ny = -ux;  // (outwards: the right of an anticlockwise wall)
    const at = (t, d) => V.p(p0[0] + ux * L * t + nx * d, p0[1] + uy * L * t + ny * d, 0);
    let s = poly([at(0.08, 1), at(0.92, 1), at(0.92, 14), at(0.08, 14)], snowy('#7f8790', 0.6));
    s += `<polygon points="${pts([at(0.2, 3), at(0.8, 3), at(0.8, 12), at(0.2, 12)])}" fill="none" stroke="#ffffff" stroke-width=".25" opacity=".85"/>`
      + `<path d="M${pts([at(0.5, 3), at(0.5, 12)]).replace(' ', 'L')}" stroke="#ffffff" stroke-width=".2" opacity=".85"/>`;
    const cols = ['#ffd54f', '#4fc3f7', '#e57373', '#81c784'];
    for (let i = 0; i < 4; i++) s += poly([at(0.84, 2 + i * 1.5), at(0.89, 2 + i * 1.5), at(0.89, 3.2 + i * 1.5), at(0.84, 3.2 + i * 1.5)], cols[i]);
    return s;
  }

  /* Fireworks over the map (Bonfire Night, New Year, at night): bursts of sparks, again and again */
  function fireworks(x0, y0, w, h) {
    let s = '';
    for (let i = 0; i < 7; i++) {
      const cx = x0 + w * (0.15 + 0.7 * rnd(i, 1, 370)), cy = y0 + h * (0.06 + 0.3 * rnd(i, 2, 371)), R = Math.min(w, h) * (0.06 + 0.05 * rnd(i, 3, 372));
      const col = pick(['rgb(255,80,80)', 'rgb(255,215,90)', 'rgb(120,200,255)', 'rgb(160,255,140)', 'rgb(255,130,240)', 'rgb(255,255,255)'], rnd(i, 4, 373));
      const dur = 4 + rnd(i, 5, 374) * 2, begin = rnd(i, 6, 375) * 5, kt = 'keyTimes="0;.35;.8;1"';
      const an = (attr, vals) => `<animate attributeName="${attr}" values="${vals}" ${kt} dur="${dur.toFixed(1)}s" begin="${begin.toFixed(1)}s" repeatCount="indefinite"/>`;
      // (the rocket going up, then the burst)
      s += `<circle cx="${f(cx)}" cy="${f(cy + R * 3)}" r="${f(R * 0.04)}" fill="${col}" opacity="0">${an('cy', `${f(cy + R * 3)};${f(cy)};${f(cy)};${f(cy)}`)}${an('opacity', '1;1;0;0')}</circle>`;
      for (let k = 0; k < 14; k++) {
        const a = k / 14 * 6.283, ex = cx + Math.cos(a) * R, ey = cy + Math.sin(a) * R + R * 0.25;
        s += `<circle cx="${f(cx)}" cy="${f(cy)}" r="${f(R * 0.075)}" fill="${col}" opacity="0">${an('cx', `${f(cx)};${f(cx)};${f(ex)};${f(ex)}`)}${an('cy', `${f(cy)};${f(cy)};${f(ey)};${f(ey)}`)}${an('opacity', '0;1;0;0')}</circle>`;
      }
    }
    return `<g class="nvfireworks" pointer-events="none">${s}</g>`;
  }

  const PIN_H = 250;  // (pins and faces sized as on a 250 m map, whatever the map's size)

  // A person's face (their picture, else their initials on their colour), at cx, cy
  function avatar(cx, cy, r, fs, p, title) {
    const col = personColour(p.entity_id || p.name), clip = 'nvp' + Math.random().toString(36).slice(2, 8);
    return `<circle cx="${f(cx)}" cy="${f(cy)}" r="${f(r + fs * 0.12)}" fill="#ffffff"/>`
      + `<circle cx="${f(cx)}" cy="${f(cy)}" r="${f(r)}" fill="${col}"/>`
      + `<text x="${f(cx)}" y="${f(cy)}" fill="#ffffff" font-size="${f(r * 0.8)}" font-family="sans-serif" font-weight="700" text-anchor="middle" dominant-baseline="central">${esc(p.initials || '?')}</text>`
      + (p.picture ? `<clipPath id="${clip}"><circle cx="${f(cx)}" cy="${f(cy)}" r="${f(r)}"/></clipPath><image href="${esc(p.picture)}" x="${f(cx - r)}" y="${f(cy - r)}" width="${f(r * 2)}" height="${f(r * 2)}" clip-path="url(#${clip})" preserveAspectRatio="xMidYMid slice"/>` : '')
      + `<title>${esc(title)}</title>`;
  }

  /* One chunk of map (your home's, or another place's), in its own coordinates: {svg, box: [x0, y0,
   * w, h], pin: [x, y] (over the house or the middle)}. opts: rot, zoom, label, pick (buildings can
   * be clicked: data-id), hideLabel, live (night...), isHome, pinColour, atPin: people shown over the
   * pin, onMap: [{p, x, y}] people drawn where they are. */
  function island(scene, opts = {}) {
    // (wet: the roads and pavements darker, with a blue sheen; put back after)
    const wx = ((opts.live || {}).weather || {}).state || '', keep = {road: C.road, pave: C.pave, kerb: C.kerb, path: C.path};
    if (['rainy', 'pouring', 'lightning-rainy', 'hail', 'snowy-rainy'].includes(wx)) {
      C.road = mix(C.road, '#2b3542', 0.4); C.pave = mix(C.pave, '#8e9aa8', 0.35); C.kerb = mix(C.kerb, '#7d8896', 0.3); C.path = mix(C.path, '#a9a59a', 0.35);
    }
    try { return islandDrawn(scene, opts); } finally { Object.assign(C, keep); }
  }

  function islandDrawn(scene, opts = {}) {
    const V = view(opts.rot || 0), H = scene.half || 250, home = scene.home || {};
    const live = opts.live || {}, people = live.people || [];
    const anyHome = people.some((p) => p.home);
    CTX.night = !!live.night;
    CTX.homeLit = opts.isHome ? (people.length ? anyHome : true) : false;  // (no people set: your house lit at night as any)
    CTX.smoke = !!opts.isHome && !live.night && anyHome;
    CTX.season = season(opts.month != null ? opts.month : (opts.date ? new Date(opts.date) : new Date()).getMonth());
    const wx = (live.weather || {}).state || '';
    CTX.snow = ['snowy', 'snowy-rainy'].includes(wx);
    CTX.wet = ['rainy', 'pouring', 'lightning-rainy', 'hail', 'snowy-rainy'].includes(wx);
    CTX.hail = wx === 'hail';
    CTX.windy = ['windy', 'windy-variant', 'pouring', 'lightning-rainy'].includes(wx);
    CTX.leaves = 90;  // (falling leaves on this map, at most)
    CTX.occ = occasion(opts.date ? new Date(opts.date) : new Date());
    CTX.energy = opts.isHome ? (live.energy || null) : null;
    const motion = opts.motion !== false;
    const out = [];
    // the chunk of ground, torn out: its earth sides (those facing the viewer, back ones first),
    // then its top, with a lip of turf
    const edge = outline(H, (scene.lat || 0) * 1000 + (scene.lon || 0) * 7000);
    const sides = [], front = [];
    for (let i = 0; i < edge.length; i++) {
      const p = edge[i], q = edge[(i + 1) % edge.length];
      const [, aw] = V.n(q[1] - p[1], -(q[0] - p[0]));
      if (aw >= 0) continue;
      front.push([p[0], p[1], p[2]]);
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
    // (a few rocks floating under the front edge, drawn behind it)
    let low = -Infinity;
    const seed0 = Math.round((scene.lat || 1) * 1e4 + (scene.lon || 1) * 3e4);
    for (let k = 0; k < 4 && front.length; k++) {
      const [x, y, dp] = front[Math.floor(rnd(seed0, k, 77) * front.length)];
      const r = shard(V, x * 0.92, y * 0.92, -dp - 7 - rnd(seed0, k, 78) * 12, 2 + rnd(seed0, k, 79) * 3.5, seed0 + k);
      out.push(r.svg); low = Math.max(low, r.low);
    }
    for (const sd of sides) out.push(sd[1]);
    const topPts = edge.map(([x, y]) => V.p(x, y, 0));
    const groundCol = CTX.season === 'winter' ? mix(C.ground, '#b9c2a4', 0.35) : CTX.season === 'autumn' ? mix(C.ground, '#cfd39a', 0.25) : C.ground;
    out.push(poly(topPts, snowy(groundCol, 0.85), ` stroke="${snowy(C.turf, 0.7)}" stroke-width="1.6" stroke-linejoin="round"`));
    // the ground: areas, water, roads, railways (kept to the board: a road's end doesn't stick out)
    const clip = 'nvclip' + Math.random().toString(36).slice(2, 8);
    out.push(`<clipPath id="${clip}"><polygon points="${pts(topPts)}"/></clipPath><g clip-path="url(#${clip})">`);
    const wid = 'nvw' + Math.random().toString(36).slice(2, 8);
    out.push(`<defs><radialGradient id="${wid}"><stop offset="0" stop-color="#b4def6"/><stop offset=".7" stop-color="${C.water}"/><stop offset="1" stop-color="#6eaedb"/></radialGradient></defs>`);
    for (const a of scene.areas || []) {
      const P = a.p.map(([x, y]) => V.p(x, y, 0));
      if (a.k !== 'water') { out.push(poly(P, ['paved', 'yard'].includes(a.k) ? (C[a.k]) : snowy(C[a.k] || C.grass, 0.85))); continue; }
      // ponds and lakes: a darker edge, lighter in the middle, and ripples spreading now and then
      out.push(poly(P, `url(#${wid})`, ` stroke="#4e8dbf" stroke-width="1.1" stroke-linejoin="round"`));
      const xs = a.p.map((q) => q[0]), ys = a.p.map((q) => q[1]);
      const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
      const n = Math.min(4, Math.max(1, Math.round((x1 - x0) * (y1 - y0) / 500)));
      for (let k = 0, tries = 0; k < n && tries < 20; tries++) {
        const x = x0 + (x1 - x0) * rnd(x0, tries, 80), y = y0 + (y1 - y0) * rnd(y0, tries, 81);
        if (!insideRing(x, y, a.p) || !insideRing(x, y, edge)) continue;
        const c = V.p(x, y, 0), dur = (3 + rnd(x, y, 82) * 3).toFixed(1), begin = (rnd(x, y, 83) * 4).toFixed(1);
        out.push(`<ellipse cx="${f(c[0])}" cy="${f(c[1])}" rx=".5" ry="${f(0.5 * SE)}" fill="none" stroke="#ffffff" stroke-width=".3" opacity="0">`
          + `<animate attributeName="rx" values=".5;4" dur="${dur}s" begin="${begin}s" repeatCount="indefinite"/><animate attributeName="ry" values="${f(0.5 * SE)};${f(4 * SE)}" dur="${dur}s" begin="${begin}s" repeatCount="indefinite"/>`
          + `<animate attributeName="opacity" values=".8;0" dur="${dur}s" begin="${begin}s" repeatCount="indefinite"/></ellipse>`);
        k++;
      }
    }
    // parks and playing fields mown in stripes; reeds round ponds, and ducks on them
    for (const a of scene.areas || []) {
      if (!['grass', 'pitch', 'water'].includes(a.k)) continue;
      const xs = a.p.map((q) => q[0]), ys = a.p.map((q) => q[1]);
      const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
      if (a.k !== 'water') {
        if (CTX.snow || (x1 - x0) * (y1 - y0) < 900) continue;
        const cid = 'nvm' + Math.random().toString(36).slice(2, 8), ang = rnd(x0, y0, 380) * Math.PI, ca = Math.cos(ang), sa = Math.sin(ang);
        const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, R = Math.hypot(x1 - x0, y1 - y0) / 2, st = [];
        for (let k = -R; k < R; k += 8) {
          const q = [[k, -R], [k + 4, -R], [k + 4, R], [k, R]].map(([u, v]) => V.p(cx + u * ca - v * sa, cy + u * sa + v * ca, 0));
          st.push(poly(q, mix(C[a.k] || C.grass, '#ffffff', 0.12)));
        }
        out.push(`<clipPath id="${cid}"><polygon points="${pts(a.p.map(([x, y]) => V.p(x, y, 0)))}"/></clipPath><g clip-path="url(#${cid})" opacity=".55">${st.join('')}</g>`);
        continue;
      }
      // reeds along the edge here and there
      let rs = '';
      for (let i = 0; i < a.p.length; i++) {
        const p = a.p[i], q = a.p[(i + 1) % a.p.length], L = Math.hypot(q[0] - p[0], q[1] - p[1]);
        for (let s = 1; s < L; s += 2.2) {
          const x = p[0] + (q[0] - p[0]) * s / L, y = p[1] + (q[1] - p[1]) * s / L;
          if (rnd(x, y, 381) > 0.5 || !insideRing(x, y, edge)) continue;
          for (let k = 0; k < 3; k++) {
            const b0 = V.p(x + (k - 1) * 0.25, y, 0), tp = V.p(x + (k - 1) * 0.45, y + (rnd(x, k, 382) - 0.5) * 0.4, 1.1 + rnd(y, k, 383) * 0.6);
            rs += `<line x1="${f(b0[0])}" y1="${f(b0[1])}" x2="${f(tp[0])}" y2="${f(tp[1])}" stroke="${snowy('#6f8f3c', 0.5)}" stroke-width=".14"/>`;
            if (k === 1 && CTX.season !== 'spring') rs += `<ellipse cx="${f(tp[0])}" cy="${f(tp[1] + 0.25)}" rx=".1" ry=".3" fill="#7a5a3a"/>`;
          }
        }
      }
      out.push(rs);
      if (motion && !CTX.snow && (x1 - x0) * (y1 - y0) > 150) {
        for (let k = 0, tries = 0; k < 3 && tries < 20; tries++) {
          const cx = x0 + (x1 - x0) * rnd(x0, tries, 384), cy = y0 + (y1 - y0) * rnd(y0, tries, 385), rr = 1.5 + rnd(cx, cy, 386) * 2;
          if (!insideRing(cx, cy, a.p) || !insideRing(cx, cy, edge)) continue;
          const loop = [];
          for (let j = 0; j <= 16; j++) loop.push([cx + Math.cos(j / 16 * 6.283) * rr, cy + Math.sin(j / 16 * 6.283) * rr]);
          if (!loop.every(([x, y]) => insideRing(x, y, a.p))) continue;
          out.push(mover(spath(V, loop) + 'Z', 25 + rnd(cx, cy, 387) * 20, -rnd(cy, cx, 388) * 40, duck(cx + cy)));
          k++;
        }
      }
    }
    for (const w of scene.water || []) out.push(`<path d="${line(V, w.p)}" fill="none" stroke="${C.water}" stroke-width="${f(w.w)}" stroke-linecap="round" stroke-linejoin="round"/>`
      + `<path d="${line(V, w.p)}" fill="none" stroke="#ffffff" stroke-opacity=".45" stroke-width="${f(Math.max(0.3, w.w * 0.12))}" stroke-dasharray="1.5 5" stroke-linecap="round"><animate attributeName="stroke-dashoffset" from="0" to="-13" dur="4s" repeatCount="indefinite"/></path>`);
    const roads = scene.roads || [];
    const paths = roads.filter((r) => r.k === 'path'), cars = roads.filter((r) => r.k !== 'path');
    for (const r of paths) out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.pathEdge}" stroke-width="${f(r.w + 0.8)}" stroke-linecap="round" stroke-linejoin="round"/>`);
    for (const r of paths) out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.path}" stroke-width="${f(r.w)}" stroke-linecap="round" stroke-linejoin="round"/>`);
    // streets: a pavement each side (with its kerb), the road, its markings
    const streets = cars.filter((r) => r.k !== 'service');
    for (const r of streets) out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.kerb}" stroke-width="${f(r.w + PAVE * 2 + 0.6)}" stroke-linecap="round" stroke-linejoin="round"/>`);
    for (const r of streets) out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.pave}" stroke-width="${f(r.w + PAVE * 2)}" stroke-linecap="round" stroke-linejoin="round"/>`);
    // (a grass verge between the pavement and the kerb on residential streets)
    for (const r of streets.filter((r) => r.k === 'minor')) out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${snowy(C.verge, 0.85)}" stroke-width="${f(r.w + 2.4)}" stroke-linecap="round" stroke-linejoin="round"/>`);
    for (const r of cars) out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${mix(C.road, '#ffffff', 0.35)}" stroke-width="${f(r.w + 0.5)}" stroke-linecap="round" stroke-linejoin="round"/>`);
    for (const r of cars) out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.road}" stroke-width="${f(r.w)}" stroke-linecap="round" stroke-linejoin="round"/>`);
    for (const r of streets) out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.roadLine}" stroke-width="${r.k === 'major' ? '.45' : '.3'}" stroke-dasharray="${r.k === 'major' ? '4 3' : '2.5 4'}" opacity=".85"/>`);
    // zebra crossings on each street just back from where streets meet (a shared point, one
    // street's end on another, or two crossing)
    const segs = [];
    streets.forEach((r, ri) => { for (let i = 0; i < r.p.length - 1; i++) segs.push([ri, r.p[i], r.p[i + 1], r.w]); });
    const joins = new Map();
    const leg = (P, ri, a, b, t, w) => {
      const L = Math.hypot(b[0] - a[0], b[1] - a[1]), k = Math.round(P[0]) + ',' + Math.round(P[1]);
      if (!joins.has(k)) joins.set(k, {P, legs: [], w: 0});
      const J = joins.get(k);
      J.w = Math.max(J.w, w);
      for (const [len, dx, dy] of [[t * L, a[0] - b[0], a[1] - b[1]], [(1 - t) * L, b[0] - a[0], b[1] - a[1]]]) {
        const ux = dx / L, uy = dy / L;
        if (len > 1 && !J.legs.some((g) => g.ri === ri && g.ux * ux + g.uy * uy > 0.9)) J.legs.push({ri, ux, uy, len, w});
      }
    };
    for (let i = 0; i < segs.length; i++) {
      const [ri, a, b, wa] = segs[i], La = Math.hypot(b[0] - a[0], b[1] - a[1]);
      if (!La) continue;
      for (let j = i + 1; j < segs.length; j++) {
        const [rj, c, d, wc] = segs[j];
        if (ri === rj) continue;
        if (Math.max(c[0], d[0]) < Math.min(a[0], b[0]) - 2 || Math.min(c[0], d[0]) > Math.max(a[0], b[0]) + 2
          || Math.max(c[1], d[1]) < Math.min(a[1], b[1]) - 2 || Math.min(c[1], d[1]) > Math.max(a[1], b[1]) + 2) continue;
        const Lc = Math.hypot(d[0] - c[0], d[1] - c[1]), rx = b[0] - a[0], ry = b[1] - a[1], sx = d[0] - c[0], sy = d[1] - c[1];
        const den = rx * sy - ry * sx;
        if (!Lc || Math.abs(den) < 1e-9) continue;
        const t = ((c[0] - a[0]) * sy - (c[1] - a[1]) * sx) / den, u = ((c[0] - a[0]) * ry - (c[1] - a[1]) * rx) / den;
        const ta = 1.5 / La, tc = 1.5 / Lc;
        if (t < -ta || t > 1 + ta || u < -tc || u > 1 + tc) continue;
        const tt = Math.max(0, Math.min(1, t)), uu = Math.max(0, Math.min(1, u)), P = [a[0] + rx * tt, a[1] + ry * tt];
        leg(P, ri, a, b, tt, wa);
        leg(P, rj, c, d, uu, wc);
      }
    }
    const zebra = [];
    for (const {P, legs, w} of joins.values()) {
      if (legs.length < 3) continue;  // (a bend, not a junction)
      const dd = w / 2 + PAVE + 1.8;
      for (const g of legs) {
        if (g.len < dd + 5) continue;
        const ux = g.ux, uy = g.uy, vx = -uy, vy = ux, cx = P[0] + ux * dd, cy = P[1] + uy * dd;
        if (!insideRing(cx, cy, edge)) continue;
        for (let o = -g.w / 2 + 0.55; o <= g.w / 2 - 0.5; o += 1.05) {
          const at = (s, e) => V.p(cx + ux * s + vx * (o + e), cy + uy * s + vy * (o + e), 0);
          zebra.push(poly([at(-1.2, 0), at(1.2, 0), at(1.2, 0.5), at(-1.2, 0.5)], C.roadLine));
        }
      }
    }
    if (zebra.length) out.push(`<g opacity=".9">${zebra.join('')}</g>`);
    // wet: puddles by the kerbs and on the pavements, raindrops rippling some of them
    if (CTX.wet) {
      const pud = [];
      for (const r of cars.concat(paths)) {
        let acc = 6 + rnd(r.p[0][0], r.p[0][1], 220) * 14;
        for (let i = 0; i < r.p.length - 1; i++) {
          const [ax, ay] = r.p[i], [bx, by] = r.p[i + 1], L = Math.hypot(bx - ax, by - ay);
          if (!L) continue;
          const ux = (bx - ax) / L, uy = (by - ay) / L;
          while (acc < L) {
            const k = rnd(ax + acc, ay, 221), side = k < 0.5 ? 1 : -1;
            const off = r.k === 'path' ? (rnd(ax, acc, 222) - 0.5) * r.w * 0.5 : r.w / 2 - 0.9 + (k > 0.8 ? PAVE * 0.9 : 0);
            const x = ax + ux * acc - uy * off * side, y = ay + uy * acc + ux * off * side;
            if (insideRing(x, y, edge)) {
              const L2 = 1.2 + rnd(x, y, 223) * 2.2, W2 = L2 * (0.45 + rnd(x, y, 224) * 0.25), ang = Math.atan2(uy, ux);
              const blob = (cx0, cy0, l, w, col, op) => {
                const P = [];
                for (let j = 0; j < 10; j++) {
                  const a = j / 10 * 6.283, rr = 1 + (rnd(cx0 + j, cy0, 225) - 0.5) * 0.35;
                  const lx = Math.cos(a) * l * rr, ly = Math.sin(a) * w * rr;
                  P.push(V.p(cx0 + lx * Math.cos(ang) - ly * Math.sin(ang), cy0 + lx * Math.sin(ang) + ly * Math.cos(ang), 0));
                }
                return `<polygon points="${pts(P)}" fill="${col}" opacity="${op}" stroke-linejoin="round"/>`;
              };
              let s = blob(x, y, L2, W2, '#7f97ab', '.75') + blob(x - ux * L2 * 0.2, y - uy * L2 * 0.2, L2 * 0.45, W2 * 0.35, '#dbe8f2', '.7');
              if (rnd(x, y, 226) < 0.55) {
                const c = V.p(x, y, 0), dur = (1.2 + rnd(x, y, 227)).toFixed(2), begin = (rnd(x, y, 228) * 2).toFixed(2);
                s += `<ellipse cx="${f(c[0])}" cy="${f(c[1])}" rx=".2" ry="${f(0.2 * SE)}" fill="none" stroke="#ffffff" stroke-width=".15" opacity="0">`
                  + `<animate attributeName="rx" values=".2;${f(W2 * 0.8)}" dur="${dur}s" begin="${begin}s" repeatCount="indefinite"/><animate attributeName="ry" values="${f(0.2 * SE)};${f(W2 * 0.8 * SE)}" dur="${dur}s" begin="${begin}s" repeatCount="indefinite"/>`
                  + `<animate attributeName="opacity" values=".9;0" dur="${dur}s" begin="${begin}s" repeatCount="indefinite"/></ellipse>`;
              }
              pud.push(s);
            }
            acc += 16 + rnd(ax, acc, 229) * 22;
          }
          acc -= L;
        }
      }
      out.push(pud.join(''));
    }
    for (const r of scene.rails || []) {
      out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.rail}" stroke-width="${f(r.w)}" stroke-linecap="butt" stroke-linejoin="round"/>`);
      out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.railTie}" stroke-width="${f(r.w * 0.55)}" stroke-dasharray=".6 1.4"/>`);
      out.push(`<path d="${line(V, r.p)}" fill="none" stroke="${C.railLine}" stroke-width=".35"/>`);
    }
    const on = (x, y) => insideRing(x, y, edge);
    // gardens: their paths, drives, patios and flower beds now; fences, sheds... with the buildings
    const plotThings = [];
    for (const P of scene.plots || []) {
      if (!on(P.c[0], P.c[1])) continue;
      const bits = plotBits(V, P, on, !!opts.isHome && P.id === home.id);
      out.push(bits.ground.join(''));
      plotThings.push(...bits.things);
    }
    // schools' playgrounds
    for (const b of scene.buildings || []) if (b.lm === 'school' && b.p.every(([x, y]) => on(x, y))) out.push(playground(V, b));
    if (motion) {
      // traffic: a few cars (and a bus) driving on the left, a train now and then, people walking
      const drives = streets.filter((r) => plen(r.p) >= 50);
      const nCars = Math.min(drives.length * 2, CTX.night ? 3 : 7);
      for (let i = 0; i < nCars && drives.length; i++) {
        const r = drives[Math.floor(rnd(i, H, 310) * drives.length)], back = rnd(i, H, 311) < 0.5;
        // (on the left, between the middle and the cars parked at the kerb)
        const p = offsetLine(back ? r.p.slice().reverse() : r.p, Math.max(0.8, r.w / 4 - 0.25)), L = plen(p);
        out.push(mover(spath(V, p), L / 9, -rnd(i, H, 312) * L / 9, carSprite(CARS[Math.floor(rnd(i, H, 313) * 10) % 10]), ' rotate="auto"'));
      }
      if (drives.length && !CTX.night) {
        const r = drives.slice().sort((a, b) => b.w - a.w || plen(b.p) - plen(a.p))[0], p = offsetLine(r.p, Math.max(1, r.w / 4 - 0.1)), L = plen(p);
        out.push(mover(spath(V, p), L / 7 + 20, -rnd(H, 1, 314) * L / 7, carSprite('#c62828', 10, 2.1, '#cfe3ee'), ` rotate="auto" keyPoints="0;1;1" keyTimes="0;${(L / 7 / (L / 7 + 20)).toFixed(3)};1" calcMode="linear"`));
      }
      for (const r of scene.rails || []) {
        const L = plen(r.p);
        if (L < 80) continue;
        const run = L / 16, dur = run * 2 + 30, back = rnd(L, 1, 315) < 0.5, p = back ? r.p.slice().reverse() : r.p;
        for (let k = 0; k < 4; k++) {
          out.push(mover(spath(V, p), dur, k * 13 / 16 - rnd(L, 2, 316) * dur, carSprite(k ? '#3f51b5' : '#283593', 12, 2.6, '#cfe3ee'),
            ` rotate="auto" keyPoints="0;1;1" keyTimes="0;${(run / dur).toFixed(3)};1" calcMode="linear"`));
        }
      }
      const walks = streets.filter((r) => plen(r.p) >= 30), nPeople = Math.min(walks.length * 3, CTX.night ? 4 : CTX.wet ? 6 : 14);
      for (let i = 0; i < nPeople && walks.length; i++) {
        const r = walks[Math.floor(rnd(i, H, 320) * walks.length)], side = rnd(i, H, 321) < 0.5 ? 1 : -1;
        const p = offsetLine(r.p, side * (r.w / 2 + PAVE * 0.5)), L = plen(p), s0 = rnd(i, H, 322) * Math.max(0, L - 30);
        const bit = stretch(p, s0, Math.min(L, s0 + 30));
        if (bit.length < 2) continue;
        const walk = plen(bit) / 1.3;
        out.push(mover(spath(V, bit), walk * 2, -rnd(i, H, 323) * walk * 2, walker(i + H), ' keyPoints="0;1;0" keyTimes="0;.5;1" calcMode="linear"'));
      }
    }
    // shadows: each building's and tree's, cast on the ground (soft by day; none at night)
    if (!CTX.night) {
      // (from the real sun when Home Assistant says where it is, else from behind on the left)
      const sh = [], [sx, sy] = shadowVec(live.sun) || V.s;
      for (const b of scene.buildings || []) {
        const hh = (b.h || 6) + (b.r === 'gable' ? (b.rh || 2.5) * 0.6 : 0);
        sh.push(poly(hull(b.p.concat(b.p.map(([x, y]) => [x + sx * hh, y + sy * hh]))).map(([x, y]) => V.p(x, y, 0)), '#24401f'));
      }
      for (const [x, y, s] of scene.trees || []) {
        if (!on(x, y)) continue;
        // (a bare tree's is next to nothing, a thinning one's smaller)
        const round = rnd(x, y, 11) >= 0.36, turn = rnd(x, y, 13);
        if (round && CTX.season === 'winter' && turn < 0.4) continue;
        const thinning = round && CTX.season === 'autumn' && turn < 0.6 && rnd(x, y, 15) < 0.35;
        const r = 2.3 * (s || 1) * (thinning ? 0.55 : 1), k = 3.2 * (s || 1), c = V.p(x + sx * k, y + sy * k, 0);
        sh.push(`<ellipse cx="${f(c[0])}" cy="${f(c[1])}" rx="${f(r)}" ry="${f(r * SE)}" fill="#24401f"/>`);
      }
      // (faint under a grey sky)
      out.push(`<g opacity="${/rain|pour|cloudy$|fog|snow|hail|lightning/.test(wx) && wx !== 'partlycloudy' ? '.07' : '.2'}">${sh.join('')}</g>`);
    }
    // street lamps along the bigger streets, every 34 m or so, either side in turn
    const lamps = [];
    for (const r of streets) {
      let acc = 10 + rnd(r.p[0][0], r.p[0][1], 60) * 20, side = 1;
      for (let i = 0; i < r.p.length - 1; i++) {
        const [ax, ay] = r.p[i], [bx, by] = r.p[i + 1], L = Math.hypot(bx - ax, by - ay);
        if (!L) continue;
        const ux = (bx - ax) / L, uy = (by - ay) / L, off = r.w / 2 + PAVE * 0.8;
        while (acc < L) {
          const x = ax + ux * acc - uy * off * side, y = ay + uy * acc + ux * off * side;
          if (on(x, y) && !lamps.some(([u, v]) => Math.hypot(u - x, v - y) < 14)) lamps.push([x, y]);
          side = -side; acc += 34;
        }
        acc -= L;
      }
    }
    const gid = 'nvg' + Math.random().toString(36).slice(2, 8);
    out.push(`<defs><radialGradient id="${gid}"><stop offset="0" stop-color="${LIGHT}" stop-opacity=".6"/><stop offset=".55" stop-color="${LIGHT}" stop-opacity=".22"/><stop offset="1" stop-color="${LIGHT}" stop-opacity="0"/></radialGradient></defs>`);
    if (CTX.night) for (const [x, y] of lamps) { const g = V.p(x, y, 0); out.push(`<ellipse cx="${f(g[0])}" cy="${f(g[1])}" rx="8" ry="${f(8 * SE)}" fill="url(#${gid})"/>`); }
    // your house: a ring pulsing out on the ground round it, so it's easy to spot
    if (opts.isHome) {
      const g = V.p(home.x || 0, home.y || 0, 0), pc0 = opts.pinColour || C.pin;
      for (const k of [0, 1.6]) {
        out.push(`<ellipse cx="${f(g[0])}" cy="${f(g[1])}" rx="6" ry="${f(6 * SE)}" fill="none" stroke="${pc0}" stroke-width=".9" opacity="0">`
          + `<animate attributeName="rx" values="6;17" dur="3.2s" begin="${k}s" repeatCount="indefinite"/><animate attributeName="ry" values="${f(6 * SE)};${f(17 * SE)}" dur="3.2s" begin="${k}s" repeatCount="indefinite"/>`
          + `<animate attributeName="opacity" values=".8;0" dur="3.2s" begin="${k}s" repeatCount="indefinite"/></ellipse>`);
      }
    }
    out.push('</g>');
    // a waterfall where a river runs off the front edge
    for (const wv of scene.water || []) {
      for (let i = 0; i < wv.p.length - 1; i++) {
        const [ax, ay] = wv.p[i], [bx, by] = wv.p[i + 1], L = Math.hypot(bx - ax, by - ay);
        let prev = null;
        for (let s = 0; s <= L; s += 1) {
          const x = ax + (bx - ax) * s / (L || 1), y = ay + (by - ay) * s / (L || 1), inn = insideRing(x, y, edge);
          if (prev && prev[2] !== inn) {
            const E = inn ? [x, y] : [prev[0], prev[1]];
            let ei = 0, bd = Infinity;
            edge.forEach((q, j) => { const d = Math.hypot(q[0] - E[0], q[1] - E[1]); if (d < bd) { bd = d; ei = j; } });
            const p0 = edge[ei], q0 = edge[(ei + 1) % edge.length], [, aw] = V.n(q0[1] - p0[1], -(q0[0] - p0[0]));
            if (aw < 0) {
              const top = V.p(E[0], E[1], -0.3), bot = V.p(E[0], E[1], -p0[2] - 16), ww = Math.max(1.2, wv.w * 0.45), wid = 'nvf' + Math.random().toString(36).slice(2, 8);
              let s2 = `<defs><linearGradient id="${wid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${C.water}"/><stop offset=".75" stop-color="#d6ecfa" stop-opacity=".85"/><stop offset="1" stop-color="#ffffff" stop-opacity="0"/></linearGradient></defs>`
                + poly([[top[0] - ww, top[1]], [top[0] + ww, top[1]], [bot[0] + ww * 1.4, bot[1]], [bot[0] - ww * 1.4, bot[1]]], `url(#${wid})`);
              for (let k = -1; k <= 1; k++) {
                s2 += `<line x1="${f(top[0] + k * ww * 0.5)}" y1="${f(top[1])}" x2="${f(bot[0] + k * ww * 0.7)}" y2="${f(bot[1])}" stroke="#ffffff" stroke-width=".25" stroke-dasharray="1.5 2.5" opacity=".7">`
                  + `<animate attributeName="stroke-dashoffset" from="0" to="-8" dur="${(0.6 + k * 0.08 + 0.1).toFixed(2)}s" repeatCount="indefinite"/></line>`;
              }
              for (let k = 0; k < 3; k++) {
                s2 += `<circle cx="${f(bot[0] + (k - 1) * ww)}" cy="${f(bot[1] - 1)}" r="${f(ww)}" fill="#ffffff" opacity=".3"><animate attributeName="r" values="${f(ww * 0.8)};${f(ww * 1.6)};${f(ww * 0.8)}" dur="${2 + k * 0.4}s" repeatCount="indefinite"/></circle>`;
              }
              out.push(s2);
            }
          }
          prev = [x, y, inn];
        }
      }
    }
    // (points along the streets, on the screen: where a bridge to another map can start)
    const ends = [];
    for (const r of streets) {
      for (let i = 0; i < r.p.length - 1; i++) {
        const [ax, ay] = r.p[i], [bx, by] = r.p[i + 1], n = Math.max(1, Math.ceil(Math.hypot(bx - ax, by - ay) / 6));
        // (with the street's way on the screen, so a bridge can leave along it)
        const sa = V.p(ax, ay, 0), sb = V.p(bx, by, 0), sl = Math.hypot(sb[0] - sa[0], sb[1] - sa[1]) || 1;
        const ddx = (sb[0] - sa[0]) / sl, ddy = (sb[1] - sa[1]) / sl;
        for (let k = 0; k <= n; k++) {
          const x = ax + (bx - ax) * k / n, y = ay + (by - ay) * k / n;
          if (insideRing(x, y, edge)) ends.push(V.p(x, y, 0).concat([ddx, ddy, r.w]));
        }
      }
    }
    if (!ends.length) for (const [x, y] of edge) ends.push(V.p(x * 0.97, y * 0.97, 0).concat([0, 0, 6]));
    // (at night, with someone home: a warm glow on the ground round your house)
    if (opts.isHome && CTX.night && CTX.homeLit && people.length) {
      const g = V.p(home.x || 0, home.y || 0, 0);
      out.push(`<ellipse cx="${f(g[0])}" cy="${f(g[1])}" rx="18" ry="${f(18 * SE)}" fill="url(#${gid})"/>`);
    }
    // the buildings and trees, back to front
    const things = [];
    let pin = null;
    // (only what's on the chunk: a building the torn edge cuts through isn't drawn)
    for (const b of scene.buildings || []) {
      const [cx, cy] = centroid(b.p), isHome = !!opts.isHome && home.id != null && b.id === home.id;
      if (!isHome && !b.p.every(([x, y]) => on(x, y))) continue;
      const d = building(V, b, isHome);
      if (isHome) pin = d.top;
      const attrs = opts.pick && opts.isHome ? ` data-id="${b.id}" class="bld"` : '';
      things.push([V.d(cx, cy), `<g${attrs}>${d.svg}</g>`]);
    }
    for (const t of scene.trees || []) {
      if (!on(t[0], t[1])) continue;
      const s = tree(V, t);
      // (on a windy day, swaying, each in its own time)
      things.push([V.d(t[0], t[1]), CTX.windy ? `<g class="nvsway" style="animation-delay:-${(rnd(t[0], t[1], 210) * 3).toFixed(2)}s">${s}</g>` : s]);
    }
    for (const c of scene.cars || []) if (on(c[0], c[1])) things.push([V.d(c[0], c[1]), car(V, c)]);
    for (const L of lamps) things.push([V.d(L[0], L[1]), lamp(V, L)]);
    things.push(...plotThings);
    // street furniture: OpenStreetMap's bus stops, benches, post boxes and bins, and more besides:
    // benches along footpaths (some with a bin), post boxes at some street corners
    const nearAng = (x, y) => {
      let best = [Infinity, 0];
      for (const r of roads) for (let i = 0; i < r.p.length - 1; i++) {
        const [ax, ay] = r.p[i], [bx, by] = r.p[i + 1], vx = bx - ax, vy = by - ay, l2 = vx * vx + vy * vy || 1;
        const tt = Math.max(0, Math.min(1, ((x - ax) * vx + (y - ay) * vy) / l2)), d = Math.hypot(ax + vx * tt - x, ay + vy * tt - y);
        if (d < best[0]) best = [d, Math.atan2(vy, vx)];
      }
      return best[1];
    };
    const furn = (scene.poi || []).map(([x, y, k]) => [x, y, k]);
    for (const r of paths) {
      let acc = 20;
      const L = plen(r.p);
      while (acc < L) {
        const [q] = stretch(r.p, acc, acc + 1), q2 = stretch(r.p, acc, acc + 1)[1] || q, ang = Math.atan2(q2[1] - q[1], q2[0] - q[0]);
        if (q && rnd(q[0], q[1], 390) < 0.35) {
          const x = q[0] - Math.sin(ang) * 1.6, y = q[1] + Math.cos(ang) * 1.6;
          furn.push([x, y, 'bench', ang]);
          if (rnd(x, y, 391) < 0.5) furn.push([x + Math.cos(ang) * 1.4, y + Math.sin(ang) * 1.4, 'bin']);
        }
        acc += 45;
      }
    }
    for (const {P, legs, w: jw} of joins.values()) {
      if (legs.length < 3 || rnd(P[0], P[1], 392) > 0.3) continue;
      const a = legs[0], b = legs[1], bx = a.ux + b.ux, by = a.uy + b.uy, bl = Math.hypot(bx, by) || 1, d = (jw / 2 + PAVE * 0.75) * 1.45;
      furn.push([P[0] + bx / bl * d, P[1] + by / bl * d, 'post_box']);
    }
    for (const [x, y, k, ang] of furn) if (on(x, y)) things.push([V.d(x, y), furniture(V, x, y, k, ang ?? nearAng(x, y))]);
    things.sort((a, b) => b[0] - a[0]);
    for (const t of things) out.push(t[1]);
    // rain splashing on the ground all over (or hailstones lying about)
    if (CTX.wet || CTX.hail) {
      const sp = [];
      for (let i = 0; i < (CTX.hail ? 70 : 36); i++) {
        const x = (rnd(i, H, 230) - 0.5) * 2 * H, y = (rnd(H, i, 231) - 0.5) * 2 * H;
        if (!on(x, y)) continue;
        const c = V.p(x, y, 0);
        if (CTX.hail) { sp.push(`<circle cx="${f(c[0])}" cy="${f(c[1])}" r=".22" fill="#ffffff" opacity=".9"/>`); continue; }
        const dur = (0.7 + rnd(i, 1, 232) * 0.6).toFixed(2), begin = (rnd(i, 2, 233) * 1.5).toFixed(2);
        sp.push(`<ellipse cx="${f(c[0])}" cy="${f(c[1])}" rx=".1" ry=".06" fill="none" stroke="#e8f2fa" stroke-width=".18" opacity="0">`
          + `<animate attributeName="rx" values=".1;.9" dur="${dur}s" begin="${begin}s" repeatCount="indefinite"/><animate attributeName="ry" values=".06;${f(0.9 * SE)}" dur="${dur}s" begin="${begin}s" repeatCount="indefinite"/>`
          + `<animate attributeName="opacity" values=".85;0" dur="${dur}s" begin="${begin}s" repeatCount="indefinite"/></ellipse>`);
      }
      out.push(`<g pointer-events="none">${sp.join('')}</g>`);
    }
    // night: everything darker and bluer, but the lit windows
    if (CTX.night) {
      const cache = {};
      for (let i = 0; i < out.length; i++) {
        out[i] = out[i].replace(/#[0-9a-f]{6}/gi, (c) => (c === LIGHT || c === LIGHT2 ? c : (cache[c] = cache[c] || mix(c, '#0b1736', 0.6))));
      }
    }
    // the pin over your home (or the place's middle), and who's there over it
    if (!pin) pin = V.p(home.x || 0, home.y || 0, 0);
    const zs = Math.pow(opts.zoom || 1, 0.9), fs = PIN_H * 0.034 / zs, pc = opts.pinColour || C.pin;
    let top = pin[1];
    if (!opts.hideLabel) {
      // (the same size on the screen however far it's zoomed in)
      const label = esc(opts.label || 'HOME'), w = label.length * fs * 0.66 + fs * 1.6, ph = fs * 1.9;
      top = pin[1] - PIN_H * 0.13 / zs;
      out.push(`<line x1="${f(pin[0])}" y1="${f(pin[1])}" x2="${f(pin[0])}" y2="${f(top)}" stroke="${pc}" stroke-width="${f(fs * 0.14)}"/>`
        + `<circle cx="${f(pin[0])}" cy="${f(pin[1])}" r="${f(fs * 0.3)}" fill="${pc}"/>`
        + `<rect x="${f(pin[0] - w / 2)}" y="${f(top - ph + fs * 0.28)}" width="${f(w)}" height="${f(ph)}" rx="${f(ph / 2)}" fill="#000000" opacity=".25"/>`
        + `<rect x="${f(pin[0] - w / 2)}" y="${f(top - ph)}" width="${f(w)}" height="${f(ph)}" rx="${f(ph / 2)}" fill="${pc}" stroke="#ffffff" stroke-width="${f(fs * 0.12)}"/>`
        + `<text x="${f(pin[0])}" y="${f(top - ph / 2)}" fill="${C.pinText}" font-size="${f(fs)}" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-weight="700" letter-spacing="${f(fs * 0.08)}" text-anchor="middle" dominant-baseline="central">${label}</text>`);
      top -= ph;
      const here = opts.atPin || [], r = fs * 1.05;
      here.forEach((p, i) => {
        out.push(avatar(pin[0] + (i - (here.length - 1) / 2) * r * 2.3, top - r * 1.45, r, fs, p, `${p.name}: ${opts.isHome ? 'home' : opts.label}`));
      });
    }
    // people out and about on this map: their face on a stalk where they are
    for (const {p, x, y} of opts.onMap || []) {
      const g = V.p(x, y, 0), r = fs * 0.85, ty = g[1] - PIN_H * 0.07 / zs;
      out.push(`<ellipse cx="${f(g[0])}" cy="${f(g[1])}" rx="${f(r * 0.6)}" ry="${f(r * 0.6 * SE)}" fill="#000000" opacity=".25"/>`
        + `<line x1="${f(g[0])}" y1="${f(g[1])}" x2="${f(g[0])}" y2="${f(ty)}" stroke="#ffffff" stroke-width="${f(fs * 0.16)}"/>`
        + avatar(g[0], ty - r, r, fs, p, `${p.name}: here`));
    }
    // the box around it all (for the viewBox)
    const corners = [];
    for (const [x, y, dp] of edge) corners.push(V.p(x, y, 0), V.p(x, y, -dp));
    const xs = corners.map((c) => c[0]), ys = corners.map((c) => c[1]).concat([top - fs * 3.5, pin[1] - PIN_H * 0.2 / zs], low > -Infinity ? [low + 2] : []);
    const m = H * 0.04, x0 = Math.min(...xs) - m, y0 = Math.min(...ys) - m, w = Math.max(...xs) - x0 + m, h = Math.max(...ys) - y0 + m * 2.2;
    return {svg: out.join(''), box: [x0, y0, w, h], pin: [pin[0], pin[1] - PIN_H * 0.06 / zs], ends};
  }

  // A point's place on a map (metres from its middle), from latitude and longitude
  function onScene(sc, lat, lon) {
    const R = 6371008.8, rad = Math.PI / 180;
    return [(lon - sc.lon) * rad * R * Math.cos(sc.lat * rad), (lat - sc.lat) * rad * R];
  }

  /* Where everyone is: over your house (home), on a map where their tracker puts them, over a
   * place they're at (their zone's name), or away (just their chip). */
  function whereabouts(scene, places, people) {
    const out = {home: [], homeMap: [], places: places.map(() => ({at: [], map: []})), away: []};
    for (const p of people) {
      if (p.home) { out.home.push(p); continue; }
      let done = false;
      if (p.lat != null && p.lon != null) {
        const maps = [[scene, out.homeMap], ...places.map((pl, i) => [pl.scene, out.places[i].map])];
        for (const [sc, list] of maps) {
          if (!sc || sc.lat == null) continue;
          const [x, y] = onScene(sc, Number(p.lat), Number(p.lon)), lim = (sc.half || 150) * 0.94;
          if (Math.abs(x) <= lim && Math.abs(y) <= lim) { list.push({p, x, y}); done = true; break; }
        }
      }
      if (!done && p.state) {
        const i = places.findIndex((pl) => String(pl.name || '').toLowerCase() === String(p.state).toLowerCase());
        if (i >= 0) { out.places[i].at.push(p); done = true; }
      }
      if (!done) out.away.push(p);
    }
    return out;
  }

  /* A bridge from a on your map to b on another's (screen points at ground level, with their
   * street's way on the screen [x, y, dx, dy]), sa and sb their scales: an S-shaped road that
   * leaves each map along its street and arches gently over the gap, in the roads' own colours,
   * with a slim side and low rails so it doesn't shout. */
  function bridge(a, b, sa, sb, night) {
    const col = (c) => (night ? mix(c, '#0b1736', 0.6) : c);
    const cx = b[0] - a[0], cy = b[1] - a[1], dist = Math.hypot(cx, cy) || 1, ux = cx / dist, uy = cy / dist;
    // (each end's way out: along its street, towards the other end, eased a little towards it)
    const way = (p, tx, ty) => {
      let dx = p[2] || 0, dy = p[3] || 0;
      if (!dx && !dy) { dx = tx; dy = ty; }
      if (dx * tx + dy * ty < 0) { dx = -dx; dy = -dy; }
      // (straight on from the street, so its kerbs carry on; eased towards the other end only
      // when the street runs nearly across the gap)
      const along = dx * tx + dy * ty;
      if (along < 0.35) { const k2 = (0.35 - along) * 1.2; dx += tx * k2; dy += ty * k2; }
      const l = Math.hypot(dx, dy) || 1;
      return [dx / l, dy / l];
    };
    const ta = way(a, ux, uy), tb = way(b, -ux, -uy), k = dist * 0.45;
    const P1 = [a[0] + ta[0] * k, a[1] + ta[1] * k], P2 = [b[0] + tb[0] * k, b[1] + tb[1] * k];
    const N = 36, mid = [], L = [], R = [], Ld = [], Rd = [], Lr = [], Rr = [];
    const wa = a[4] || 6, wb = b[4] || 6, rise = 2.6, thick = 1.3, rail = 0.9, RW = [];
    for (let i = 0; i <= N; i++) {
      const t = i / N, u = 1 - t, s = sa + (sb - sa) * t;
      // (each end as wide as the street it carries on: the road, then a pavement each side)
      const rw = (wa + (wb - wa) * t) / 2, W = rw + PAVE + 0.3;
      RW.push(rw / W);
      const x = u * u * u * a[0] + 3 * u * u * t * P1[0] + 3 * u * t * t * P2[0] + t * t * t * b[0];
      const y0 = u * u * u * a[1] + 3 * u * u * t * P1[1] + 3 * u * t * t * P2[1] + t * t * t * b[1];
      const dx = 3 * u * u * (P1[0] - a[0]) + 6 * u * t * (P2[0] - P1[0]) + 3 * t * t * (b[0] - P2[0]);
      const dy = 3 * u * u * (P1[1] - a[1]) + 6 * u * t * (P2[1] - P1[1]) + 3 * t * t * (b[1] - P2[1]);
      // (across it, flat on the ground, a metre long at this scale)
      const gl = Math.hypot(dx, dy / SE) || 1, px = (dy / SE) / gl * s, py = (-dx * SE) / gl * s;
      const y = y0 - rise * Math.sin(Math.PI * t) * CE * s;
      mid.push([x, y]);
      L.push([x + px * W, y + py * W]); R.push([x - px * W, y - py * W]);
      Ld.push([x + px * W, y + py * W + thick * CE * s]); Rd.push([x - px * W, y - py * W + thick * CE * s]);
      Lr.push([x + px * W, y + py * W - rail * CE * s]); Rr.push([x - px * W, y - py * W - rail * CE * s]);
    }
    const side = (top, down) => poly(top.concat(down.slice().reverse()), col('#8c8173'));
    const inner = () => mid.map(([x, y], i) => [x + (L[i][0] - x) * RW[i], y + (L[i][1] - y) * RW[i]]).concat(mid.map(([x, y], i) => [x + (R[i][0] - x) * RW[i], y + (R[i][1] - y) * RW[i]]).reverse());
    return `<g class="nvbridge">`
      // its slim sides (both: an S shows each in turn), then the deck: kerbs, the road, its line
      + side(L, Ld) + side(R, Rd)
      + poly(L.concat(R.slice().reverse()), col(C.kerb))
      + poly(inner(), col(C.road))
      + `<polyline points="${pts(mid)}" fill="none" stroke="${col(C.roadLine)}" stroke-width=".3" stroke-dasharray="2.5 4" opacity=".85"/>`
      // low rails
      + `<polyline points="${pts(Lr)}" fill="none" stroke="${col('#f1ece2')}" stroke-width=".35" opacity=".8" stroke-linejoin="round"/>`
      + `<polyline points="${pts(Rr)}" fill="none" stroke="${col('#f1ece2')}" stroke-width=".35" opacity=".8" stroke-linejoin="round"/>`
      + Lr.filter((q, i) => i % 3 === 0).map((q, i) => `<line x1="${f(q[0])}" y1="${f(q[1])}" x2="${f(L[i * 3][0])}" y2="${f(L[i * 3][1])}" stroke="${col('#cfc6b6')}" stroke-width=".2"/>`).join('')
      + Rr.filter((q, i) => i % 3 === 0).map((q, i) => `<line x1="${f(q[0])}" y1="${f(q[1])}" x2="${f(R[i * 3][0])}" y2="${f(R[i * 3][1])}" stroke="${col('#cfc6b6')}" stroke-width=".2"/>`).join('')
      + '</g>';
  }

  /* The nearest pair of points between two sets (a bridge's ends): each cut to those nearest the
   * other's middle first, so it's quick. */
  function nearestPair(A, B, ca, cb) {
    const near = (list, c) => list.map((p) => [Math.hypot(p[0] - c[0], p[1] - c[1]), p]).sort((x, y) => x[0] - y[0]).slice(0, 160).map((x) => x[1]);
    const a = near(A, cb), b = near(B, ca);
    let best = null, bd = Infinity;
    for (const p of a) for (const q of b) {
      const d = (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2;
      if (d < bd) { bd = d; best = [p, q]; }
    }
    return best;
  }

  /**
   * The drawing as SVG text: your home's map, with the other places' maps beside it (left, right,
   * above, below; several on one side share it). opts: {rot: 0-3 (quarter turns), zoom, label: the
   * pin's text, pick: true (your map's buildings can be clicked: data-id), hideLabel, live,
   * places: [{name, side, scene}]}
   */
  function draw(scene, opts = {}) {
    const live = opts.live || {}, all = (opts.places || []).filter((pl) => pl && pl.scene);
    const whoAll = whereabouts(scene, all, live.people || []);
    // (another place's map only shows while someone's there)
    const keep = all.map((pl, i) => whoAll.places[i].at.length + whoAll.places[i].map.length > 0);
    const places = all.filter((pl, i) => keep[i]);
    const who = {...whoAll, places: whoAll.places.filter((x, i) => keep[i])};
    const homeI = island(scene, {...opts, isHome: true, atPin: who.home, onMap: who.homeMap});
    const [hx, hy, hw, hh] = homeI.box;
    const gap = hw * 0.025;
    const groups = [`<g class="nvisl" data-f="" data-k="">${homeI.svg}</g>`], bridges = [];
    const hc = [hx + hw / 2, hy + hh / 2];
    const boxes = [[hx, hy, hx + hw, hy + hh]];
    const PLACE_PINS = ['#7e57c2', '#00897b', '#f4511e', '#6d4c41', '#c2185b', '#3949ab'];
    const bySide = {left: [], right: [], up: [], down: []};
    places.forEach((pl, i) => {
      const I = island(pl.scene, {rot: opts.rot, zoom: opts.zoom, live, month: opts.month, date: opts.date, motion: opts.motion, isHome: false, label: String(pl.name || 'PLACE').toUpperCase(),
        pinColour: PLACE_PINS[i % PLACE_PINS.length], atPin: who.places[i].at, onMap: who.places[i].map});
      I.key = String(pl.zone || pl.name || i);
      (bySide[pl.side] || bySide.left).push(I);
    });
    const place = (I, tx, ty, sc) => {
      const [bx, by, bw, bh] = I.box;
      const dx = tx - bx * sc, dy = ty - by * sc;
      groups.push(`<g class="nvisl" data-k="${esc(I.key)}" data-f="${f(dx + I.pin[0] * sc)} ${f(dy + I.pin[1] * sc)}" transform="translate(${f(dx)} ${f(dy)}) scale(${sc.toFixed(4)})">${I.svg}</g>`);
      boxes.push([tx, ty, tx + bw * sc, ty + bh * sc]);
      // a bridge from the nearest of your streets to the nearest of its
      const ends = I.ends.map((p) => [dx + p[0] * sc, dy + p[1] * sc, p[2], p[3], p[4]]);
      const pair = nearestPair(homeI.ends, ends, hc, [tx + bw * sc / 2, ty + bh * sc / 2]);
      if (pair) bridges.push(bridge(pair[0], pair[1], 1, sc, !!live.night));
    };
    // (left and right: a column as tall as your map, shared; above and below: a row as wide)
    for (const side of ['left', 'right']) {
      const list = bySide[side];
      if (!list.length) continue;
      const need = list.reduce((t, I) => t + I.box[3], 0) + gap * (list.length - 1);
      const sc = Math.min(1, hh / need), colW = Math.max(...list.map((I) => I.box[2])) * sc;
      let ty = hy + hh / 2 - (need * sc) / 2;
      for (const I of list) {
        const x = side === 'left' ? hx - gap - colW / 2 - (I.box[2] * sc) / 2 : hx + hw + gap + colW / 2 - (I.box[2] * sc) / 2;
        place(I, x, ty, sc);
        ty += I.box[3] * sc + gap * sc;
      }
    }
    for (const side of ['up', 'down']) {
      const list = bySide[side];
      if (!list.length) continue;
      const need = list.reduce((t, I) => t + I.box[2], 0) + gap * (list.length - 1);
      const sc = Math.min(1, hw / need), rowH = Math.max(...list.map((I) => I.box[3])) * sc;
      let tx = hx + hw / 2 - (need * sc) / 2;
      for (const I of list) {
        const y = side === 'up' ? hy - gap - rowH / 2 - (I.box[3] * sc) / 2 : hy + hh + gap + rowH / 2 - (I.box[3] * sc) / 2;
        place(I, tx, y, sc);
        tx += I.box[2] * sc + gap * sc;
      }
    }
    const x0 = Math.min(...boxes.map((b) => b[0])), y0 = Math.min(...boxes.map((b) => b[1]));
    const w = Math.max(...boxes.map((b) => b[2])) - x0, h = Math.max(...boxes.map((b) => b[3])) - y0;
    const pin = homeI.pin;
    // now and then a few birds fly over (by day, when it's not wet)
    let birds = '';
    const wx = (live.weather || {}).state || '';
    if (!live.night && !/rain|pour|snow|hail|lightning|fog/.test(wx)) {
      const flock = (n, y, dur, begin, dir) => {
        const ya = y0 + h * y, yb = ya - h * 0.12, xa = dir > 0 ? x0 - 30 : x0 + w + 30, xb = dir > 0 ? x0 + w + 30 : x0 - 30;
        let s = '';
        for (let i = 0; i < n; i++) {
          const ox = -dir * Math.ceil(i / 2) * 5.5, oy = (i % 2 ? 1 : -1) * Math.ceil(i / 2) * 3, sz = 2.4 + (i % 3) * 0.3;
          const up = `M${f(ox - sz)} ${f(oy - sz * 0.5)}Q${f(ox - sz * 0.4)} ${f(oy - sz * 0.6)} ${f(ox)} ${f(oy)}Q${f(ox + sz * 0.4)} ${f(oy - sz * 0.6)} ${f(ox + sz)} ${f(oy - sz * 0.5)}`;
          const dn = `M${f(ox - sz)} ${f(oy + sz * 0.3)}Q${f(ox - sz * 0.4)} ${f(oy - sz * 0.1)} ${f(ox)} ${f(oy)}Q${f(ox + sz * 0.4)} ${f(oy - sz * 0.1)} ${f(ox + sz)} ${f(oy + sz * 0.3)}`;
          s += `<path d="${up}" fill="none" stroke="#2c3440" stroke-width=".35" stroke-linecap="round"><animate attributeName="d" values="${up};${dn};${up}" dur="${(0.5 + i * 0.07).toFixed(2)}s" repeatCount="indefinite"/></path>`;
        }
        return `<g opacity="0"><animateTransform attributeName="transform" type="translate" values="${f(xa)} ${f(ya)};${f(xb)} ${f(yb)};${f(xb)} ${f(yb)}" keyTimes="0;.55;1" dur="${dur}s" begin="${begin}s" repeatCount="indefinite"/>`
          + `<animate attributeName="opacity" values="1;1;0;0" keyTimes="0;.55;.56;1" dur="${dur}s" begin="${begin}s" repeatCount="indefinite"/>${s}</g>`;
      };
      birds = `<g class="nvbirds" pointer-events="none">${flock(5, 0.3, 40, 3, 1)}${flock(3, 0.62, 55, 24, -1)}</g>`;
    }
    return {svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${f(x0)} ${f(y0)} ${f(w)} ${f(h)}" data-box="${f(x0)} ${f(y0)} ${f(w)} ${f(h)}" data-pin="${f(pin[0])} ${f(pin[1])}" data-zoom="${opts.zoom || 1}" preserveAspectRatio="xMidYMid meet" style="width:100%;height:100%;display:block;position:relative" role="img" aria-label="The streets around your home">${groups.join('')}${bridges.join('')}${birds}${live.night && occasion(opts.date ? new Date(opts.date) : new Date()).fireworks ? fireworks(x0, y0, w, h) : ''}</svg>`, away: who.away};
  }

  /* Fits the drawing to its box: all of it where the box is about its shape; in a much narrower
   * (or flatter) box, e.g. a phone held upright, closer in around your home (up to MAX_ZOOM),
   * rather than tiny in the middle. Done again as the box changes size. */
  const MAX_ZOOM = 2.4, MAX_TOTAL = 10;
  function fit(el) {
    const svg = el.querySelector('svg');
    if (!svg) return;
    // (round your house, or the place you tapped while it's still shown)
    const fg = el._nvFocus ? [...svg.querySelectorAll('.nvisl')].find((g) => g.dataset.k === el._nvFocus) : null;
    if (el._nvFocus && !fg) el._nvFocus = null;
    const [x0, y0, w, h] = svg.dataset.box.split(' ').map(Number), [px, py] = (fg ? fg.dataset.f : svg.dataset.pin).split(' ').map(Number);
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const boxAr = r.width / r.height, ar = w / h;
    // (closer in for a box much narrower or flatter than the drawing, on top of the zoom chosen)
    const shapeZ = Math.min(MAX_ZOOM, Math.max(1, boxAr < ar ? ar / boxAr : boxAr / ar) ** 0.75);
    // (zoomed right out: all of it, other places too)
    const uz = Number(svg.dataset.zoom) || 1, z = uz <= 1 ? 1 : Math.min(MAX_TOTAL, uz * Math.sqrt(shapeZ));
    let vw, vh;
    if (boxAr < ar) { vw = w / z; vh = vw / boxAr; } else { vh = h / z; vw = vh * boxAr; }
    const clampTo = (c, size, lo, full) => (size >= full ? lo + (full - size) / 2 : Math.min(lo + full - size, Math.max(lo, c - size / 2)));
    svg.setAttribute('viewBox', `${f(clampTo(px, vw, x0, w))} ${f(clampTo(py, vh, y0, h))} ${f(vw)} ${f(vh)}`);
  }

  function personColour(key) {
    return pick(['#e53935', '#8e24aa', '#3949ab', '#00897b', '#f4511e', '#6d4c41', '#c2185b', '#2e7d32'], rnd(String(key).length, String(key).charCodeAt(0) + String(key).charCodeAt(String(key).length - 1), 50));
  }

  // The weather over the map (rain, snow, fog, cloud shadows, a flash of lightning): HTML layers
  // over the drawing, the same whatever the zoom
  const WEATHER = {
    'sunny': ['☀', 'Sunny'], 'clear-night': ['☾', 'Clear'], 'partlycloudy': ['⛅', 'Partly cloudy'], 'cloudy': ['☁', 'Cloudy'],
    'fog': ['🌫', 'Fog'], 'rainy': ['🌧', 'Rain'], 'pouring': ['🌧', 'Heavy rain'], 'snowy': ['❄', 'Snow'], 'snowy-rainy': ['🌨', 'Sleet'],
    'hail': ['🌨', 'Hail'], 'lightning': ['⚡', 'Thunder'], 'lightning-rainy': ['⛈', 'Thunderstorms'], 'windy': ['💨', 'Windy'],
    'windy-variant': ['💨', 'Windy'], 'exceptional': ['⚠', 'Severe weather'],
  };
  // puffy clouds drifting behind the maps: each a few soft circles
  const CLOUDS = [[6, 72], [17, 24], [29, 58], [41, 14], [53, 84], [64, 36], [77, 66], [89, 18]].map(([x, y], i) =>
    [[0, 6, 26], [26, -8, 34], [56, 0, 28], [80, 8, 20], [38, 12, 26]].map(([dx, dy, r]) => {
      const k = 0.75 + (i % 3) * 0.2;
      return `radial-gradient(circle ${Math.round(r * k)}px at calc(${x}% + ${Math.round(dx * k)}px) calc(${y}% + ${Math.round(dy * k)}px),rgba(255,255,255,.88) 0 70%,rgba(255,255,255,0) 100%)`;
    }).join(',')).join(',');
  /* Rain and snow as tiles of streaks or flakes (the same every time), slid down by the browser's
   * compositor (transform, not background-position), so they stay smooth however busy the map is.
   * Each tile repeats seamlessly: a streak or flake crossing an edge is drawn on the other side too. */
  function fxTile(size, n, seed, one) {
    let s = '';
    for (let i = 0; i < n; i++) {
      const x = rnd(seed, i, 400) * size, y = rnd(i, seed, 401) * size, k = rnd(seed + 1, i, 402);
      for (const dx of [-size, 0, size]) for (const dy of [-size, 0, size]) s += one(x + dx, y + dy, k);
    }
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}">${s}</svg>`;
    return `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`;
  }
  const streak = (len, w, a) => (x, y, k) => `<line x1="${f(x)}" y1="${f(y)}" x2="${f(x)}" y2="${f(y + len * (0.7 + 0.6 * k))}" stroke="rgba(205,225,255,${a})" stroke-width="${w}" stroke-linecap="round"/>`;
  const flake = (r, a) => (x, y, k) => `<circle cx="${f(x)}" cy="${f(y)}" r="${f(r * (0.6 + 0.8 * k))}" fill="rgba(255,255,255,${a})"/>`;
  const RAIN_FAR = fxTile(256, 34, 1, streak(12, 1, 0.38)), RAIN_NEAR = fxTile(256, 16, 2, streak(22, 1.6, 0.5));
  const RAIN_HEAVY = fxTile(256, 40, 3, streak(26, 1.8, 0.55));
  const SNOW_FAR = fxTile(300, 40, 4, flake(1.3, 0.75)), SNOW_NEAR = fxTile(300, 18, 5, flake(2.4, 0.95));
  const FX_CSS = `
    .nvfx{position:absolute;inset:0;pointer-events:none;overflow:hidden}
    .nv-tilt{position:absolute;inset:-30%;transform:rotate(12deg)}
    .nv-fall{position:absolute;left:0;right:0;top:-300px;bottom:0;background-repeat:repeat;will-change:transform;animation:nvfall256 linear infinite}
    .nv-fall.rf{background-image:${RAIN_FAR};animation-duration:.85s;opacity:.75}
    .nv-fall.rn{background-image:${RAIN_NEAR};animation-duration:.5s}
    .nv-fall.rh{background-image:${RAIN_HEAVY};animation-duration:.38s}
    .nv-fall.sf{background-image:${SNOW_FAR};animation-duration:14s;animation-name:nvfall300}
    .nv-fall.sn{background-image:${SNOW_NEAR};animation-duration:8s;animation-name:nvfall300}
    @keyframes nvfall256{from{transform:translate3d(0,0,0)}to{transform:translate3d(0,256px,0)}}
    @keyframes nvfall300{from{transform:translate3d(0,0,0)}to{transform:translate3d(0,300px,0)}}
    .nv-sway{position:absolute;inset:0;animation:nvsway2 4s ease-in-out infinite alternate;will-change:transform}
    @keyframes nvsway2{from{transform:translate3d(-14px,0,0)}to{transform:translate3d(14px,0,0)}}
    .nv-fog{background:linear-gradient(180deg,rgba(235,240,245,.55),rgba(235,240,245,.25) 60%,rgba(235,240,245,.45));animation:nvfog 12s ease-in-out infinite alternate}
    @keyframes nvfog{to{opacity:.6}}
    .nv-cloud{position:absolute;top:0;bottom:0;left:0;width:200%;will-change:transform;animation:nvcloud 70s linear infinite;background-repeat:repeat-x;background-size:50% 100%;
      background-image:radial-gradient(ellipse 22% 14% at 20% 30%,rgba(20,30,50,.20),transparent 70%),radial-gradient(ellipse 26% 16% at 70% 60%,rgba(20,30,50,.18),transparent 70%),radial-gradient(ellipse 18% 12% at 45% 85%,rgba(20,30,50,.16),transparent 70%)}
    .nv-cloud.light{opacity:.55}
    @keyframes nvcloud{from{transform:translate3d(0,0,0)}to{transform:translate3d(-50%,0,0)}}
    .nv-grey{background:rgba(70,80,95,.16)}
    .nv-sun{background:radial-gradient(ellipse at 15% 0%,rgba(255,220,130,.22),transparent 60%)}
    .nv-flash{background:#fff;opacity:0;animation:nvflash 7s infinite}
    @keyframes nvflash{0%,90%,94%,100%{opacity:0}91%{opacity:.55}92.5%{opacity:.1}93%{opacity:.45}}
    .nvchips{position:absolute;right:10px;top:10px;display:flex;flex-direction:column;align-items:flex-end;gap:6px;pointer-events:none;font:13px/1.2 sans-serif}
    .nvchip{display:flex;align-items:center;gap:6px;padding:4px 10px 4px 4px;border-radius:999px;background:rgba(18,22,30,.78);color:#fff;box-shadow:0 1px 4px rgba(0,0,0,.35)}
    .nvchip.wx{padding:5px 12px;font-size:14px}
    .nvchip .av{width:22px;height:22px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;background-size:cover;background-position:center}
    .nvchip.away{opacity:.72}
    .nvchip .st{color:rgba(255,255,255,.7)}
    .nvsky{position:absolute;inset:0;overflow:hidden;pointer-events:none;background:linear-gradient(180deg,#78c3ec 0%,#acdcf3 50%,#dcf1f0 100%)}
    .nvsky.grey{background:linear-gradient(180deg,#8f9eab 0%,#b8c2ca 55%,#d6dcdf 100%)}
    .nvsky.golden{background:linear-gradient(180deg,#e9876a 0%,#f6b77e 40%,#fbe0b0 75%,#cfe0ea 100%)}
    .nv-golden{background:linear-gradient(200deg,rgba(255,150,70,.42),rgba(255,190,120,.22) 55%,rgba(170,110,190,.22));mix-blend-mode:multiply}
    .nvsky.night{background:linear-gradient(180deg,#050c20 0%,#0c1a3b 55%,#17284d 100%)}
    .nvsky .cl{position:absolute;top:0;bottom:0;left:-100%;width:300%;animation:nvdrift 160s linear infinite;background-image:${CLOUDS}}
    .nvsky .cl.b{animation-duration:90s;opacity:.55;transform:scale(1.3);top:10%}
    .nvsky.grey .cl{opacity:.6}
    .nvsky.night .cl{opacity:.06}
    .nvsky .st{position:absolute;inset:0;display:none;background-image:radial-gradient(circle,#fff 0 1px,transparent 1.5px),radial-gradient(circle,rgba(255,255,255,.7) 0 .8px,transparent 1.3px),radial-gradient(circle,rgba(200,220,255,.8) 0 1.2px,transparent 1.8px);
      background-size:137px 129px,83px 97px,211px 173px;background-position:0 0,40px 61px,90px 20px;animation:nvtwinkle 5s ease-in-out infinite alternate}
    .nvsky.night .st{display:block}
    @keyframes nvdrift{from{transform:translateX(0)}to{transform:translateX(33.3%)}}
    @keyframes nvtwinkle{from{opacity:.55}to{opacity:1}}
    .nvvig{position:absolute;inset:0;pointer-events:none;background:radial-gradient(ellipse 75% 70% at 50% 48%,transparent 60%,rgba(8,16,36,.26) 100%)}
    .nvcredit{position:absolute;left:10px;bottom:6px;font:11px/1.2 sans-serif;color:rgba(20,40,60,.6);pointer-events:none}
    .nvcredit.dark{color:rgba(255,255,255,.55)}
    .nvsway{transform-box:fill-box;transform-origin:50% 100%;animation:nvsway 2.6s ease-in-out infinite alternate}
    @keyframes nvsway{from{transform:rotate(-3deg)}to{transform:rotate(3deg)}}
    @media (prefers-reduced-motion: reduce){.nvfx,.nvfx *,.nvsky .cl,.nvsky .st,.nvsway{animation:none!important}}`;

  function overlays(live) {
    const w = (live && live.weather) || null, st = w && w.state;
    let fx = '';
    const cloud = (light) => `<div class="nvfx"><div class="nv-cloud${light ? ' light' : ''}"></div></div>`;
    if (['rainy', 'pouring', 'lightning-rainy', 'snowy-rainy', 'hail'].includes(st)) {
      const heavy = st === 'pouring' || st === 'lightning-rainy';
      fx += `<div class="nvfx nv-grey"></div>${cloud()}<div class="nvfx"><div class="nv-tilt"><div class="nv-fall rf"></div><div class="nv-fall rn"></div>${heavy ? '<div class="nv-fall rh"></div>' : ''}</div></div>`;
    }
    if (['snowy', 'snowy-rainy'].includes(st)) fx += '<div class="nvfx"><div class="nv-tilt" style="transform:rotate(4deg)"><div class="nv-sway"><div class="nv-fall sf"></div><div class="nv-fall sn"></div></div></div></div>';
    if (st === 'fog') fx += '<div class="nvfx nv-fog"></div>';
    if (st === 'cloudy') fx += '<div class="nvfx nv-grey"></div>' + cloud();
    if (st === 'partlycloudy') fx += cloud(true);
    if (st === 'sunny' && !(live && live.night)) fx += '<div class="nvfx nv-sun"></div>';
    if (['lightning', 'lightning-rainy'].includes(st)) fx += '<div class="nvfx nv-flash"></div>';
    let chips = '';
    if (w && st && st !== 'unavailable' && st !== 'unknown') {
      const [icon, text] = WEATHER[st] || ['', st];
      const t = w.temperature != null && w.temperature !== '' ? ` ${Math.round(Number(w.temperature))}${esc(w.unit || '°C')}` : '';
      chips += `<div class="nvchip wx" title="${esc(text)}">${icon} ${esc(text)}${t}</div>`;
    }
    for (const p of (live && live.people) || []) {
      const col = personColour(p.entity_id || p.name);
      const where = p.home ? 'Home' : !p.state || p.state === 'not_home' ? 'Away' : p.state === 'unknown' || p.state === 'unavailable' ? '—' : p.state;
      chips += `<div class="nvchip${p.home ? '' : ' away'}"><span class="av" style="background-color:${col}${p.picture ? `;background-image:url('${esc(p.picture)}')` : ''}">${p.picture ? '' : esc(p.initials || '?')}</span>${esc(p.name)} <span class="st">${esc(where)}</span></div>`;
    }
    return `<style>${FX_CSS}</style>${fx}${chips ? `<div class="nvchips">${chips}</div>` : ''}`;
  }

  function render(el, scene, opts) {
    // (OpenStreetMap's credit, as its licence asks: in a corner of the box, whatever the zoom)
    const d = draw(scene, opts);
    // (behind it: the sky, by day or night, greyer when it's wet; over it: a soft vignette)
    const live = (opts || {}).live || {}, st = (live.weather || {}).state || '';
    const grey = /rain|pour|cloudy$|fog|snow|hail|lightning/.test(st) && st !== 'partlycloudy';
    // (near sunrise and sunset, by the real sun: a golden light)
    const golden = !live.night && live.sun && live.sun.el != null && live.sun.el < 10 && live.sun.el > -4 && !grey;
    const sky = live.night ? 'night' : grey ? 'grey' : golden ? 'golden' : '';
    const glow = golden ? `<div class="nvfx nv-golden" style="opacity:${Math.max(0.25, Math.min(1, 1 - live.sun.el / 10)).toFixed(2)}"></div>` : '';
    el.innerHTML = `<div class="nvsky ${sky}"><div class="st"></div><div class="cl b"></div><div class="cl"></div></div>` + d.svg + glow + '<div class="nvvig"></div>' + overlays(live)
      + `<div class="nvcredit${live.night ? ' dark' : ''}">\u00a9 OpenStreetMap contributors</div>`;
    if (getComputedStyle(el).position === 'static') el.style.position = 'relative';
    fit(el);
    el._nvPick = !!(opts && opts.pick);
    if (!el._nvClick) {
      // tap another place's map to zoom round it; tap yours to come back
      el._nvClick = (e) => {
        const g = e.target.closest && e.target.closest('.nvisl');
        if (!g || (el._nvPick && e.target.closest('.bld'))) return;
        el._nvFocus = g.dataset.k || null;
        fit(el);
      };
      el.addEventListener('click', el._nvClick);
    }
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

  /* What's happening now, from Home Assistant's states (the card; the add-on's page gets the same
   * from the add-on, src/live.py): ents = {weather, people: [...], sun}. */
  function liveFrom(states, ents) {
    if (!ents) return null;
    const sun = states[ents.sun || 'sun.sun'];
    const out = {night: sun ? sun.state === 'below_horizon' : null, weather: null, people: []};
    if (ents.weather) {
      const st = states[ents.weather] || {}, a = st.attributes || {};
      out.weather = {entity: ents.weather, state: st.state, temperature: a.temperature, unit: a.temperature_unit || '°C'};
    }
    for (const e of ents.people || []) {
      const st = states[e] || {}, a = st.attributes || {};
      const name = a.friendly_name || e.split('.').pop().replace(/_/g, ' ');
      const initials = (name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('') || '?').toUpperCase();
      out.people.push({entity_id: e, name, initials, picture: a.entity_picture || null, state: st.state, home: st.state === 'home',
        lat: a.latitude ?? null, lon: a.longitude ?? null});
    }
    // the sun's place (rounded, so the map's only drawn again every few minutes), and your house's energy
    const sa = (sun && sun.attributes) || {};
    out.sun = sa.azimuth != null && sa.elevation != null ? {az: Math.round(Number(sa.azimuth) / 5) * 5, el: Math.round(Number(sa.elevation))} : null;
    const en = ents.energy || {};
    out.energy = {solar: en.solar ? active(states[en.solar]) : null, car: !!en.car, charging: en.car ? active(states[en.car]) : false,
      heat: en.heat ? active(states[en.heat]) : null};
    return out;
  }

  // Whether an energy entity says it's going (the same as src/live.py active())
  const ON_WORDS = ['on', 'charging', 'heating', 'heat', 'cooling', 'cool', 'running', 'true', 'active', 'producing', 'heat_pump', 'eco', 'performance'];
  function active(st) {
    if (!st) return false;
    const a = st.attributes || {};
    if (a.hvac_action != null) return ['heating', 'cooling', 'defrosting', 'preheating'].includes(String(a.hvac_action).toLowerCase());
    const s = String(st.state || '').toLowerCase();
    if (ON_WORDS.includes(s)) return true;
    const v = Number(s);
    if (s === '' || Number.isNaN(v)) return false;
    return v > (['kw', 'kwh'].includes(String(a.unit_of_measurement || '').toLowerCase()) ? 0.02 : 20);
  }

  window.NeighbourhoodView = {draw, render, fit, zoom: zoomStep, liveFrom, version: VERSION};

  // ---------- the dashboard card ----------
  if (!window.customElements || customElements.get('neighbourhood-view-card')) return;

  const ROT_KEY = 'neighbourhood-view-rot';
  const getRot = () => { try { return Number(localStorage.getItem(ROT_KEY)) || 0; } catch (e) { return 0; } };
  const setRot = (r) => { try { localStorage.setItem(ROT_KEY, String(r)); } catch (e) { /* (not kept) */ } };

  /* The map as a screensaver (the add-on's Settings › Screensaver, for every screen): tapping it
   * goes to another dashboard, and any screen left alone on another dashboard comes back to it.
   * This file's loaded on every dashboard (it's one of your dashboards' resources), so the watcher
   * below runs wherever the screen is. The settings are on the add-on's status sensor
   * (screensaver: {tap, idle, map}). Anything done on the screen (a touch, a tap, a scroll, a key,
   * the mouse) starts the wait again; a dialog left open goes too, after the wait. */
  const STATUS = 'sensor.neighbourhood_view_status';
  function haNow() { const ha = document.querySelector('home-assistant'); return ha && ha.hass; }
  function saverOf(hass) {
    const st = hass && hass.states && hass.states[STATUS];
    return (st && st.attributes && st.attributes.screensaver) || null;
  }
  function navigate(path) {
    history.pushState(null, '', path);
    window.dispatchEvent(new CustomEvent('location-changed', {detail: {replace: false}}));
  }
  if (!window.__neighbourhoodViewIdle) {
    window.__neighbourhoodViewIdle = true;
    let last = Date.now();
    const poke = () => { last = Date.now(); };
    for (const ev of ['pointerdown', 'pointermove', 'keydown', 'wheel', 'touchstart', 'scroll']) window.addEventListener(ev, poke, {capture: true, passive: true});
    setInterval(() => {
      const s = saverOf(haNow());
      if (!s || !s.idle || !s.map) { last = Date.now(); return; }
      const here = location.pathname.replace(/\/$/, ''), map = String(s.map).replace(/\/$/, '');
      // (not on the map itself, editing a dashboard, Home Assistant's settings, or an add-on's page)
      if (here === map || /[?&]edit=1/.test(location.search)
        || /^\/(config|developer-tools|hassio|profile|history|logbook|media-browser|api)(\/|$)/.test(here) || /_neighbourhood_view$|ingress/.test(here)) { last = Date.now(); return; }
      if (Date.now() - last > s.idle * 1000) { last = Date.now(); navigate(s.map); }
    }, 5000);
  }

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
      // (drawn again when the weather, someone's home/away or day/night changes)
      if (this._scene && this._ents) {
        const live = liveFrom(hass.states || {}, this._ents), key = JSON.stringify(live);
        if (key !== this._liveKey) { this._liveKey = key; this._draw(); }
      }
      if (this._root) this._root.querySelector('.map').classList.toggle('tap', !!this._tap());
      // (the add-on's map file renamed or first written: read it again)
      if (this._started && this._mapUrl() !== this._fileUrl) this._load();
      if (!this._started && hass) {
        this._started = true;
        this._load();
        this._timer = setInterval(() => this._load(), 2 * 60000);  // (a new map, places or settings)
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
        .tools { position: absolute; right: 10px; bottom: 10px; display: flex; gap: 2px; padding: 3px; border-radius: 999px;
          background: rgba(18,22,30,.82); box-shadow: 0 2px 8px rgba(0,0,0,.4); border: 1px solid rgba(255,255,255,.18); }
        .tools button { width: 34px; height: 34px; border-radius: 50%; border: none; cursor: pointer; font-size: 17px; line-height: 1;
          background: transparent; color: #fff; }
        .tools button:hover { background: rgba(255,255,255,.16); }
        .map.tap { cursor: pointer; }
      </style><ha-card><div class="map"></div><div class="msg">Reading the map…</div>
        <div class="tools"><button data-z="-1" title="Zoom out" aria-label="Zoom out">−</button><button data-z="1" title="Zoom in" aria-label="Zoom in">+</button><button data-r="-1" title="Turn left" aria-label="Turn left">⟲</button><button data-r="1" title="Turn right" aria-label="Turn right">⟳</button></div></ha-card>`;
      this._root.querySelector('.tools').addEventListener('click', (e) => {
        const btn = e.target && e.target.closest ? e.target.closest('button') : null;
        const d = (btn && btn.dataset) || {}, r = Number(d.r), z = Number(d.z);
        if (r) setRot((getRot() + r + 4) % 4);
        else if (z) zoomStep(z);
        else return;
        this._draw();
      });
      // tapping the map goes to the dashboard set (Settings › Screensaver, or the card's tap_navigate)
      this._root.querySelector('.map').addEventListener('click', (e) => {
        const to = this._tap();
        if (!to) return;
        e.stopPropagation();
        navigate(to);
      }, true);
      this._size();
    }

    // Where tapping the map goes: the card's own tap_navigate, else the add-on's screensaver
    _tap() {
      if (this._config.tap_navigate !== undefined) return this._config.tap_navigate || '';
      const s = saverOf(this._hass) || this._screen || {};
      return s.tap || '';
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

    // Where the add-on keeps the map for the card: a private file any signed-in user can read
    // (its name's on the add-on's status sensor), so kiosk and other non-admin users see it too
    _mapUrl() {
      if (this._config.url) return null;  // (the add-on's own address, given: read from it)
      const st = this._hass && this._hass.states && this._hass.states[this._config.status_entity || 'sensor.neighbourhood_view_status'];
      return (st && st.attributes && st.attributes.map_url) || null;
    }

    async _fetchData() {
      const file = this._mapUrl();
      if (file) {
        // (checked with the server each time, so it's only downloaded again when it's changed)
        const r = await fetch(file, {credentials: 'same-origin', cache: 'no-cache'});
        if (r.ok) {
          const text = await r.text();
          if (text === this._lastText && this._scene) return null;  // (the same: nothing to draw again)
          this._lastText = text;
          return JSON.parse(text);
        }
        // (not there yet, e.g. just renamed: through the add-on, for administrators)
        if (!(this._hass.user && this._hass.user.is_admin)) throw new Error(`The map couldn't be read (${r.status}): is the Neighbourhood View add-on running?`);
      } else if (this._hass.user && this._hass.user.is_admin === false) {
        throw new Error('Waiting for the Neighbourhood View add-on (update and start it).');
      }
      const base = await this._base();
      const r = await fetch(base + 'api/scene', {credentials: 'same-origin', cache: 'no-store'});
      if (!r.ok) throw new Error(`The add-on answered ${r.status}`);
      return r.json();
    }

    async _load() {
      try {
        this._fileUrl = this._mapUrl();
        const d = await this._fetchData();
        if (!d) return;
        if (!d.scene) { this._scene = null; this._msg(d.message || 'Set your postcode and house number in the Neighbourhood View add-on.'); return; }
        this._scene = d.scene;
        this._places = d.places || [];
        this._screen = d.screen || null;  // (the screensaver, if the status sensor's not there)
        this._root.querySelector('.map').classList.toggle('tap', !!this._tap());
        // (the entities to follow: the card's own weather / people, else the add-on's Settings)
        const c = this._config;
        this._ents = {...(d.entities || {}), ...(c.weather ? {weather: c.weather} : {}), ...(c.people ? {people: [].concat(c.people)} : {})};
        this._liveKey = null;
        this._draw();
      } catch (e) {
        this._msg(e && e.message ? e.message : String(e));
      }
    }

    _draw() {
      if (!this._scene) return;
      const s = this._scene, label = this._config.label || (s.number ? `NO. ${s.number}` : 'HOME');
      const live = this._ents && this._hass ? liveFrom(this._hass.states || {}, this._ents) : null;
      this._liveKey = JSON.stringify(live);
      render(this._root.querySelector('.map'), s, {rot: getRot(), zoom: zoomStep(0), label: String(label).toUpperCase(), live, places: this._places,
        motion: this._config.motion !== false, date: this._config.date || undefined});
      this._msg('');
    }
  }

  customElements.define('neighbourhood-view-card', NeighbourhoodViewCard);
  window.customCards = window.customCards || [];
  window.customCards.push({type: 'neighbourhood-view-card', name: 'Neighbourhood View',
    description: 'An isometric drawing of the streets around your home (from the Neighbourhood View add-on)', preview: false});
  console.info(`%c NEIGHBOURHOOD-VIEW-CARD %c ${VERSION} `, 'background:#2196f3;color:#fff', 'background:#eee;color:#333');
})();
