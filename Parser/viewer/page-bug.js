/* Bug page (bug.html#bug=<id>&t=<agent>-r<k>&i=<action>): one bug, 3 agents x 3 runs.
 * Loads data/bugs/bug-<id>.js (window.TRAJ_BUG, schema trajview/3) by injecting a <script>
 * (no fetch(), so file:// works); data/overview.js, when present, gives the bug order for
 * prev / next. Shell: run matrix, selected-trajectory bar, playhead, tabs, action details
 * panel, keyboard, URL hash. The tab views live in view-*.js and register on TV.views as
 * { render(el), onCursor(i, opts) }.
 *
 * Playhead (ported from the old viewer.js): play / pause (space), step -/+ (k / j), a range
 * slider over the actions, speed 1-16 actions per second. The cursor S.i drives every view
 * (onCursor) and the details panel. Tabs: Trajectory, Fingerprint (view id timeline),
 * Comparison (view id fingerprint). Hash keys: bug, t, i, v (trajectory|timeline|fingerprint),
 * lvl (phases, the default|categories|steps; subphases and segments open categories),
 * fp (agents|runs), speed, details=0 (cursor set, panel closed), theme; play=1 starts playing
 * on open (read only, never written back). */
(function () {
  'use strict';
  var TV = window.TV, esc = TV.esc, $ = TV.$, $$ = TV.$$;
  var VIEWS = ['trajectory', 'timeline', 'fingerprint'];
  var SPEEDS = [1, 2, 4, 8, 16];
  var S = TV.state = { bug: null, t: null, i: 0, view: 'trajectory', level: 'phases', fp: 'agents', timeMode: false,
    expanded: {}, playing: false, speed: 4, panel: false };
  var B = null;          // the loaded bug: {data, trajs, byKey, agents, runs, maxN}
  var RS = TV.ruleset.get(), RKEY = TV.ruleset.key(RS);
  TV.watchRules(RKEY);
  function status(kind, html) {
    var el = $('#status');
    el.hidden = !html;
    el.className = 'status' + (kind ? ' ' + kind : '');
    el.innerHTML = html || '';
  }
  function rulesLine(extra) {
    return '<span class="rs-name">' + esc(TV.ruleset.label(RS)) + '</span>' + (extra ? '<span class="rs-x">' + extra + '</span>' : '') + '<a class="rs-edit" href="tables.html">Customize the rules</a>';
  }

  /* ---------------------------------------------------------------- bug order (overview) */
  var OV = window.TRAJ_OVERVIEW;
  var BUGS = OV && OV.bugs ? OV.bugs.map(function (b) { return String(b.bug); }).sort(TV.bugSort) : [];

  /* ---------------------------------------------------------------- accessors */
  TV.traj = function () { return B && B.byKey[S.t]; };
  TV.exp = function (t) {
    t = t || TV.traj();
    var e = S.expanded[t.id];
    if (!e) e = S.expanded[t.id] = TV.levelExpansion(t, S.level);
    return e;
  };
  TV.applyLevel = function (t, level) { S.expanded[t.id] = TV.levelExpansion(t, level); };

  /* ---------------------------------------------------------------- hash (throttled while playing) */
  var hashTimer = 0;
  function saveHash() {
    if (hashTimer) return;
    hashTimer = setTimeout(function () {
      hashTimer = 0;
      TV.writeHash({ bug: S.bug, t: S.t, i: S.i || '', v: S.view === 'trajectory' ? '' : S.view,
        lvl: S.level === 'phases' ? '' : S.level, fp: S.fp === 'agents' ? '' : S.fp,
        speed: S.speed === 4 ? '' : S.speed, details: S.i && !S.panel ? '0' : '', theme: TV.readHash().theme });
    }, 150);
  }
  function readHash() {
    var q = TV.readHash();
    if (VIEWS.indexOf(q.v) >= 0) S.view = q.v;
    else if (q.v === 'compare') S.view = 'fingerprint';
    if (TV.levelOf(q.lvl)) S.level = TV.levelOf(q.lvl);
    if (q.fp === 'runs') S.fp = 'runs';
    if (SPEEDS.indexOf(+q.speed) >= 0) S.speed = +q.speed;
    if (q.time) S.timeMode = true;
    return q;
  }

  /* ---------------------------------------------------------------- loading */
  function noData(html) {
    stopPlay();
    $('#app').hidden = true;
    document.body.classList.remove('docked');
    var nd = $('#nodata');
    nd.hidden = false;
    nd.innerHTML = html;
    closePanel(true);
  }
  function loadBug(id, opts) {
    opts = opts || {};
    id = String(id || '').replace(/^bug-/, '');
    stopPlay();
    if (!id) {
      noData('<h2>Which bug?</h2><p>Open a bug from the <a href="index.html">overview</a>, or add <code>#bug=&lt;id&gt;</code> to the address.</p>');
      return;
    }
    S.bug = id;
    B = null;
    $('#bugTitle').textContent = 'bug-' + id;
    document.title = 'bug-' + id + ' · Inceptor';
    navButtons();
    $('#nodata').hidden = true;
    $('#app').hidden = false;
    $('#view').innerHTML = '<div class="loading">Loading bug-' + esc(id) + '…</div>';
    var old = document.getElementById('bugdata');
    if (old) old.parentNode.removeChild(old);
    window.TRAJ_BUG = undefined;
    var s = document.createElement('script');
    s.id = 'bugdata';
    s.src = 'data/bugs/bug-' + encodeURIComponent(id) + '.js';
    s.onload = function () {
      if (S.bug !== id) return;
      var d = window.TRAJ_BUG;
      if (!d || String(d.bug) !== id || !(d.trajectories || []).length) { missing(id, d); return; }
      if (TV.ruleset.isDefault(RS) || d.schema !== 'trajview/3') { ready(d, opts); return; }
      /* the user's rules: re-run this bug's runs from the corpus packs */
      if (!TV.engine.usable()) {
        status('warn', rulesLine('your rules need the analysis engine, which a page opened from a file cannot start; this page shows the <b>built-in lookup tables</b>'));
        ready(d, opts);
        return;
      }
      $('#view').innerHTML = '<div class="loading">Applying your rules to bug-' + esc(id) + '…</div>';
      status('busy', rulesLine('applying them to the ' + d.trajectories.length + ' runs of bug-' + esc(id) + '…'));
      TV.corpus.bug(d, RS).then(function () {
        if (S.bug !== id) return;
        status('ok', rulesLine('applied'));
        ready(d, opts);
      }, function (err) {
        if (S.bug !== id) return;
        status('warn', rulesLine('could not be applied (' + esc(err.message) + '); this page shows the <b>built-in lookup tables</b>'));
        ready(window.TRAJ_BUG, opts);
      });
    };
    s.onerror = function () { if (S.bug === id) missing(id); };
    document.head.appendChild(s);
  }
  function missing(id, d) {
    var known = BUGS.indexOf(id) >= 0;
    noData('<h2>No data for bug-' + esc(id) + '</h2>' +
      (d && !(d.trajectories || []).length ? '<p>The bug file exists but holds no trajectories (nothing converted for it?).</p>' :
        '<p>The page reads <code>viewer/data/bugs/bug-' + esc(id) + '.js</code>, which was not found' + (known ? '' : ' (and the overview does not list this bug)') + '.</p>') +
      '<p>Generate it from the Parser directory:</p><pre>cd Parser\npython3 -m atif.cli convert ' + esc(id) + ' --config original --runs 1 2 3\npython3 -m atif.cli view ' + esc(id) + '</pre>' +
      '<p><a href="index.html">Back to the overview</a>' + (BUGS.length ? ' · <a href="bug.html#bug=' + esc(BUGS[0]) + '">first bug</a>' : '') + '</p>');
  }
  function ready(d, opts) {
    if (d.schema !== 'trajview/3') {
      noData('<h2>Old data for bug-' + esc(d.bug) + '</h2><p>The bug file has schema <code>' + esc(d.schema || '?') + '</code>; this dashboard reads phases and their outcomes (<code>trajview/3</code>). Regenerate the data from the Parser directory:</p>' +
        '<pre>cd Parser\npython3 -m atif.cli view --all</pre>');
      return;
    }
    TV.vocab = d.vocab || {};
    var trajs = d.trajectories.map(TV.prepTraj);
    var agents = (d.agents || TV.AGENT_ORDER).slice();
    B = { data: d, trajs: trajs, byKey: {}, agents: agents, runs: d.runs || [1, 2, 3], maxN: 1 };
    trajs.forEach(function (t) { B.byKey[t.key] = t; B.maxN = Math.max(B.maxN, t.n); });
    TV.bugData = B;
    var want = opts.t && B.byKey[opts.t] ? opts.t : (B.byKey[S.t] ? S.t : null);
    if (!want) {
      var first = agents.map(function (a) { return a + '-r' + B.runs[0]; }).filter(function (k) { return B.byKey[k]; })[0];
      want = first || trajs[0].key;
    }
    S.t = want;
    var t = TV.traj();
    S.i = opts.i ? TV.clamp(+opts.i || 0, 0, t.n) : 0;
    S.panel = !!S.i && opts.details !== '0';
    document.body.classList.add('docked');
    if (!S.panel) document.body.classList.add('dock-off');      // no details column until an action is picked
    renderMatrix();
    renderTrajbar();
    setView(S.view, true);
    syncPanel();
    updateCursorUI();
    measureSticky();
    saveHash();
    if (opts.play) startPlay();
  }

  /* ---------------------------------------------------------------- header nav */
  function navButtons() {
    var k = BUGS.indexOf(S.bug);
    var prev = k > 0 ? BUGS[k - 1] : null, next = k >= 0 && k < BUGS.length - 1 ? BUGS[k + 1] : null;
    var pb = $('#prevBug'), nb = $('#nextBug');
    pb.disabled = !prev; nb.disabled = !next;
    pb.title = prev ? 'Previous: bug-' + prev + ' ( [ )' : 'No previous bug';
    nb.title = next ? 'Next: bug-' + next + ' ( ] )' : 'No next bug';
    pb.dataset.bug = prev || ''; nb.dataset.bug = next || '';
    pb.innerHTML = '&#8249;<span class="lbl"> ' + (prev ? 'bug-' + esc(prev) : '') + '</span>';
    nb.innerHTML = '<span class="lbl">' + (next ? 'bug-' + esc(next) : '') + ' </span>&#8250;';
  }
  function gotoBug(id) {
    if (!id) return;
    S.t = S.t || null;
    S.i = 0;
    S.expanded = {};
    loadBug(id, { t: S.t });
  }
  $('#prevBug').addEventListener('click', function () { gotoBug(this.dataset.bug); });
  $('#nextBug').addEventListener('click', function () { gotoBug(this.dataset.bug); });

  /* ---------------------------------------------------------------- run matrix */
  function renderMatrix() {
    var h = '<div class="mx-corner"></div>' + B.runs.map(function (r) { return '<div class="mx-h">Run ' + r + '</div>'; }).join('');
    B.agents.forEach(function (a) {
      var model = '';
      B.trajs.forEach(function (t) { if (t.agent === a && t.model) model = t.model; });
      h += '<div class="mx-a">' + TV.agentHTML(a) + (model ? '<span class="model">' + esc(model) + '</span>' : '') + '</div>';
      B.runs.forEach(function (r) {
        var key = a + '-r' + r, t = B.byKey[key];
        if (!t) { h += '<div class="cell missing">not converted</div>'; return; }
        h += '<button type="button" class="cell" data-key="' + esc(key) + '" aria-pressed="' + (key === S.t) + '" aria-label="' + esc(a + ' run ' + r + ', ' + t.oc) + '">' +
          '<span class="c1">' + TV.passPill(t.outcome.pass) + '<span class="cn">' + t.n + '<span class="lng"> actions</span></span></span>' +
          '<span class="track">' + TV.stripsHTML(t.strip, t.subStrip, t.n, B.maxN) + '</span>' +
          '</button>';
      });
    });
    var el = $('#matrix');
    el.style.setProperty('--nr', B.runs.length);
    el.innerHTML = h;
  }
  $('#matrix').addEventListener('click', function (e) {
    var c = e.target.closest('.cell[data-key]');
    if (c) TV.select(c.dataset.key);
  });

  function renderTrajbar() {
    var t = TV.traj();
    var dur = t.stats.duration_s != null ? t.stats.duration_s : t.stats.reported_duration_s;
    $('#trajbar').innerHTML = '<h2>' + TV.agentHTML(t.agent) + '<span class="muted">run ' + t.run + '</span>' + TV.passPill(t.outcome.pass) + '</h2>' +
      '<span class="facts">' + TV.plural(t.n, 'action') + ' · ' + TV.plural(t.phases.length, 'phase') +
      (t.anchor ? ' · first fix #' + t.anchor : ' · no app-source edit') +
      (dur != null ? ' · ' + TV.fmtDur(dur) : '') + '</span>';
  }

  /* ---------------------------------------------------------------- selection + cursor */
  /* select a trajectory; opts.i = also put the cursor on that action, opts.view = switch tab */
  TV.select = function (key, opts) {
    opts = opts || {};
    if (!B || !B.byKey[key]) return;
    var changed = key !== S.t;
    if (changed) stopPlay();
    S.t = key;
    var t = TV.traj();
    if (changed) S.i = 0;
    if (opts.i) S.i = TV.clamp(Math.round(+opts.i), 1, t.n);
    S.panel = !!S.i;
    $$('#matrix .cell[data-key]').forEach(function (c) { c.setAttribute('aria-pressed', c.dataset.key === key ? 'true' : 'false'); });
    renderTrajbar();
    syncPanel();                                        // the layout first, then the view at its width
    if (opts.view) setView(opts.view, true); else render();
    updateCursorUI();
    saveHash();
  };
  /* move the playhead; opts.playing = a playback tick (keeps the panel as the user left it),
   * opts.from = the view that was clicked (it need not scroll) */
  TV.setCursor = function (i, opts) {
    opts = opts || {};
    var t = TV.traj();
    if (!t || !t.n) return;
    i = TV.clamp(Math.round(i), 1, t.n);
    S.i = i;
    if (!opts.playing) S.panel = true;
    var v = TV.views[S.view];
    if (v && v.onCursor) {
      try { v.onCursor(i, opts); } catch (err) { if (window.console) console.error(err); }
    }
    syncPanel();
    updateCursorUI();
    saveHash();
  };

  /* ---------------------------------------------------------------- playhead */
  var timer = 0;
  var ICON_PLAY = '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M3 1.4v9.2l7.6-4.6z" fill="currentColor"/></svg>';
  var ICON_PAUSE = '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><rect x="2.2" y="1.5" width="2.8" height="9" rx="0.7" fill="currentColor"/><rect x="7" y="1.5" width="2.8" height="9" rx="0.7" fill="currentColor"/></svg>';
  function playBtn() {
    var b = $('#playBtn');
    b.innerHTML = S.playing ? ICON_PAUSE : ICON_PLAY;
    b.setAttribute('aria-label', S.playing ? 'Pause' : 'Play');
    b.setAttribute('aria-pressed', S.playing ? 'true' : 'false');
    document.body.classList.toggle('playing', S.playing);
  }
  function stopPlay() {
    if (timer) clearInterval(timer);
    timer = 0;
    if (!S.playing) return;
    S.playing = false;
    playBtn();
  }
  function startPlay() {
    var t = TV.traj();
    if (!t || !t.n) return;
    if (timer) clearInterval(timer);
    S.playing = true;
    playBtn();
    // play opens the details at the cursor, except on a phone, where the sheet would cover the view
    var phone = window.matchMedia && window.matchMedia('(max-width: 760px)').matches;
    var o = phone ? { playing: true } : { play: true };
    if (!S.i || S.i >= t.n) TV.setCursor(1, o);                   // start (or restart) at the first action
    else TV.setCursor(S.i, o);
    schedule();
  }
  function schedule() {
    if (timer) clearInterval(timer);
    timer = setInterval(function () {
      var tt = TV.traj();
      if (!tt || S.i >= tt.n) { stopPlay(); return; }
      TV.setCursor(S.i + 1, { playing: true });
    }, 1000 / S.speed);
  }
  TV.togglePlay = function () { if (S.playing) stopPlay(); else startPlay(); };
  TV.stopPlay = stopPlay;
  $('#playBtn').addEventListener('click', TV.togglePlay);
  $('#playBtn').innerHTML = ICON_PLAY;
  $('#stepBack').addEventListener('click', function () { TV.setCursor((S.i || 2) - 1); });
  $('#stepFwd').addEventListener('click', function () { TV.setCursor((S.i || 0) + 1); });
  $('#cursor').addEventListener('input', function (e) { TV.setCursor(+e.target.value, { from: 'slider' }); });
  $('#speed').addEventListener('change', function (e) {
    S.speed = +e.target.value || 4;
    if (S.playing) schedule();
    saveHash();
  });
  function updateCursorUI() {
    var t = TV.traj();
    if (!t) return;
    var a = S.i ? t.actions[S.i - 1] : null, c = $('#cursor');
    c.max = Math.max(1, t.n);
    c.value = S.i || 1;
    c.disabled = !t.n;
    $('#stepBack').disabled = !t.n || S.i <= 1;
    $('#stepFwd').disabled = !t.n || S.i >= t.n;
    $('#playBtn').disabled = !t.n;
    $('#speed').value = String(S.speed);
    $('#cursorLabel').innerHTML = a ? '<b>#' + a.i + '</b><span class="muted">/' + t.n + '</span> <span class="cl-mid">' + esc(a.category) + '</span>' +
        (a.verdict !== 'none' ? ' ' + TV.verdictDot(a.verdict) : '') +
        TV.cursorPhaseHTML(a)
      : '<b>#–</b><span class="muted">/' + t.n + ' · press ▶ or j</span>';
  }

  /* ---------------------------------------------------------------- views */
  function setView(v, force) {
    if (VIEWS.indexOf(v) < 0) v = 'trajectory';
    var changed = v !== S.view;
    S.view = v;
    $$('.tabs [data-view]').forEach(function (b) { b.setAttribute('aria-selected', b.dataset.view === v ? 'true' : 'false'); });
    $('#viewTitle').textContent = v === 'fingerprint' ? 'Trajectory Comparison' : 'Trajectory Inspection';
    if (changed || force) render();
    saveHash();
  }
  TV.setView = setView;
  TV.setLevel = function (lvl) {
    S.level = lvl;
    TV.applyLevel(TV.traj(), lvl);
    render();
    saveHash();
  };
  TV.setFp = function (mode) { S.fp = mode === 'runs' ? 'runs' : 'agents'; render(); saveHash(); };
  TV.setTimeMode = function (on) { S.timeMode = !!on; render(); };
  function tabCtl() {
    var t = TV.traj(), h = '';
    if (S.view === 'trajectory') {
      h = TV.levelCtlHTML(S.level);
    } else if (S.view === 'timeline') {
      h = t.hasTs ? '<span class="seg small" role="group" aria-label="x axis"><button type="button" data-x="index" aria-pressed="' + !S.timeMode + '">action #</button>' +
        '<button type="button" data-x="time" aria-pressed="' + S.timeMode + '">wall-clock</button></span>' : '<span class="muted small">x = action # (no timestamps in this log)</span>';
    } else if (S.view === 'fingerprint') {
      h = '<span class="seg small" role="group" aria-label="Fingerprints of"><button type="button" data-fp="agents" aria-pressed="' + (S.fp === 'agents') + '" title="the three agents in the selected run">3 agents · run ' + t.run + '</button>' +
        '<button type="button" data-fp="runs" aria-pressed="' + (S.fp === 'runs') + '" title="the selected agent in each of its runs">' + esc(t.agent) + ' · ' + B.runs.length + ' runs</button></span>';
    }
    $('#tabCtl').innerHTML = h;
  }
  $('#tabCtl').addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.level) TV.setLevel(b.dataset.level);
    else if (b.dataset.x) TV.setTimeMode(b.dataset.x === 'time');
    else if (b.dataset.fp) TV.setFp(b.dataset.fp);
  });
  function render() {
    if (!B) return;
    tabCtl();
    var el = $('#view'), v = TV.views[S.view];
    TV.tip.hide();
    try {
      v.render(el);
      if (v.onCursor && S.i) v.onCursor(S.i, { initial: true, noscroll: true });
    } catch (err) {
      el.innerHTML = '<p class="note">View error: ' + esc(err && err.message) + '</p>';
      if (window.console) console.error(err);
    }
  }
  TV.render = render;
  $$('.tabs [data-view]').forEach(function (b) { b.addEventListener('click', function () { setView(b.dataset.view); }); });
  var resizeTimer = 0;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { measureSticky(); if (!RO) relayout(); }, 120);
  });
  /* the view follows its own width: a ResizeObserver redraws it in the frame where the width
   * changed (the details panel opened or closed, the window resized), so no frame with the old
   * layout is ever painted (a delayed redraw made the view flicker) */
  var viewW = 0, RO = window.ResizeObserver;
  if (RO) {
    new RO(function (entries) {
      var w = Math.round(entries[0].contentRect.width);
      if (!w || w === viewW) return;
      var first = !viewW;
      viewW = w;
      if (!first) relayout();
    }).observe(widthProbe($('#view')));
  }
  /* a zero-height box as wide as the view: its size never follows the view's content, so a
   * redraw cannot notify the observer again */
  function widthProbe(view) {
    var probe = document.createElement('div');
    probe.className = 'wprobe';
    probe.setAttribute('aria-hidden', 'true');
    view.parentNode.insertBefore(probe, view);
    return probe;
  }
  /* width-dependent views re-render; the Trajectory view only re-fits its labels (keeps scroll) */
  function relayout() {
    if (!B) return;
    var v = TV.views[S.view];
    if (v && v.relayout) v.relayout(); else render();
  }
  /* the sticky playhead sits under the sticky header; scrolled-to items clear both */
  function measureSticky() {
    var hh = $('header.top').offsetHeight || 0, ph = $('#playhead').offsetHeight || 0;
    document.documentElement.style.setProperty('--hdr-h', hh + 'px');
    document.documentElement.style.setProperty('--ph-h', ph + 'px');
  }

  /* ---------------------------------------------------------------- details panel */
  /* the panel shows the cursor's action while S.panel is on; closing it keeps the cursor */
  function syncPanel() {
    var t = TV.traj();
    var want = !!(t && S.i && S.panel);
    var was = document.body.classList.contains('panel-open');
    document.body.classList.toggle('panel-open', want);
    if (want) { document.body.classList.remove('dock-off'); renderPanel(); } else emptyPanel();
    if (want !== was && !RO) setTimeout(relayout, 180);                   // no ResizeObserver: redraw after the slide
  }
  /* no action picked: the docked column says how to fill it */
  function emptyPanel() {
    $('#dtI').textContent = '#–';
    $('#dtOf').textContent = '';
    $('#dtPrev').disabled = $('#dtNext').disabled = true;
    $('#dtBody').innerHTML = '<p class="dt-empty">Click an action, or press <kbd>j</kbd>.</p>';
  }
  /* closing also removes the docked column; picking an action brings it back */
  function closePanel(silent) {
    S.panel = false;
    if (silent) { document.body.classList.remove('panel-open'); return; }
    var off = document.body.classList.contains('dock-off');
    document.body.classList.add('dock-off');
    syncPanel();
    if (!off && !RO) setTimeout(relayout, 180);
  }
  TV.closePanel = closePanel;
  function renderPanel() {
    var t = TV.traj(), a = t.actions[S.i - 1];
    if (!a) return;
    $('#dtI').textContent = '#' + a.i;
    $('#dtOf').textContent = 'of ' + t.n + ' · ' + t.agent + ' run ' + t.run;
    $('#dtPrev').disabled = a.i <= 1;
    $('#dtNext').disabled = a.i >= t.n;
    $('#dtBody').innerHTML = TV.detailsActsHTML(a) + TV.actionDetailsHTML(t, a);
    if (TV.steps) TV.steps.fill($('#dtBody'), t, a);
    $('#dtBody').scrollTop = 0;
  }
  $('#dtPrev').addEventListener('click', function () { TV.setCursor(S.i - 1); });
  $('#dtNext').addEventListener('click', function () { TV.setCursor(S.i + 1); });
  $('#dtClose').addEventListener('click', function () { closePanel(); });

  /* ---------------------------------------------------------------- keyboard */
  document.addEventListener('keydown', function (e) {
    var tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' && e.target.type !== 'range') return;
    if (tag === 'select' || tag === 'textarea' || e.metaKey || e.ctrlKey || e.altKey) return;
    if (!B) { if (e.key === '[' || e.key === ']') gotoBug(e.key === '[' ? $('#prevBug').dataset.bug : $('#nextBug').dataset.bug); return; }
    var k = e.key;
    if (k === 'j') { TV.setCursor((S.i || 0) + 1); e.preventDefault(); }
    else if (k === 'k') { TV.setCursor((S.i || 2) - 1); e.preventDefault(); }
    else if (k === ' ' && tag !== 'button') { TV.togglePlay(); e.preventDefault(); }
    else if (k === 'Escape') { if (!$('#help').hidden) $('#help').hidden = true; else closePanel(); }
    else if (k === '1' || k === '2' || k === '3') setView(VIEWS[+k - 1]);
    else if (k === 'e' && S.view === 'trajectory') TV.setLevel('steps');
    else if (k === 'c' && S.view === 'trajectory') TV.setLevel('phases');
    else if (k === '[') gotoBug($('#prevBug').dataset.bug);
    else if (k === ']') gotoBug($('#nextBug').dataset.bug);
    else if (k === '?') $('#help').hidden = !$('#help').hidden;
  });

  /* ---------------------------------------------------------------- init + hash navigation */
  setTimeout(function () { document.body.classList.remove('preload'); }, 400);   // no slide-in on first paint
  var q = readHash();
  S.t = /^\w+-r\d+$/.test(q.t || '') ? q.t : null;
  $('#speed').value = String(S.speed);
  loadBug(q.bug || '', { t: S.t, i: q.i, details: q.details, play: q.play === '1' || q.play === 'true' });
  window.addEventListener('hashchange', function () {
    var q2 = TV.readHash();
    var id = String(q2.bug || '').replace(/^bug-/, '');
    if (id && id !== S.bug) { S.expanded = {}; readHash(); loadBug(id, { t: q2.t, i: q2.i, play: q2.play === '1' }); }
    else if (B && q2.t && q2.t !== S.t && B.byKey[q2.t]) TV.select(q2.t, { i: q2.i });
  });
})();
