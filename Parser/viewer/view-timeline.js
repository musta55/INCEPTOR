/* Bug page > Fingerprint tab (view id 'timeline'): the selected trajectory as one strip per
 * action category (position = category, a dot per action, colour = the agent's self-check:
 * passed, errored, executed), under a phase band and an outcome band: Validation shows its
 * self-validation (the legend chips use the same fills), Localization and Repair show their
 * files as marks (grey = looked at, never edited; a colour per localization -> repair
 * attempt = edited), Planning nothing. A dashed line at the first fix. Hover an action for
 * its files, hover the phase or outcome band for the
 * phase's files (the dots that did not fit show there); click to move the playhead there
 * (details panel); the playhead draws a cursor line and column. x = action index, or
 * wall-clock when the log has timestamps. A change of width redraws the chart only (relayout),
 * in the frame of the change, so nothing flickers. */
(function () {
  'use strict';
  var TV = window.TV, esc = TV.esc;
  var root = null, geo = null;
  var L = 140, R = 14;

  function layout(t, W) {
    var n = t.n, xs = [], ws = [];
    var plotW = Math.max(100, W - L - R);
    if (TV.state.timeMode && t.hasTs) {
      var gaps = [];
      for (var k = 1; k < n; k++) gaps.push(Math.max(0, t.actions[k].tms - t.actions[k - 1].tms));
      var lastGap = TV.median(gaps) || 1000;
      var span = Math.max(1, t.t1 - t.t0 + lastGap);
      t.actions.forEach(function (a, k) {
        xs.push(L + plotW * (a.tms - t.t0) / span);
        var nx = k + 1 < n ? t.actions[k + 1].tms : a.tms + lastGap;
        ws.push(Math.max(1.5, plotW * (nx - a.tms) / span));
      });
      return { xs: xs, ws: ws, plotW: plotW, time: true, span: span };
    }
    var bw = plotW / n;
    for (var i = 0; i < n; i++) { xs.push(L + i * bw); ws.push(bw); }
    return { xs: xs, ws: ws, plotW: plotW, time: false, bw: bw };
  }
  function x0(i) { return geo.xs[i - 1]; }
  function x1(i) { return geo.xs[i - 1] + geo.ws[i - 1]; }
  function nearest(x) {
    var xs = geo.xs, lo = 0, hi = xs.length - 1;
    if (!geo.time) return TV.clamp(Math.floor((x - L) / geo.bw) + 1, 1, xs.length);
    while (lo < hi) { var m = (lo + hi + 1) >> 1; if (xs[m] <= x) lo = m; else hi = m - 1; }
    return lo + 1;
  }
  function niceStep(raw) {
    var p = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1e-9))));
    var m = raw / p;
    return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p;
  }

  function legend(t) {
    var used = {};
    t.subs.forEach(function (s) { if (TV.hasVerdict(s.p.phase)) used[s.outcome] = 1; });
    return TV.legendCardHTML(TV.bandLegendRows(used, t.nCycles).concat([
      ['Action', 'a dot per action · self-check by the agent', TV.verdictLegend('mk')],
      ['Marker', '', t.anchor ? '<span class="lgm"><i class="anchormk"></i>first fix (first edit of a source file)</span>' : '']
    ]));
  }

  function render(el) {
    root = el;
    var t = TV.traj();
    if (!t.n) { el.innerHTML = '<p class="note">This trajectory has no tool calls.</p>'; geo = null; return; }
    el.innerHTML = legend(t) + '<div class="card tl-wrap"></div><p class="hint">Hover an action or a phase for its files · click for details.</p>';
    draw(el.querySelector('.tl-wrap'), t);
  }
  function chartWidth(wrap) { return Math.max(420, wrap.clientWidth - 14); }
  /* the width changed (panel opened or closed, window resized): redraw the chart in place,
   * keeping the legend, the scroll position and the cursor */
  function relayout() {
    if (!root || !geo) return;
    var wrap = root.querySelector('.tl-wrap'), t = TV.traj();
    if (!wrap || !t || !t.n || chartWidth(wrap) === geo.W) return;
    var left = wrap.scrollLeft;
    draw(wrap, t);
    wrap.scrollLeft = left;
    if (TV.state.i) onCursor(TV.state.i, { noscroll: true });
  }

  function draw(wrap, t) {
    var W = chartWidth(wrap);
    geo = layout(t, W);
    geo.W = W;
    var lanes = TV.lanes([t]), laneY = {};
    var y = t.anchor ? 18 : 8, Y = {};
    Y.pur = y; y += 26;
    Y.seg = y; y += 26;
    var laneH = 18;
    Y.cap = y + 8; y += 8 + 12;
    Y.lanes = y;
    lanes.forEach(function (c) { laneY[c] = y; y += laneH; });
    Y.axis = y + 6; y += 6 + 26;
    var H = y;
    geo.Y = Y;
    var s = '<svg class="tl" width="' + W + '" height="' + H + '" role="img" aria-label="Fingerprint of ' + esc(t.id) + '">';
    function rowLabel(yy, txt, cls) { return '<text class="rl ' + (cls || '') + '" x="' + (L - 8) + '" y="' + yy + '" text-anchor="end" dominant-baseline="middle">' + esc(txt) + '</text>'; }
    s += rowLabel(Y.pur + 10, 'phase') + rowLabel(Y.seg + 10, 'outcome');
    t.phases.forEach(function (p) {
      var a = x0(p.start), b = x1(p.end);
      s += '<rect x="' + (a + 0.5) + '" y="' + Y.pur + '" width="' + Math.max(1, b - a - 1) + '" height="20" rx="3" fill="' + TV.phaseVar(p.phase) + '"/>';
      if (b - a > p.phase.length * 6.4 + 8) s += '<text class="bandlbl" style="fill:' + TV.phaseTextVar(p.phase) + '" x="' + ((a + b) / 2) + '" y="' + (Y.pur + 10.5) + '" text-anchor="middle" dominant-baseline="middle">' + esc(p.phase) + '</text>';
    });
    /* the outcome band, one rectangle per phase: Validation filled with its outcome (glyph and
     * label), Localization and Repair outlined with their file marks inside, Planning empty */
    t.phases.forEach(function (p) {
      var a = x0(p.start), b = x1(p.end), w = Math.max(1, b - a - 1);
      if (TV.hasFiles(p.phase)) {                   // the files as dots, when they all fit
        var rows = TV.spanFiles(t, p);
        s += '<rect class="segr fz" x="' + (a + 0.5) + '" y="' + Y.seg + '" width="' + w + '" height="20" rx="3"/>';
        s += TV.marksSVG(rows, a, b, Y.seg + 10, 7, 11, 3, 10.5);   // as many as fit, then "+n"
        return;
      }
      if (!TV.hasVerdict(p.phase)) return;          // Planning: no outcome
      p.subphases.forEach(function (sg) {
        var a = x0(sg.start), b = x1(sg.end), ev = TV.EVIDENCE_SHORT[sg.evidence];
        s += '<rect class="segr o-' + sg.outcome + '" x="' + (a + 0.5) + '" y="' + Y.seg + '" width="' + Math.max(1, b - a - 1) + '" height="20" rx="3"/>';
        if (b - a >= 13) {
          var full = sg.outcome + (ev ? ' · ' + ev : '');
          var txt = b - a > full.length * 6.5 + 12 ? full : b - a > sg.outcome.length * 6.5 + 12 ? sg.outcome : '';
          s += '<text class="seglbl o-' + sg.outcome + '" x="' + ((a + b) / 2) + '" y="' + (Y.seg + 10.5) + '" text-anchor="middle" dominant-baseline="middle">' + esc(txt) + '</text>';
        }
      });
    });
    /* the category lanes, under a caption */
    s += '<text class="rl cap" x="4" y="' + (Y.cap + 5) + '" dominant-baseline="middle" data-tip="Each line is an action category (the action table of the Lookup tables page)">action category</text>' +
      '<line class="capline" x1="' + L + '" x2="' + (L + geo.plotW) + '" y1="' + (Y.cap + 5) + '" y2="' + (Y.cap + 5) + '"/>';
    lanes.forEach(function (c, k) {
      var yy = laneY[c];
      if (k % 2 === 0) s += '<rect class="lanebg" x="' + L + '" y="' + yy + '" width="' + geo.plotW + '" height="' + laneH + '"/>';
      s += '<text class="rl lane" x="' + (L - 8) + '" y="' + (yy + laneH / 2) + '" text-anchor="end" dominant-baseline="middle" data-tip="' + esc(TV.catDef(c)) + '">' + esc(c) + '</text>';
    });
    t.actions.forEach(function (a) {                // one dot per action
      var r = Math.max(1.8, Math.min(geo.ws[a.i - 1] / 2 - 0.4, 6));
      s += '<circle class="mk v-' + a.verdict + '" data-i="' + a.i + '" cx="' + (x0(a.i) + geo.ws[a.i - 1] / 2).toFixed(2) + '" cy="' + (laneY[a.category] + laneH / 2) + '" r="' + r.toFixed(2) + '"/>';
    });
    s += '<line class="axis" x1="' + L + '" x2="' + (L + geo.plotW) + '" y1="' + Y.axis + '" y2="' + Y.axis + '"/>';
    var ticks = [];
    if (geo.time) {
      var stepS = niceStep(geo.span / 1000 / 8);
      for (var ts = 0; ts * 1000 <= geo.span; ts += stepS) ticks.push({ x: L + geo.plotW * ts * 1000 / geo.span, l: TV.fmtDur(ts) });
    } else {
      var st = Math.max(1, niceStep(t.n / 10));
      ticks.push({ x: (x0(1) + x1(1)) / 2, l: '1' });
      for (var i = st; i <= t.n; i += st) ticks.push({ x: (x0(i) + x1(i)) / 2, l: String(i) });
    }
    ticks.forEach(function (tk) {
      s += '<line class="tick" x1="' + tk.x + '" x2="' + tk.x + '" y1="' + Y.axis + '" y2="' + (Y.axis + 4) + '"/>' +
        '<text class="ticklbl" x="' + tk.x + '" y="' + (Y.axis + 15) + '" text-anchor="middle">' + tk.l + '</text>';
    });
    s += '<text class="rl" x="' + (L - 8) + '" y="' + (Y.axis + 15) + '" text-anchor="end">' + (geo.time ? 'elapsed' : 'action #') + '</text>';
    if (t.anchor) {
      var ax = x0(t.anchor);
      s += '<line class="anchorline" x1="' + ax + '" x2="' + ax + '" y1="' + (Y.pur - 4) + '" y2="' + Y.axis + '"/>' +
        '<text class="anchorlbl" x="' + (ax + 4) + '" y="' + (Y.pur - 6) + '">first fix #' + t.anchor + '</text>';
    }
    s += '<rect class="curcol" x="0" y="' + Y.pur + '" width="0" height="' + (Y.axis - Y.pur) + '"/>';
    s += '<line class="playline" x1="0" x2="0" y1="' + (Y.pur - 3) + '" y2="' + (Y.axis + 3) + '" visibility="hidden"/>';
    s += '<rect class="overlay" x="' + L + '" y="' + Y.pur + '" width="' + geo.plotW + '" height="' + (Y.axis - Y.pur + 20) + '"/>';
    wrap.innerHTML = s + '</svg>';
    bind(wrap, t);
  }

  function bind(wrap, t) {
    var svg = wrap.querySelector('svg.tl'), ov = svg.querySelector('.overlay');
    function px(ev) { return TV.svgPoint(svg, ev).x; }
    function py(ev) { return TV.svgPoint(svg, ev).y; }
    ov.addEventListener('mousemove', function (ev) {
      var i = nearest(px(ev)), a = t.actions[i - 1];
      if (py(ev) < geo.Y.seg + 22 && a.span) { TV.tip.show(TV.phaseTip(t, a.span), ev); return; }   // the phase / outcome band
      TV.tip.show(TV.actionTip(t, a), ev);
    });
    ov.addEventListener('mouseleave', function () { TV.tip.hide(); });
    ov.addEventListener('click', function (ev) { TV.setCursor(nearest(px(ev)), { from: 'timeline' }); });
  }

  function onCursor(i) {
    if (!root || !geo) return;
    var svg = root.querySelector('svg.tl');
    if (!svg) return;
    var line = svg.querySelector('.playline'), col = svg.querySelector('.curcol');
    svg.querySelectorAll('.mk.cur').forEach(function (m) { m.classList.remove('cur'); });
    var t = TV.traj();
    if (!i || i > t.n) { line.setAttribute('visibility', 'hidden'); col.setAttribute('width', 0); return; }
    var a = x0(i), w = geo.ws[i - 1], cx = a + w / 2;
    line.setAttribute('x1', cx); line.setAttribute('x2', cx); line.setAttribute('visibility', 'visible');
    col.setAttribute('x', a); col.setAttribute('width', Math.max(2, w));
    var mk = svg.querySelector('.mk[data-i="' + i + '"]');
    if (mk) mk.classList.add('cur');
    var wrap = svg.parentNode;                       // keep the cursor in sight when the chart scrolls sideways
    if (wrap && wrap.scrollWidth > wrap.clientWidth + 2 && (cx < wrap.scrollLeft + L || cx > wrap.scrollLeft + wrap.clientWidth - 20)) {
      wrap.scrollLeft = Math.max(0, cx - wrap.clientWidth / 2);
    }
  }

  TV.views.timeline = { render: render, onCursor: onCursor, relayout: relayout };
})();
