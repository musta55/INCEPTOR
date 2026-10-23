/* An uploaded trajectory (analyze.html#u=<id>), next to the corpus, or a comparison of uploads
 * (analyze.html#g=<group>&m=<member>, set up on upload.html; analyze.html#b=<bug>&m=<member>,
 * every upload of one bug, opened from the corpus table). Uploading itself is upload.html;
 * analyze.html with nothing named goes to the corpus page.
 *
 *   analyze.html#g=<id>   a comparison group (uploads.js groups): a bar with its members (one
 *                         bug's agents, or one agent's runs), the selected member shown as
 *                         below, and the Fingerprint tab with every member side by side.
 *   analyze.html#b=<bug>  the same for every upload of a bug (TV.uploads.bugGroup): each
 *                         agent's runs, labelled "agent · run n" as in the Corpus Overview.
 *
 *   analyze.html#u=<id>   one upload (uploads.js): its file bar (bug id, external validation,
 *                         previous / next, delete), its unrecognised steps with a suggested
 *                         lookup-table row for each (review.js), then the bug page's
 *                         Trajectory and Fingerprint tabs (Comparison: the view id
 *                         fingerprint, Fingerprint: the view id timeline).
 *
 * Every upload is analysed with the one table file of tables.html (TV.ruleset); one analysed
 * with other rules is analysed again when opened. The corpus side of the comparison is
 * data/overview.js, re-run under the same rules when they are not the default ones
 * (TV.corpus). This file gives the views the shell they expect: TV.traj, TV.exp, TV.state,
 * TV.setCursor, the playhead and the details panel. */
