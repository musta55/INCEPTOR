/* Bug page > Fingerprint: small multiples of the trajectories of this bug, one bubble grid
 * each. x = action index on a scale shared by all grids, y = action-category lanes (the union
 * over the grids); bubble colour = verdict (pass / fail / none); a dashed line at the first
 * fix; above each grid the phase strip and the subphase-outcome strip. Default: the 3 agents
 * of the selected run; toggle (S.fp = 'runs'): the selected agent across its runs. Click a
 * bubble (any point of its column) to select that trajectory and action; the playhead
 * highlights the current column of the selected one. */
(function () {
  'use strict';
  var TV = window.TV, esc = TV.esc;
  var root = null, grids = [];
  var ROWH = 13, PH = 8, SH = 8, Y0 = 23;     // lane height, phase / subphase strip heights, first lane

  function rows() {
    var B = TV.bugData, cur = TV.traj();
    if (TV.state.fp === 'runs') return B.runs.map(function (r) { return { key: cur.agent + '-r' + r, t: B.byKey[cur.agent + '-r' + r], label: 'run ' + r }; });
    return B.agents.map(function (a) { return { key: a + '-r' + cur.run, t: B.byKey[a + '-r' + cur.run], label: a }; });
  }

  function grid(t, lanes, cw, LW, narrow, maxN) {
    var yA = Y0 + lanes.length * ROWH, W = LW + maxN * cw + 6, H = yA + 18;
    var r = Math.max(1.4, Math.min(cw, ROWH) / 2 - 0.6);
    var s = '<svg class="fp" width="' + W.toFixed(1) + '" height="' + H + '" data-key="' + esc(t.key) + '" role="img" aria-label="' + esc('Fingerprint of ' + t.agent + ' run ' + t.run) + '">';
    function xa(i) { return LW + (i - 1) * cw; }
    s += '<text class="rl strip-l" x="' + (LW - 6) + '" y="' + (PH / 2) + '" text-anchor="end" dominant-baseline="middle">' + (narrow ? 'p' : 'phase') + '</text>';
    s += '<text class="rl strip-l" x="' + (LW - 6) + '" y="' + (PH + 2 + SH / 2) + '" text-anchor="end" dominant-baseline="middle">' + (narrow ? 's' : 'subphase') + '</text>';
    t.phases.forEach(function (p) {
      s += '<rect class="band" x="' + xa(p.start).toFixed(2) + '" y="0" width="' + Math.max(1, (p.end - p.start + 1) * cw - 1).toFixed(2) + '" height="' + PH + '" rx="1.5" fill="' + TV.phaseVar(p.phase) + '"/>';
    });
    t.subs.forEach(function (sg) {
      s += '<rect class="segr o-' + sg.outcome + '" x="' + xa(sg.start).toFixed(2) + '" y="' + (PH + 2) + '" width="' + Math.max(1, (sg.end - sg.start + 1) * cw - 1).toFixed(2) + '" height="' + SH + '" rx="1.5"/>';
    });
    lanes.forEach(function (m, k) {
      var yy = Y0 + k * ROWH;
      if (k % 2 === 0) s += '<rect class="lanebg" x="' + LW + '" y="' + yy + '" width="' + (maxN * cw).toFixed(1) + '" height="' + ROWH + '"/>';
      s += '<text class="rl lane" x="' + (LW - 6) + '" y="' + (yy + ROWH / 2) + '" text-anchor="end" dominant-baseline="middle">' + esc(narrow ? TV.catAbbr(m) : m) + '</text>';
    });
    if (t.anchor) s += '<line class="anchorline" x1="' + xa(t.anchor).toFixed(2) + '" x2="' + xa(t.anchor).toFixed(2) + '" y1="0" y2="' + (yA + 1) + '"/>';
    s += '<rect class="curcol" x="0" y="0" width="0" height="' + yA + '"/>';
    t.actions.forEach(function (a) {
      var k = lanes.indexOf(a.category);
      s += '<circle class="bub v-' + a.verdict + '" data-i="' + a.i + '" cx="' + (xa(a.i) + cw / 2).toFixed(2) + '" cy="' + (Y0 + k * ROWH + ROWH / 2) + '" r="' + r.toFixed(2) + '"/>';
    });
    s += '<line class="axis" x1="' + LW + '" x2="' + (LW + t.n * cw).toFixed(1) + '" y1="' + (yA + 1) + '" y2="' + (yA + 1) + '"/>';
    var st = maxN > 100 ? 25 : maxN > 40 ? 10 : 5;
    if (cw * st < 22) st *= 2;
    for (var i = st; i <= t.n; i += st) s += '<text class="ticklbl" x="' + (xa(i) + cw / 2).toFixed(1) + '" y="' + (yA + 13) + '" text-anchor="middle">' + i + '</text>';
    s += '<line class="playline" x1="0" x2="0" y1="0" y2="' + (yA + 2) + '" visibility="hidden"/>';
    s += '<rect class="overlay" x="' + LW + '" y="0" width="' + (t.n * cw).toFixed(1) + '" height="' + yA + '"/>';
    return s + '</svg>';
  }

  function render(el) {
    root = el;
    var cur = TV.traj(), byRuns = TV.state.fp === 'runs';
    var rs = rows(), trajs = rs.map(function (x) { return x.t; }).filter(Boolean);
    var subUsed = {}, anchors = false;
    trajs.forEach(function (t) {
      t.subs.forEach(function (s) { subUsed[s.outcome] = 1; });
      if (t.anchor) anchors = true;
    });
    var lanes = TV.lanes(trajs);
    var maxN = Math.max.apply(null, [1].concat(trajs.map(function (t) { return t.n; })));
    var W = Math.max(280, el.clientWidth - 26);
    var narrow = W < 560, LW = narrow ? 30 : 96;
    var cw = Math.min(14, (W - LW - 10) / maxN);
    var h = '<div class="legend fp-legend">' +
      '<span class="lg-t">Bubble</span><span class="lgm"><i class="bub v-pass"></i>pass</span><span class="lgm"><i class="bub v-fail"></i>fail</span>' +
      '<span class="lgm"><i class="bub v-none"></i>no verdict</span>' + (anchors ? '<span class="lgm"><i class="anchormk"></i>first fix</span>' : '') + '</div>' +
      '<div class="legend fp-legend"><span class="lg-t">Subphase outcome</span>' + TV.outcomeLegend(subUsed) + '</div>';
    h += '<p class="fp-sub muted small">' + (byRuns ? esc(cur.agent) + ' in each of its runs' : 'The ' + rs.length + ' agents in run ' + cur.run) +
      ' · x = action #, one scale for all (' + maxN + ' max) · rows = action category' +
      (narrow ? ' (' + lanes.map(function (m) { return TV.catAbbr(m) + ' ' + m; }).join(', ') + ')' : '') +
      ' · strips = phase, then subphase outcome</p>';
    grids = [];
    rs.forEach(function (x) {
      var t = x.t;
      if (!t) {
        h += '<div class="fpcard missing"><div class="fp-h">' + (byRuns ? '<b>' + esc(x.label) + '</b>' : TV.agentHTML(x.label)) + '<span class="muted small">not converted</span></div></div>';
        return;
      }
      var isCur = t.key === cur.key;
      h += '<div class="fpcard' + (isCur ? ' cur' : '') + '" data-key="' + esc(t.key) + '">' +
        '<div class="fp-h">' + (byRuns ? '<b class="fp-run">run ' + t.run + '</b>' : TV.agentHTML(t.agent)) + TV.passPill(t.outcome.pass) +
        '<span class="muted small">' + TV.plural(t.n, 'action') + ' · ' + TV.plural(t.subs.length, 'subphase') + ' · ' + TV.plural(t.attempts.length, 'attempt') +
        (t.stats.n_failed_actions != null ? ' · ' + t.stats.n_failed_actions + ' failed actions' : '') + '</span>' +
        (isCur ? '<span class="tag cur-tag">selected · playhead</span>' : '<button type="button" class="btn small" data-select="' + esc(t.key) + '" title="Make this the selected trajectory">select</button>') + '</div>' +
        '<div class="fp-wrap">' + grid(t, lanes, cw, LW, narrow, maxN) + '</div></div>';
      grids.push({ t: t, cw: cw, LW: LW });
    });
    h += '<p class="hint">Click a bubble (or anywhere in its column) to select that trajectory and action · space plays the selected one.</p>';
    el.innerHTML = h;
    el.querySelectorAll('[data-select]').forEach(function (b) { b.addEventListener('click', function () { TV.select(b.dataset.select); }); });
    grids.forEach(function (g) {
      var svg = el.querySelector('svg.fp[data-key="' + CSS.escape(g.t.key) + '"]'), ov = svg.querySelector('.overlay');
      function idx(ev) { var rc = svg.getBoundingClientRect(); return TV.clamp(Math.floor((ev.clientX - rc.left - g.LW) / g.cw) + 1, 1, g.t.n); }
      ov.addEventListener('mousemove', function (ev) {
        TV.tip.show('<div class="tt-m">' + esc(g.t.agent + ' · run ' + g.t.run) + '</div>' + TV.actionTip(g.t, g.t.actions[idx(ev) - 1]), ev);
      });
      ov.addEventListener('mouseleave', function () { TV.tip.hide(); });
      ov.addEventListener('click', function (ev) {
        var i = idx(ev);
        if (g.t.key !== TV.state.t) TV.select(g.t.key, { i: i }); else TV.setCursor(i, { from: 'fingerprint' });
      });
    });
  }

  function onCursor(i, opts) {
    if (!root) return;
    opts = opts || {};
    grids.forEach(function (g) {
      var svg = root.querySelector('svg.fp[data-key="' + CSS.escape(g.t.key) + '"]');
      if (!svg) return;
      var col = svg.querySelector('.curcol'), line = svg.querySelector('.playline');
      svg.querySelectorAll('.bub.cur').forEach(function (b) { b.classList.remove('cur'); });
      if (g.t.key === TV.state.t && i && i <= g.t.n) {
        var x = g.LW + (i - 1) * g.cw;
        col.setAttribute('x', x); col.setAttribute('width', Math.max(2, g.cw));
        line.setAttribute('x1', x + g.cw / 2); line.setAttribute('x2', x + g.cw / 2); line.setAttribute('visibility', 'visible');
        var b = svg.querySelector('.bub[data-i="' + i + '"]');
        if (b) b.classList.add('cur');
        if (!opts.initial && opts.from !== 'fingerprint' && root.getBoundingClientRect().top < window.innerHeight - 60) {   // bring the grid into sight
          var rc = svg.getBoundingClientRect();
          if (rc.bottom < 90 || rc.top > window.innerHeight - 40) svg.parentNode.parentNode.scrollIntoView({ block: 'nearest' });
        }
      } else {
        col.setAttribute('width', 0);
        line.setAttribute('visibility', 'hidden');
      }
    });
  }

  TV.views.fingerprint = { render: render, onCursor: onCursor };
})();
