/* Bug page > Timeline: the selected trajectory as one strip per action category
 * (position = category, colour = verdict), under a phase band, a subphase band coloured by
 * outcome (the legend chips use the same fills), and the repair attempts (first edit to
 * judging run, coloured by the attempt's outcome; ticks = edits, dot = judging run); failures
 * on a rail by kind (shape); a dashed line at the first fix. Hover for the action, click to
 * move the playhead there (details panel); the playhead draws a cursor line and column.
 * x = action index, or wall-clock when the log has timestamps. */
(function () {
  'use strict';
  var TV = window.TV, esc = TV.esc;
  var root = null, geo = null;
  var L = 112, R = 14;

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
    var kinds = {};
    t.actions.forEach(function (a) { if (a.verdict === 'fail') kinds[a.fail_kind || 'exit'] = 1; });
    var used = {};
    t.subs.forEach(function (s) { used[s.outcome] = 1; });
    return '<div class="legend" style="margin-bottom:10px">' +
      '<span class="lg-t">Subphase outcome</span>' + TV.outcomeLegend(used) +
      '<span class="lg-t">Action</span><span class="lgm"><i class="mk v-pass"></i>pass</span><span class="lgm"><i class="mk v-fail"></i>fail</span><span class="lgm"><i class="mk"></i>no verdict</span>' +
      (Object.keys(kinds).length ? '<span class="lg-t">Failure</span>' + TV.FAIL_KINDS.filter(function (k) { return kinds[k]; }).map(function (k) {
        return '<span class="lgm" data-tip="' + esc(TV.FAIL_KIND_LABEL[k]) + '"><svg width="12" height="12" aria-hidden="true">' + TV.failGlyphSVG(k, 6, 6, 5) + '</svg>' + esc(k) + '</span>';
      }).join('') : '') +
      (t.attempts.length ? '<span class="lg-t">Attempts</span><span class="lgm" data-tip="from the first edit of an attempt to the run that judges it; coloured by the attempt\'s outcome"><i class="attmk"></i>first edit → judging run</span>' : '') +
      (t.anchor ? '<span class="lgm"><i class="anchormk"></i>first fix</span>' : '') +
      '</div>';
  }

  function render(el) {
    root = el;
    var t = TV.traj();
    if (!t.n) { el.innerHTML = '<p class="note">This trajectory has no tool calls.</p>'; geo = null; return; }
    el.innerHTML = legend(t) + '<div class="card tl-wrap"></div><p class="hint">Hover for an action · click to move the playhead there · space plays, j / k step.' +
      (t.hasTs ? '' : ' This log has no per-step timestamps, so x is the action number.') + '</p>';
    var wrap = el.querySelector('.tl-wrap');
    var W = Math.max(420, wrap.clientWidth - 14);
    geo = layout(t, W);
    var lanes = TV.lanes([t]);
    var y = t.anchor ? 18 : 8, Y = {};
    Y.pur = y; y += 26;
    Y.seg = y; y += 26;
    if (t.attempts.length) { Y.att = y + 2; y += 4 + 16 + 4; }
    var laneH = 16;
    Y.lanes = y + 6; y += 6 + lanes.length * laneH;
    Y.rail = y + 6; y += 6 + 18;
    Y.axis = y + 2; y += 26;
    var H = y;
    geo.Y = Y;
    var s = '<svg class="tl" width="' + W + '" height="' + H + '" role="img" aria-label="Timeline of ' + esc(t.id) + '">';
    function rowLabel(yy, txt, cls) { return '<text class="rl ' + (cls || '') + '" x="' + (L - 8) + '" y="' + yy + '" text-anchor="end" dominant-baseline="middle">' + esc(txt) + '</text>'; }
    s += rowLabel(Y.pur + 10, 'phase') + rowLabel(Y.seg + 10, 'subphase');
    t.phases.forEach(function (p) {
      var a = x0(p.start), b = x1(p.end);
      s += '<rect x="' + (a + 0.5) + '" y="' + Y.pur + '" width="' + Math.max(1, b - a - 1) + '" height="20" rx="3" fill="' + TV.phaseVar(p.phase) + '"/>';
      if (b - a > p.phase.length * 6.4 + 8) s += '<text class="bandlbl" style="fill:' + TV.phaseTextVar(p.phase) + '" x="' + ((a + b) / 2) + '" y="' + (Y.pur + 10.5) + '" text-anchor="middle" dominant-baseline="middle">' + esc(p.phase) + '</text>';
    });
    t.subs.forEach(function (sg) {
      var a = x0(sg.start), b = x1(sg.end), ev = TV.EVIDENCE_SHORT[sg.evidence];
      s += '<rect class="segr o-' + sg.outcome + '" x="' + (a + 0.5) + '" y="' + Y.seg + '" width="' + Math.max(1, b - a - 1) + '" height="20" rx="3"/>';
      if (b - a >= 13) {
        var txt = TV.OUTCOME_GLYPH[sg.outcome], full = sg.outcome + (ev ? ' · ' + ev : '');
        if (b - a > full.length * 6.5 + 22) txt += ' ' + full; else if (b - a > sg.outcome.length * 6.5 + 22) txt += ' ' + sg.outcome;
        s += '<text class="seglbl o-' + sg.outcome + '" x="' + ((a + b) / 2) + '" y="' + (Y.seg + 10.5) + '" text-anchor="middle" dominant-baseline="middle">' + esc(txt) + '</text>';
      }
    });
    if (t.attempts.length) {
      s += rowLabel(Y.att + 7, 'attempts');
      t.attempts.forEach(function (at) {
        var a = x0(at.start), b = x1(at.end), yy = Y.att;
        s += '<rect class="attspan o-' + at.outcome + '" x="' + (a + 0.5) + '" y="' + yy + '" width="' + Math.max(2, b - a - 1) + '" height="13" rx="6.5"/>';
        at.edits.forEach(function (i) { var cx = (x0(i) + x1(i)) / 2; s += '<rect class="attmark o-' + at.outcome + '" x="' + (cx - 1) + '" y="' + (yy + 2) + '" width="2" height="9"/>'; });
        if (at.judge) { var jx = (x0(at.judge) + x1(at.judge)) / 2; s += '<circle class="attmark o-' + at.outcome + '" cx="' + jx + '" cy="' + (yy + 6.5) + '" r="4"/>'; }
        var ev = TV.EVIDENCE_SHORT[at.evidence];
        var cands = ['⟲ ' + at.id + ' ' + TV.OUTCOME_GLYPH[at.outcome] + ' ' + at.outcome + (ev ? ' (' + ev + ')' : ''), '⟲ ' + at.id + ' ' + TV.OUTCOME_GLYPH[at.outcome], '⟲' + at.id];
        var room = Math.floor((b - a - 8) / 5.6), lbl = cands.filter(function (c) { return c.length <= room; })[0];
        if (lbl) s += '<text class="attlbl o-' + at.outcome + '" x="' + (a + 6) + '" y="' + (yy - 1) + '">' + esc(lbl) + '</text>';
      });
    }
    lanes.forEach(function (m, k) {
      var yy = Y.lanes + k * laneH;
      if (k % 2 === 0) s += '<rect class="lanebg" x="' + L + '" y="' + yy + '" width="' + geo.plotW + '" height="' + laneH + '"/>';
      s += rowLabel(yy + laneH / 2, m, 'lane');
    });
    var mh = 10;
    t.actions.forEach(function (a) {
      var k = lanes.indexOf(a.category);
      var w = Math.max(1.5, Math.min(geo.ws[a.i - 1] - (geo.ws[a.i - 1] > 4 ? 1 : 0), 14));
      var cx = x0(a.i) + geo.ws[a.i - 1] / 2;
      s += '<rect class="mk v-' + a.verdict + '" data-i="' + a.i + '" x="' + (cx - w / 2) + '" y="' + (Y.lanes + k * laneH + (laneH - mh) / 2) + '" width="' + w + '" height="' + mh + '" rx="1.5"/>';
    });
    s += rowLabel(Y.rail + 9, 'failures');
    s += '<line class="railline" x1="' + L + '" x2="' + (L + geo.plotW) + '" y1="' + (Y.rail + 9) + '" y2="' + (Y.rail + 9) + '"/>';
    t.actions.forEach(function (a) {
      if (a.verdict !== 'fail') return;
      s += TV.failGlyphSVG(a.fail_kind, x0(a.i) + geo.ws[a.i - 1] / 2, Y.rail + 9, 5.5);
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
    function px(ev) { var r = svg.getBoundingClientRect(); return ev.clientX - r.left; }
    ov.addEventListener('mousemove', function (ev) {
      var i = nearest(px(ev)), a = t.actions[i - 1], at = a.attempt;
      TV.tip.show(TV.actionTip(t, a) + (at ? '<div class="tt-m">⟲ attempt ' + at.id + ' #' + at.start + '–#' + at.end + ': ' + TV.OUTCOME_GLYPH[at.outcome] + ' ' + at.outcome +
        (TV.EVIDENCE_SHORT[at.evidence] ? ' (' + TV.EVIDENCE_SHORT[at.evidence] + ')' : '') + '</div>' : ''), ev);
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

  TV.views.timeline = { render: render, onCursor: onCursor };
})();
