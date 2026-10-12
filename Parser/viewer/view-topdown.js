/* Bug page > Trajectory: the top-down hierarchy of the selected trajectory.
 * Phase blocks -> subphase blocks -> step rows (collapsible; steps rendered only when open).
 * Above them, the phase strip and the subphase-outcome strip of the whole run, with the first
 * fix (the anchor: first edit of app source) marked. Subphases are colour-coded by outcome
 * (left edge, tint, solid outcome chip) and say, in the codebook's words, what their check
 * was and what it showed. A step row selects its action (details panel); the level control
 * sets what is open. The playhead (onCursor) highlights the current step / subphase / phase,
 * opens the phase that holds it (and, at the Steps level, the subphase), and scrolls it into
 * view. */
(function () {
  'use strict';
  var TV = window.TV, esc = TV.esc;
  var root = null;

  function outcomeSummary(p) {
    var c = {};
    p.subphases.forEach(function (s) { c[s.outcome] = (c[s.outcome] || 0) + 1; });
    return ['failed', 'blocked', 'succeeded', 'unchecked'].filter(function (o) { return c[o]; }).map(function (o) {
      return '<span class="ocount o-' + o + '" data-tip="' + esc(TV.plural(c[o], 'subphase') + ' · ' + TV.outcomeDef(p.phase, o)) + '"><b aria-hidden="true">' +
        TV.OUTCOME_GLYPH[o] + '</b>' + c[o] + '</span>';
    }).join('');
  }
  function catStrip(t, s) {
    var h = '<span class="midstrip" aria-hidden="true">';
    for (var i = s.start; i <= s.end && i - s.start < 32; i++) {
      var a = t.actions[i - 1];
      h += '<i class="ms v-' + a.verdict + '" data-i="' + a.i + '">' + esc(TV.catAbbr(a.category)) + '</i>';
    }
    if (s.end - s.start >= 32) h += '<i class="ms more">+' + (s.end - s.start - 31) + '</i>';
    return h + '</span>';
  }
  /* "2 attempts · the run that judges an attempt: it passes, or the code compiles" */
  function subLabel(s) {
    var row = ((TV.vocab.text || {}).outcomes || {})[s.p.phase] || {};
    var what = row[s.outcome] && row[s.outcome] !== '–' ? row.check + ': ' + row[s.outcome] : TV.OUTCOME_LABEL[s.outcome];
    var count = s.n_attempts ? TV.plural(s.n_attempts, 'attempt') : s.n_events > 1 ? s.n_events + ' checks' : '';
    return (count ? count + ' · ' : '') + what;
  }
  function attemptsIn(t, lo, hi) {
    return t.attempts.filter(function (at) { return at.start <= hi && at.end >= lo; });
  }
  function attemptBadge(list, tipPrefix) {
    if (!list.length) return '';
    var bad = list.filter(function (at) { return at.outcome === 'failed'; }).length;
    var tip = (tipPrefix || '') + list.map(function (at) {
      return 'attempt ' + at.id + ' #' + at.start + '–#' + at.end + ': ' + TV.plural(at.edits.length, 'edit') + ', ' +
        (at.judge ? 'judged by #' + at.judge + ' → ' + at.outcome + ' (' + at.evidence + ')' : 'never run');
    }).join(' · ');
    return '<span class="attbadge' + (bad ? ' bad' : '') + '" data-tip="' + esc(tip) + '">⟲ ' + TV.plural(list.length, 'attempt') + (bad ? ', ' + bad + ' failed' : '') + '</span>';
  }

  function stepHTML(t, a) {
    var role = TV.attemptRole(a);
    return '<div class="step' + (a.i === TV.state.i ? ' cur' : '') + '" data-i="' + a.i + '">' +
      '<button type="button" class="st-h">' +
      '<span class="st-i">#' + a.i + '</span>' +
      '<span class="midchip" data-tip="' + esc(TV.catDef(a.category)) + '">' + esc(a.category) + '</span>' +
      (a.scope && a.scope !== 'main' ? '<span class="tag" data-tip="' + esc(a.scope) + '">sub</span>' : '') +
      (t.anchor === a.i ? '<span class="tag" data-tip="the first edit of app source: the anchor of the phases">first fix</span>' : '') +
      (role === 'edit' || role === 'judging run' ? '<span class="tag" data-tip="' + esc('attempt ' + a.attempt.id + ' (' + a.attempt.outcome + ')') + '">' + (role === 'edit' ? 'edit' : 'judge') + ' ' + a.attempt.id + '</span>' : '') +
      (a.own_phase ? '<span class="tag" data-tip="' + esc('its own phase is ' + a.own_phase + '; a single row between two stretches of one phase joins them (G7)') + '">' +
        '<i class="sw" style="background:' + TV.phaseVar(a.own_phase) + '"></i>' + esc(a.own_phase) + '</span>' : '') +
      '<span class="st-t">' + esc(a.target || a.tool) + '</span>' +
      (a.verdict !== 'none' ? '<span class="vg v-' + a.verdict + '">' + TV.VERDICT_GLYPH[a.verdict] + (a.fail_kind ? ' ' + esc(a.fail_kind) : '') + '</span>' : '<span class="vg none"></span>') +
      '</button></div>';
  }

  function subHTML(t, s, e) {
    var open = !!e.s[s.id], n = s.end - s.start + 1;
    var absorbed = s.absorbed.map(function (k) {
      return '<span class="tag" data-tip="' + esc(s.own_phases[k] + ' action(s) whose own phase is ' + k + ' joined this ' + s.p.phase + ' stretch: a single row between rows of one phase joins them (G7)') + '">' +
        '<i class="sw" style="background:' + TV.phaseVar(k) + '"></i>' + s.own_phases[k] + ' ' + esc(k) + '</span>';
    }).join('');
    var extras = absorbed + (s.n_attempts ? attemptBadge(attemptsIn(t, s.start, s.end)) : '') + s.flags.map(TV.flagHTML).join('');
    var h = '<div class="sblk o-' + s.outcome + (TV.isProblemSub(s) ? ' problem' : '') + '" data-sid="' + esc(s.id) + '">' +
      '<button type="button" class="sb-h" aria-expanded="' + open + '">' +
      '<span class="caret" aria-hidden="true">' + (open ? '▾' : '▸') + '</span>' +
      '<span class="sb-t">' + TV.outcomePill(s.outcome, null, s.p.phase, s.evidence) + '</span>' +
      '<span class="slabel">' + esc(subLabel(s)) + '</span>' +
      '<span class="srange">#' + s.start + (n > 1 ? '–#' + s.end : '') + ' <span class="muted">(' + n + ')</span></span>' +
      '<span class="sb-2">' + (extras ? '<span class="badges">' + extras + '</span>' : '<span></span>') + catStrip(t, s) + '</span>' +
      '</button>';
    if (open) {
      h += '<div class="sb-body">';
      for (var i = s.start; i <= s.end; i++) h += stepHTML(t, t.actions[i - 1]);
      h += '</div>';
    }
    return h + '</div>';
  }

  function phaseHTML(t, p, e) {
    var open = !!e.p[p.id], n = p.end - p.start + 1;
    var h = '<div class="pblk" data-pid="' + esc(p.id) + '" style="--pc:' + TV.phaseVar(p.phase) + '">' +
      '<button type="button" class="pb-h" aria-expanded="' + open + '">' +
      '<span class="caret" aria-hidden="true">' + (open ? '▾' : '▸') + '</span>' +
      '<span class="plabel" data-tip="' + esc(TV.phaseDef(p.phase)) + '">' + esc(p.phase) + '</span>' +
      '<span class="prange">#' + p.start + (n > 1 ? '–#' + p.end : '') + '</span>' +
      '<span class="psize" data-tip="' + esc(n + ' of ' + t.n + ' actions') + '"><i style="width:' + Math.max(2, 100 * n / t.n) + '%"></i></span>' +
      '<span class="pn">' + TV.plural(n, 'action') + ' · ' + TV.plural(p.subphases.length, 'subphase') + '</span>' +
      '<span class="psum">' + outcomeSummary(p) + '</span>' +
      (p.phase === 'repair' ? attemptBadge(attemptsIn(t, p.start, p.end), 'repair attempts: ') : '') +
      '</button>';
    if (open) {
      h += '<div class="pb-body">';
      p.subphases.forEach(function (s) { h += subHTML(t, s, e); });
      h += '</div>';
    }
    return h + '</div>';
  }

  /* phase strip + subphase-outcome strip of the whole run; pieces are placed by action index
   * (left / width in %), so both strips, the first-fix marker and the playhead line up */
  function pos(start, end, n) {
    return 'left:' + (100 * (start - 1) / n).toFixed(3) + '%;width:calc(' + (100 * (end - start + 1) / n).toFixed(3) + '% - 2px)';
  }
  function overview(t, width) {
    var h = '<div class="td-strips"><div class="td-over" role="list" aria-label="Phases (width proportional to actions)">';
    t.phases.forEach(function (p) {
      var n = p.end - p.start + 1, px = width * n / t.n;
      var bad = p.subphases.filter(function (s) { return s.outcome === 'failed' || s.outcome === 'blocked'; }).length;
      h += '<button type="button" role="listitem" class="ov" data-pid="' + esc(p.id) + '" data-label="' + esc(p.phase) + '" style="' + pos(p.start, p.end, t.n) + ';background:' + TV.phaseVar(p.phase) + ';color:' + TV.phaseTextVar(p.phase) + '" ' +
        'data-tip="' + esc(p.phase + ' #' + p.start + '–#' + p.end + ' · ' + TV.plural(n, 'action') + ', ' + TV.plural(p.subphases.length, 'subphase') + (bad ? ', ' + bad + ' failed / blocked' : '')) + '">' +
        '<span>' + esc(p.phase) + '</span>' + (bad && px > 24 ? '<b class="ovbad" aria-hidden="true">' + bad + '</b>' : '') + '</button>';
    });
    h += '</div><div class="td-seg" role="list" aria-label="Subphases, coloured by outcome">';
    t.subs.forEach(function (sg) {
      var n = sg.end - sg.start + 1, ev = TV.EVIDENCE_SHORT[sg.evidence];
      h += '<button type="button" role="listitem" class="tsg o-' + sg.outcome + '" data-sid="' + esc(sg.id) + '" style="' + pos(sg.start, sg.end, t.n) + '" ' +
        'data-tip="' + esc(sg.p.phase + ' · ' + TV.OUTCOME_GLYPH[sg.outcome] + ' ' + sg.outcome + (ev ? ' (' + ev + ')' : '') + ' #' + sg.start + (n > 1 ? '–#' + sg.end : '') + ' · ' + subLabel(sg)) + '" ' +
        'aria-label="' + esc(sg.p.phase + ', ' + sg.outcome) + '"></button>';
    });
    h += '</div>';
    if (t.anchor) h += '<span class="ov-anchor" style="left:' + (100 * (t.anchor - 1) / t.n).toFixed(3) + '%" aria-hidden="true"><b>first fix #' + t.anchor + '</b></span>';
    return h + '<span class="ov-cursor" aria-hidden="true" hidden></span></div>';
  }

  function legend(t) {
    var used = {};
    t.subs.forEach(function (s) { used[s.outcome] = 1; });
    return '<div class="legend td-legend"><span class="lg-t">Subphase outcome</span>' + TV.outcomeLegend(used) +
      '<span class="lg-t">Action</span><span class="vg v-pass">✓ pass</span><span class="vg v-fail">✗ fail</span><span class="muted">(verdict of a build / test run)</span>' +
      (t.anchor ? '<span class="lgm"><i class="anchormk"></i>first fix</span>' : '<span class="muted">· no app-source edit (no first fix)</span>') + '</div>';
  }

  function render(el) {
    root = el;
    var t = TV.traj(), e = TV.exp(t);
    if (!t.n) { el.innerHTML = '<p class="note">This trajectory has no tool calls.</p>'; return; }
    var h = overview(t, Math.max(200, el.clientWidth)) + legend(t) + '<div class="td-list">';
    t.phases.forEach(function (p) { h += phaseHTML(t, p, e); });
    el.innerHTML = h + '</div>';
    fitLabels();
  }
  /* a phase label shows only where it fits (re-checked when the details panel changes the width) */
  function fitLabels() {
    if (!root) return;
    root.querySelectorAll('.td-over .ov').forEach(function (b) {
      var sp = b.querySelector('span');
      sp.textContent = b.dataset.label;
      if (sp.scrollWidth > sp.clientWidth + 1) sp.textContent = '';
    });
  }

  function replacePhase(t, pid) {
    var p = t.phases.filter(function (x) { return x.id === pid; })[0];
    var node = root.querySelector('.pblk[data-pid="' + CSS.escape(pid) + '"]');
    if (!p || !node) return;
    var tmp = document.createElement('div');
    tmp.innerHTML = phaseHTML(t, p, TV.exp(t));
    node.parentNode.replaceChild(tmp.firstChild, node);
  }
  /* after a manual expand / collapse: re-highlight, but do not re-open what the user closed */
  function rerenderPhase(t, pid) {
    replacePhase(t, pid);
    highlight(TV.state.i, { noscroll: true });
  }

  document.addEventListener('click', function (ev) {
    if (!root || !root.contains(ev.target) || TV.state.view !== 'trajectory') return;
    var t = TV.traj(), e = TV.exp(t), b;
    if ((b = ev.target.closest('.ov'))) {
      e.p[b.dataset.pid] = 1;
      rerenderPhase(t, b.dataset.pid);
      var n = root.querySelector('.pblk[data-pid="' + CSS.escape(b.dataset.pid) + '"]');
      if (n) n.scrollIntoView({ block: 'start', behavior: 'smooth' });
      return;
    }
    if ((b = ev.target.closest('.tsg'))) { var sg = t.subById[b.dataset.sid]; if (sg) TV.setCursor(sg.start); return; }
    if ((b = ev.target.closest('.st-h'))) { TV.setCursor(+b.parentNode.dataset.i, { from: 'trajectory' }); return; }
    if ((b = ev.target.closest('.sb-h'))) {
      var sid = b.parentNode.dataset.sid;
      if (e.s[sid]) delete e.s[sid]; else e.s[sid] = 1;
      rerenderPhase(t, t.subById[sid].p.id);
      return;
    }
    if ((b = ev.target.closest('.pb-h'))) {
      var pid = b.parentNode.dataset.pid;
      if (e.p[pid]) delete e.p[pid]; else e.p[pid] = 1;
      rerenderPhase(t, pid);
    }
  });

  /* playhead: reveal the current action (open its phase; at the Steps level also its
   * subphase), then highlight it. A re-render (initial) keeps what the level control set. */
  function onCursor(i, opts) {
    if (!root) return;
    opts = opts || {};
    var t = TV.traj(), a = i ? t.actions[i - 1] : null;
    if (a && a.span && opts.from !== 'trajectory' && !opts.initial) {
      var e = TV.exp(t), open = false;
      if (!e.p[a.span.id]) { e.p[a.span.id] = 1; open = true; }
      if (TV.state.level === 'steps' && a.sub && !e.s[a.sub.id]) { e.s[a.sub.id] = 1; open = true; }
      if (open) replacePhase(t, a.span.id);
    }
    highlight(i, opts);
  }
  /* highlight the current action at the deepest level that is open (+ its subphase and mini token) */
  function highlight(i, opts) {
    opts = opts || {};
    var t = TV.traj();
    root.querySelectorAll('.cur, .hascur').forEach(function (n) { n.classList.remove('cur'); n.classList.remove('hascur'); });
    var c = root.querySelector('.ov-cursor');
    var a = i ? t.actions[i - 1] : null;
    if (c) { c.hidden = !a; if (a) c.style.left = (100 * (i - 0.5) / t.n) + '%'; }
    if (!a) return;
    var tsg = a.sub && root.querySelector('.tsg[data-sid="' + CSS.escape(a.sub.id) + '"]');
    if (tsg) tsg.classList.add('cur');
    var sblk = a.sub && root.querySelector('.sblk[data-sid="' + CSS.escape(a.sub.id) + '"]');
    var target = root.querySelector('.step[data-i="' + i + '"]');
    if (sblk) {
      sblk.classList.add(target ? 'hascur' : 'cur');
      var tok = sblk.querySelector('.ms[data-i="' + i + '"]');
      if (tok) tok.classList.add('cur');
    }
    if (!target) target = sblk;
    if (!target && a.span) target = root.querySelector('.pblk[data-pid="' + CSS.escape(a.span.id) + '"]');
    if (!target) return;
    target.classList.add('cur');
    var away = opts.playing && root.getBoundingClientRect().top > window.innerHeight - 60;   // reader scrolled up: leave them there
    if (!opts.noscroll && opts.from !== 'trajectory' && !away) {
      var r = target.getBoundingClientRect();
      var top = (parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--hdr-h')) || 50) +
        (parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--ph-h')) || 40);
      if (r.top < top + 4 || r.bottom > window.innerHeight - 10) target.scrollIntoView({ block: r.height > window.innerHeight * 0.6 ? 'start' : 'nearest' });
    }
  }

  TV.views.trajectory = { render: render, onCursor: onCursor, relayout: fitLabels };
})();