(function () {
  'use strict';
  var TV = window.TV, esc = TV.esc, $ = TV.$, $$ = TV.$$;
  var VIEWS = ['trajectory', 'timeline', 'fingerprint'];
  var S = TV.state = { t: null, i: 0, view: 'trajectory', level: 'phases', fp: 'agents', timeMode: false,
    expanded: {}, playing: false, speed: 4, panel: false };
  var D = window.TRAJ_OVERVIEW && window.TRAJ_OVERVIEW.schema === 'trajview-overview/3' ? window.TRAJ_OVERVIEW : null;
  var RS = TV.ruleset.get(), RKEY = TV.ruleset.key(RS);
  TV.watchRules(RKEY);
  var REC = null;                  // the open upload
  var CUR = null;                  // its prepared trajectory
  var LIST = [];                   // every upload, newest first
  var GROUP = null;                // the open comparison: {g (uploads.js group), byKey: {upload id: trajectory}}
  if (D) TV.vocab = D.vocab || {};

  function busy(text) { $('#busy').hidden = !text; if (text) $('#busyText').textContent = text; }
  function status(kind, html) {
    var el = $('#status');
    el.hidden = !html;
    el.className = 'status' + (kind ? ' ' + kind : '');
    el.innerHTML = html || '';
  }

  /* ---------------------------------------------------------------- routing */
  function route() {
    var q = TV.readHash();
    stopPlay();
    if (VIEWS.indexOf(q.v) >= 0) S.view = q.v;
    S.fp = q.fp === 'runs' ? 'runs' : 'agents';
    if (q.g) openGroup(q.g, q.m);
    else if (q.b) openGroup('b:' + q.b, q.m);
    else if (q.u) { GROUP = null; openUpload(q.u); }
    else location.replace('index.html');            // uploading is upload.html
  }
  function saveHash() {
    if (GROUP) TV.writeHash(Object.assign(GROUP.g.kind === 'bug' ? { b: GROUP.g.bug } : { g: GROUP.g.id },
      { m: REC && REC.id, v: S.view === 'trajectory' ? '' : S.view, fp: S.fp === 'runs' ? 'runs' : '', theme: TV.readHash().theme }));
  }
  window.addEventListener('hashchange', route);
  TV.steps.source = function (t) { return REC && t._src === REC.id ? TV.uploads.atif(REC) : null; };

  /* ---------------------------------------------------------------- a comparison group */
  function openGroup(gid, mid) {
    $('#err').hidden = true;
    $('#trajScreen').hidden = false;
    TV.uploads.list().then(function (xs) {
      LIST = xs;
      var g = /^b:/.test(gid) ? TV.uploads.bugGroup(null, xs.filter(function (r) { return r && r.result && r.result.trajectory; }), gid.slice(2)) :
        TV.uploads.groups(xs).filter(function (x) { return x.id === gid; })[0];
      if (g && !g.members.length) g = null;
      if (!g) {
        $('#trajScreen').hidden = true;
        $('#err').innerHTML = '<b>' + (/^b:/.test(gid) ? 'No upload of ' + esc(TV.bugName(gid.slice(2))) : 'No comparison ' + esc(gid)) + ' in this browser.</b> <a href="index.html">Back to the corpus</a>';
        $('#err').hidden = false;
        return;
      }
      var stale = TV.engine.usable() ? g.members.filter(function (r) { return r.rulesKey !== RKEY; }) : [];
      return stale.reduce(function (p, r, k) {
        return p.then(function () {
          busy('Applying the tables to ' + r.name + (stale.length > 1 ? ' (' + (k + 1) + ' of ' + stale.length + ')' : '') + '…');
          return TV.uploads.reanalyze(r, RS).catch(function () { /* shown as it was analysed */ });
        });
      }, Promise.resolve()).then(function () {
        busy('');
        GROUP = { g: g, byKey: {} };
        g.members.forEach(function (r) { GROUP.byKey[r.id] = prepUpload(r); });
        groupData();
        $('#fpTab').hidden = false;
        show(g.members.filter(function (r) { return r.id === mid; })[0] || g.members[0], true);
      });
    });
  }
  /* the members as the Fingerprint view reads them (TV.bugData.group); a bug's runs show as on
   * the bug page: its agents in the open run, or the open agent's runs (S.fp) */
  function groupData() {
    var g = GROUP.g, members = g.members, kind = g.kind, run = null;
    if (kind === 'bug' && REC) {
      var cur = members.filter(function (r) { return r.id === REC.id; })[0] || members[0], ag = TV.uploads.agent(cur);
      if (S.fp === 'runs') { kind = 'runs'; members = members.filter(function (r) { return TV.uploads.agent(r) === ag; }); }
      else { kind = 'agents'; run = cur._bugRun; members = members.filter(function (r) { return r._bugRun === run; }); }
    }
    TV.bugData = { agents: [], runs: [], byKey: GROUP.byKey, trajs: g.members.map(function (r) { return GROUP.byKey[r.id]; }),
      group: { kind: kind, run: run, rows: members.map(function (r) {
        return { key: r.id, t: GROUP.byKey[r.id], label: g.kind !== 'bug' ? TV.uploads.memberLabel(r, members) : kind === 'runs' ? 'run ' + r._bugRun : TV.uploads.agent(r) };
      }) } };
  }
  function renderGroupBar() {
    var el = $('#grpbar');
    el.hidden = !GROUP;
    if (!GROUP) return;
    var g = GROUP.g;
    el.innerHTML = '<h1>' + esc(g.name || 'Comparison') + '</h1><span class="gk">' + esc(TV.uploads.KINDS[g.kind] || '') + '</span><div class="gmembers" role="group" aria-label="Members">' +
      g.members.map(function (r) { return { key: r.id, t: GROUP.byKey[r.id], label: TV.uploads.memberLabel(r, g.members) }; }).map(function (x) {
        var t = x.t, a = t.agent, extra = g.kind !== 'runs' && x.label !== a ? ' <span class="muted small">' + esc(x.label.slice(a.length + 3)) + '</span>' : '';
        return '<button type="button" class="gmem" data-mem="' + esc(x.key) + '" aria-pressed="' + (REC && x.key === REC.id) + '">' +
          (g.kind === 'runs' ? '<b>' + esc(x.label) + '</b>' : TV.agentHTML(a, extra)) + TV.markHTML(t.outcome.pass, 'external validation: ' + TV.EXTERNAL_WORD[TV.oc(t.outcome.pass)]) + '<span class="n">' + t.n + '</span></button>';
      }).join('') + '</div>' + '<span class="gk gext" data-tip="' + esc(TV.EXTERNAL_DEF) + '">' + TV.extBox(true) + TV.extBox(false) + 'external validation</span>' +
      (g.kind === 'bug' ? '' : '<a class="btn small" href="upload.html#g=' + encodeURIComponent(g.id) + '">Edit</a>');
  }
  $('#grpbar').addEventListener('click', function (e) {
    var b = e.target.closest('[data-mem]');
    if (b) TV.select(b.dataset.mem);
  });

  /* ---------------------------------------------------------------- one upload */
  function openUpload(id) {
    $('#err').hidden = true;
    $('#trajScreen').hidden = false;
    TV.uploads.list().then(function (xs) {
      LIST = xs;
      var rec = xs.filter(function (r) { return r.id === id; })[0];
      if (!rec) {
        $('#trajScreen').hidden = true;
        $('#err').innerHTML = '<b>No upload ' + esc(id) + ' in this browser.</b> Uploads are kept per browser; it may have been deleted. <a href="index.html">Back to the corpus</a>';
        $('#err').hidden = false;
        return;
      }
      if (rec.rulesKey === RKEY) { show(rec, true); return; }
      if (!TV.engine.usable()) { show(rec, true); status('warn', 'This upload was analysed with other rules; analysing it again needs the analysis engine.'); return; }
      busy('Applying the tables to ' + rec.name + '…');
      TV.uploads.reanalyze(rec, RS).then(function (r) { busy(''); show(r, true); }, function (err) {
        busy('');
        show(rec, true);
        status('warn', 'Could not apply the current tables (' + esc(err.message) + '); this shows the tables it was analysed with.');
      });
    });
  }
  /* an upload's trajectory, prepared (TV.prepTraj), keyed by the upload's id; in a 'runs'
   * group its run is the run number given on upload.html */
  function prepUpload(rec) {
    var res = rec.result, t = TV.prepTraj(res.trajectory);
    t._src = rec.id;
    t.agent = TV.uploads.agent(rec);                  // the folder's name for it, when it gave one
    if (rec.group && rec.group.kind === 'runs') t.run = rec.run || 1;
    t.key = rec.id;
    var byIndex = {};
    t.actions.forEach(function (a) { a.rules = []; byIndex[a.i] = a; });
    ((res.rules || {}).optional || []).concat((res.rules || {}).custom || []).forEach(function (r) {
      (r.matched || []).forEach(function (i) { if (byIndex[i]) byIndex[i].rules.push({ id: r.id, sentence: r.sentence }); });
    });
    return t;
  }
  function show(rec, fresh) {
    REC = rec;
    var res = rec.result, t = prepUpload(rec), src = res.source || {}, longId = !/^\d*$/.test(String(rec.bug || src.bug || ''));
    if (res.vocab) TV.vocab = res.vocab;
    if (GROUP && GROUP.byKey[rec.id]) { GROUP.byKey[rec.id] = t; groupData(); }
    renderGroupBar();
    $('.fb-nav').hidden = $('#delUp').hidden = !!GROUP;
    var keepI = !fresh && CUR ? S.i : 0;
    CUR = t;
    S.t = t.key;
    if (fresh) S.expanded = {};
    S.i = keepI ? TV.clamp(keepI, 1, t.n) : 0;
    if (!S.i) S.panel = false;
    /* the bug and the agent only; the file's own details are in the title's tooltip */
    var bugKey = TV.uploads.bug(rec), head = bugKey ? TV.bugName(bugKey) : rec.name;
    document.title = head + ' · ' + t.agent + ' · Inceptor';
    document.body.classList.add('has-result', 'docked');
    if (!S.i) document.body.classList.add('dock-off');          // no details column until an action is picked
    $('#fname').textContent = head;
    $('#fname').title = [rec.name, src.model, rec.dataset, TV.uploads.formatLabel(src.format), TV.uploads.sizeLabel(rec.size || 0)].filter(Boolean).join(' · ');
    $('#fmeta').innerHTML = TV.agentHTML(t.agent);
    $('#bugLbl').textContent = 'Bug';
    $('#bugFld').title = 'The bug the log works on; paths are read relative to its checkout';
    $('#bug').style.width = longId ? '190px' : '';
    $('#bug').inputMode = 'text';
    $('#bug').value = rec.bug || '';
    $('#bug').placeholder = src.bug || 'id';
    $$('#outcomeSeg button').forEach(function (b) {
      b.setAttribute('aria-pressed', b.dataset.oc === (rec.outcome === true ? 'pass' : rec.outcome === false ? 'fail' : '') ? 'true' : 'false');
    });
    var k = LIST.map(function (r) { return r.id; }).indexOf(rec.id);
    $('#prevUp').disabled = k <= 0;
    $('#nextUp').disabled = k < 0 || k >= LIST.length - 1;
    $('#prevUp').title = k > 0 ? 'Newer: ' + LIST[k - 1].name + ' ( [ )' : 'No newer upload';
    $('#nextUp').title = k >= 0 && k < LIST.length - 1 ? 'Older: ' + LIST[k + 1].name + ' ( ] )' : 'No older upload';
    $('#notes').innerHTML = (res.warnings || []).map(function (w) { return '<p class="note">' + esc(w) + '</p>'; }).join('');
    renderReview(res);
    var changed = ((res.rules || {}).optional || []).concat((res.rules || {}).custom || []).reduce(function (s, r) { return s + (r.matched || []).length; }, 0);
    if (!$('#status').classList.contains('warn')) {               // only your own rows are worth a line
      status('', TV.ruleset.isDefault(RS) ? '' : '<span class="rs-name">' + esc(TV.ruleset.label(RS)) + '</span><span class="rs-x">they changed ' + TV.plural(changed, 'action') + ' here</span><a class="rs-edit" href="tables.html">Customize the rules</a>');
    }
    syncPanel();
    setView(S.view, true);
    updateCursorUI();
    measureSticky();
    saveHash();
  }
  /* unrecognised steps: a suggested row each; adding rows analyses the upload again */
  function renderReview(res) {
    var el = $('#unrec');
    el.innerHTML = TV.review.html(res.unrecognized, { goto: true });
    var card = el.querySelector('.unrec');
    if (!card) return;
    TV.review.bind(card, res.unrecognized, function (rs, rows) {
      RS = rs;
      RKEY = TV.ruleset.key(RS);
      TV.rulesShown(RKEY);
      busy('Analysing ' + REC.name + ' with ' + TV.plural(rows.length, 'new rule') + '…');
      TV.uploads.reanalyze(REC, RS).then(function (r) {
        busy('');
        if (GROUP) { route(); return; }                          // the other members get the rows too
        show(r, false);
        status('ok', '<span class="rs-name">' + esc(TV.ruleset.label(RS)) + '</span><span class="rs-x">added ' + TV.plural(rows.length, 'row') +
          '; your other uploads and the corpus get them when you open them</span><a class="rs-edit" href="tables.html">See the tables</a>');
      }, function (err) { busy(''); status('warn', 'The rules were added, but this upload could not be analysed again: ' + esc(err.message)); });
    });
  }

  /* bug id and external validation */
  var bugTimer = 0;
  $('#bug').addEventListener('input', function () {
    clearTimeout(bugTimer);
    var v = this.value.replace(/^bug-/, '').trim();
    bugTimer = setTimeout(function () {
      if (!REC || (REC.bug || '') === v) return;
      REC.bug = v || null;
      busy('Analysing with bug-' + (v || '?') + '…');
      TV.uploads.reanalyze(REC, RS).then(function (r) { busy(''); show(r, false); }, function (err) { busy(''); status('warn', 'Could not analyse it again: ' + esc(err.message)); });
    }, 700);
  });
  $('#outcomeSeg').addEventListener('click', function (e) {
    var b = e.target.closest('button[data-oc]');
    if (!b || !REC) return;
    TV.uploads.setOutcome(REC, b.dataset.oc === 'pass' ? true : b.dataset.oc === 'fail' ? false : null).then(function (r) { show(r, false); });
  });
  function step(d) {
    if (GROUP) {                                      // within the comparison
      var ms = GROUP.g.members, j = ms.indexOf(REC) + d;
      if (ms[j]) TV.select(ms[j].id);
      return;
    }
    var k = LIST.map(function (r) { return r.id; }).indexOf(REC && REC.id);
    var next = LIST[k + d];
    if (next) location.hash = 'u=' + encodeURIComponent(next.id);
  }
  $('#prevUp').addEventListener('click', function () { step(-1); });
  $('#nextUp').addEventListener('click', function () { step(1); });
  $('#delUp').addEventListener('click', function () {
    if (!REC || !window.confirm('Delete ' + REC.name + ' from this browser? This cannot be undone.')) return;
    TV.uploads.remove([REC.id]).then(function () { location.href = 'index.html'; });
  });

  /* ---------------------------------------------------------------- the views' shell */
  TV.traj = function () { return CUR; };
  TV.applyLevel = function (t, level) { S.expanded[t.id] = TV.levelExpansion(t, level); };
  TV.exp = function (t) {
    t = t || CUR;
    return S.expanded[t.id] || (S.expanded[t.id] = TV.levelExpansion(t, S.level));
  };
  TV.setCursor = function (i, opts) {
    opts = opts || {};
    var t = CUR;
    if (!t || !t.n) return;
    S.i = TV.clamp(Math.round(i), 1, t.n);
    if (!opts.playing) S.panel = true;
    var v = TV.views[S.view];
    if (v && v.onCursor) { try { v.onCursor(S.i, opts); } catch (err) { if (window.console) console.error(err); } }
    syncPanel();
    updateCursorUI();
  };
  /* a comparison's member (the Fingerprint view and the group bar select one) */
  TV.select = function (key, opts) {
    if (!GROUP || !GROUP.byKey[key]) return;
    var rec = GROUP.g.members.filter(function (r) { return r.id === key; })[0];
    if (!rec) return;
    stopPlay();
    if (rec !== REC) show(rec, true);
    if (opts && opts.i) TV.setCursor(opts.i);
  };
  function setView(v, force) {
    if (VIEWS.indexOf(v) < 0 || (v === 'fingerprint' && !GROUP)) v = 'trajectory';
    var changed = v !== S.view;
    S.view = v;
    $$('.tabs [data-view]').forEach(function (b) { b.setAttribute('aria-selected', b.dataset.view === v ? 'true' : 'false'); });
    $('#viewTitle').textContent = v === 'fingerprint' ? 'Trajectory Comparison' : 'Trajectory Inspection';
    if (changed || force) render();
    saveHash();
  }
  function tabCtl() {
    var h = '';
    if (S.view === 'fingerprint') {
      var g = GROUP && GROUP.g;
      if (g && g.kind === 'bug' && REC) {
        var ag = TV.uploads.agent(REC), run = REC._bugRun;
        var nAg = g.members.filter(function (r) { return r._bugRun === run; }).length, nRun = g.members.filter(function (r) { return TV.uploads.agent(r) === ag; }).length;
        h = '<span class="seg small" role="group" aria-label="Fingerprints of"><button type="button" data-fp="agents" aria-pressed="' + (S.fp !== 'runs') + '" title="the agents in the selected run">' + TV.plural(nAg, 'agent') + ' · run ' + run + '</button>' +
          '<button type="button" data-fp="runs" aria-pressed="' + (S.fp === 'runs') + '" title="the selected agent in each of its runs">' + esc(ag) + ' · ' + TV.plural(nRun, 'run') + '</button></span>';
      }
    } else if (S.view === 'trajectory') {
      h = TV.levelCtlHTML(S.level);
    } else if (CUR.hasTs) {
      h = '<span class="seg small" role="group" aria-label="x axis"><button type="button" data-x="index" aria-pressed="' + !S.timeMode + '">action #</button>' +
        '<button type="button" data-x="time" aria-pressed="' + S.timeMode + '">wall-clock</button></span>';
    } else h = '<span class="muted small">x = action # (no timestamps in this log)</span>';
    $('#tabCtl').innerHTML = h;
  }
  $('#tabCtl').addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.level) { S.level = b.dataset.level; TV.applyLevel(CUR, S.level); render(); }
    else if (b.dataset.x) { S.timeMode = b.dataset.x === 'time'; render(); }
    else if (b.dataset.fp) { S.fp = b.dataset.fp === 'runs' ? 'runs' : 'agents'; groupData(); render(); saveHash(); }
  });
  function render() {
    if (!CUR) return;
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
  function relayout() {
    if (!CUR) return;
    var v = TV.views[S.view];
    if (v && v.relayout) v.relayout(); else render();
  }
  function measureSticky() {
    document.documentElement.style.setProperty('--hdr-h', ($('header.top').offsetHeight || 0) + 'px');
    document.documentElement.style.setProperty('--ph-h', ($('#playhead').offsetHeight || 0) + 'px');
  }

  /* ---------------------------------------------------------------- playhead */
  var play = 0;
  var ICON_PLAY = '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M3 1.4v9.2l7.6-4.6z" fill="currentColor"/></svg>';
  var ICON_PAUSE = '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><rect x="2.2" y="1.5" width="2.8" height="9" rx="0.7" fill="currentColor"/><rect x="7" y="1.5" width="2.8" height="9" rx="0.7" fill="currentColor"/></svg>';
  function playBtn() {
    var b = $('#playBtn');
    b.innerHTML = S.playing ? ICON_PAUSE : ICON_PLAY;
    b.setAttribute('aria-label', S.playing ? 'Pause' : 'Play');
    document.body.classList.toggle('playing', S.playing);
  }
  function stopPlay() {
    if (play) clearInterval(play);
    play = 0;
    if (S.playing) { S.playing = false; playBtn(); }
  }
  function startPlay() {
    if (!CUR || !CUR.n) return;
    S.playing = true;
    playBtn();
    TV.setCursor(!S.i || S.i >= CUR.n ? 1 : S.i, { playing: true });
    schedule();
  }
  function schedule() {
    if (play) clearInterval(play);
    play = setInterval(function () {
      if (!CUR || S.i >= CUR.n) { stopPlay(); return; }
      TV.setCursor(S.i + 1, { playing: true });
    }, 1000 / S.speed);
  }
  function togglePlay() { if (S.playing) stopPlay(); else startPlay(); }
  $('#playBtn').addEventListener('click', togglePlay);
  $('#playBtn').innerHTML = ICON_PLAY;
  $('#stepBack').addEventListener('click', function () { TV.setCursor((S.i || 2) - 1); });
  $('#stepFwd').addEventListener('click', function () { TV.setCursor((S.i || 0) + 1); });
  $('#cursor').addEventListener('input', function (e) { TV.setCursor(+e.target.value, { from: 'slider' }); });
  $('#speed').addEventListener('change', function (e) { S.speed = +e.target.value || 4; if (S.playing) schedule(); });
  function updateCursorUI() {
    var t = CUR;
    if (!t) return;
    var a = S.i ? t.actions[S.i - 1] : null, c = $('#cursor');
    c.max = Math.max(1, t.n);
    c.value = S.i || 1;
    c.disabled = !t.n;
    $('#stepBack').disabled = !t.n || S.i <= 1;
    $('#stepFwd').disabled = !t.n || S.i >= t.n;
    $('#playBtn').disabled = !t.n;
    $('#cursorLabel').innerHTML = a ? '<b>#' + a.i + '</b><span class="muted">/' + t.n + '</span> <span class="cl-mid">' + esc(a.category) + '</span>' +
        (a.verdict !== 'none' ? ' ' + TV.verdictDot(a.verdict) : '') +
        TV.cursorPhaseHTML(a)
      : '<b>#–</b><span class="muted">/' + t.n + ' · press ▶ or j</span>';
  }

  /* ---------------------------------------------------------------- details panel */
  function syncPanel() {
    var want = !!(CUR && S.i && S.panel);
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
  function closePanel() {
    var off = document.body.classList.contains('dock-off');
    S.panel = false;
    document.body.classList.add('dock-off');
    syncPanel();
    if (!off && !RO) setTimeout(relayout, 180);
  }
  TV.closePanel = closePanel;
  function renderPanel() {
    var t = CUR, a = t.actions[S.i - 1];
    if (!a) return;
    $('#dtI').textContent = '#' + a.i;
    $('#dtOf').textContent = 'of ' + t.n + ' · ' + t.agent;
    $('#dtPrev').disabled = a.i <= 1;
    $('#dtNext').disabled = a.i >= t.n;
    $('#dtBody').innerHTML = TV.detailsActsHTML(a) + TV.actionDetailsHTML(t, a);
    if (TV.steps) TV.steps.fill($('#dtBody'), t, a);
    $('#dtBody').scrollTop = 0;
  }
  $('#dtPrev').addEventListener('click', function () { TV.setCursor(S.i - 1); });
  $('#dtNext').addEventListener('click', function () { TV.setCursor(S.i + 1); });
  $('#dtClose').addEventListener('click', closePanel);

  /* ---------------------------------------------------------------- keyboard */
  document.addEventListener('keydown', function (e) {
    var tag = (e.target.tagName || '').toLowerCase();
    if ((tag === 'input' && e.target.type !== 'range') || tag === 'select' || tag === 'textarea' || e.metaKey || e.ctrlKey || e.altKey) return;
    var k = e.key;
    if (k === 'Escape') { if (!$('#help').hidden) $('#help').hidden = true; else closePanel(); return; }
    if (k === '?') { $('#help').hidden = !$('#help').hidden; return; }
    if (!CUR) return;
    if (k === 'j') { TV.setCursor((S.i || 0) + 1); e.preventDefault(); }
    else if (k === 'k') { TV.setCursor((S.i || 2) - 1); e.preventDefault(); }
    else if (k === ' ' && tag !== 'button') { togglePlay(); e.preventDefault(); }
    else if (k === '1' || k === '2' || (k === '3' && GROUP)) setView(VIEWS[+k - 1]);
    else if (k === '[') step(-1);
    else if (k === ']') step(1);
  });

  setTimeout(function () { document.body.classList.remove('preload'); }, 400);
  route();
})();
