/* Analyze page (analyze.html): one uploaded log, your own rules.
 * Needs the local server (python3 -m atif.cli serve): GET /api/rules gives the mandatory and
 * optional rules and the vocabularies, POST /api/analyze runs atif.upload.analyze on the log under the
 * current rule set and returns one trajview/3 trajectory plus a report per rule. Every
 * change of a rule, the bug id or the outcome re-runs the analysis on the log kept in memory.
 * The rule set is remembered in localStorage (a convenience; export it to keep it).
 * The Trajectory and Timeline views are the bug page's (view-*.js); this file gives them the
 * shell they expect: TV.traj, TV.exp, TV.state, TV.setCursor, the playhead and the details panel. */
(function () {
  'use strict';
  var TV = window.TV, esc = TV.esc, $ = TV.$, $$ = TV.$$;
  var VIEWS = ['trajectory', 'timeline'];
  var STORE = 'tv-rules', OPEN = 'tv-rules-open';
  var S = TV.state = { t: null, i: 0, view: 'trajectory', level: 'subphases', fp: 'agents', timeMode: false,
    expanded: {}, playing: false, speed: 4, panel: false };
  var INFO = null;                 // GET /api/rules
  var RULES = null;                // {schema, optional: [{id}], custom: [...]}; the
                                   // mandatory rules are never part of it
  var REPORT = null;               // the last analysis' rules report
  var FILE = null;                 // {name, text}
  var OPTS = { bug: '', outcome: null };
  var CUR = null;                  // the prepared trajectory
  var seq = 0;                     // request counter: only the latest answer is shown

  /* ---------------------------------------------------------------- storage (best effort) */
  function load(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
  function save(key, v) { try { localStorage.setItem(key, v); } catch (e) { /* blocked */ } }

  /* ---------------------------------------------------------------- server */
  function api(path, body) {
    return fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {})
      .then(function (r) {
        return r.json().catch(function () { return { error: 'the server answered ' + r.status }; }).then(function (j) {
          if (!r.ok || j.error) throw Object.assign(new Error(j.error || ('HTTP ' + r.status)), { server: true });
          return j;
        });
      });
  }
  function offline() {
    $('#offline').hidden = false;
    $('#drop').hidden = true;
    $('#rules').hidden = true;
  }
  function start() {
    if (location.protocol === 'file:') { offline(); return; }
    api('/api/rules').then(function (info) {
      INFO = info;
      RULES = restore();
      renderRules();
      setOpen(load(OPEN) === '1');
    }).catch(offline);
  }
  function restore() {
    var s = null;
    try { s = JSON.parse(load(STORE) || 'null'); } catch (e) { /* a broken store: the defaults */ }
    try { return fromFile(s || {}); } catch (e) { return JSON.parse(JSON.stringify(INFO.default)); }
  }
  /* a rule set as saved or imported: its optional rules (ids of INFO.optional; the mandatory
   * ones an older file lists are always applied anyway) and its custom rules */
  function fromFile(obj) {
    var d = JSON.parse(JSON.stringify(INFO.default)), known = {}, fixed = {};
    INFO.optional.forEach(function (o) { known[o.id] = o; });
    INFO.mandatory.forEach(function (o) { fixed[o.id] = o; });
    if (obj.settings && (obj.settings.keep_attempts === false || obj.settings.smoothing === false)) throw new Error('G4 and G7 are mandatory rules and cannot be switched off');
    if (Array.isArray(obj.optional)) {
      d.optional = obj.optional.map(function (o) { return typeof o === 'string' ? o : o && o.id; })
        .filter(function (id) { return known[id]; }).map(function (id) { return { id: id }; });
    }
    if (Array.isArray(obj.custom)) {
      d.custom = obj.custom.filter(function (r) { return r && r.kind && r.match && !known[r.id] && !fixed[r.id]; })
        .map(function (r, n) { return Object.assign({ id: 'R' + (n + 1), field: 'target', enabled: true }, r); });
    }
    return d;
  }
  function persist() { save(STORE, JSON.stringify({ schema: RULES.schema, optional: RULES.optional, custom: RULES.custom })); }

  /* ---------------------------------------------------------------- file in */
  var drop = $('#drop'), input = $('#file');
  drop.addEventListener('click', function () { input.click(); });
  drop.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
  $('#replace').addEventListener('click', function () { input.click(); });
  input.addEventListener('change', function () { if (input.files[0]) readFile(input.files[0]); input.value = ''; });
  ['dragenter', 'dragover'].forEach(function (k) {
    document.addEventListener(k, function (e) { if (INFO) { e.preventDefault(); document.body.classList.add('dragging'); } });
  });
  ['dragleave', 'drop'].forEach(function (k) {
    document.addEventListener(k, function (e) {
      if (k === 'dragleave' && e.relatedTarget) return;
      document.body.classList.remove('dragging');
      if (k === 'drop' && INFO) {
        e.preventDefault();
        var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
        if (f) readFile(f);
      }
    });
  });
  function readFile(f) {
    if (INFO && f.size > INFO.max_bytes) { showError(f.name + ' is larger than ' + Math.round(INFO.max_bytes / 1048576) + ' MB.'); return; }
    busy('Reading ' + f.name + '…');
    f.text().then(function (text) {
      FILE = { name: f.name, text: text };
      OPTS.bug = '';                                   // a new log: infer its bug again
      $('#bug').value = '';
      analyze(true);
    }, function () { busy(false); showError('The file could not be read.'); });
  }

  /* ---------------------------------------------------------------- analysis */
  var timer = 0;
  function reanalyze() {
    persist();
    renderRules();
    if (!FILE) return;
    clearTimeout(timer);
    timer = setTimeout(function () { analyze(false); }, 300);
  }
  function analyze(fresh) {
    var my = ++seq;
    busy(fresh ? 'Analysing ' + FILE.name + '…' : 'Applying the rules…');
    state('analysing…', '');
    api('/api/analyze', { name: FILE.name, text: FILE.text, rules: RULES, bug: OPTS.bug || null, outcome: OPTS.outcome })
      .then(function (res) { if (my === seq) show(res, fresh); })
      .catch(function (err) {
        if (my !== seq) return;
        busy(false);
        if (!err.server) { offline(); return; }
        state('not applied', 'bad');
        showError(err.message);
      });
  }
  function show(res, fresh) {
    busy(false);
    $('#err').hidden = true;
    REPORT = res.rules;
    TV.vocab = res.vocab || {};
    var keepI = !fresh && CUR ? S.i : 0;
    var t = TV.prepTraj(res.trajectory);
    var byIndex = {};
    t.actions.forEach(function (a) { a.rules = []; byIndex[a.i] = a; });
    (REPORT.optional || []).concat(REPORT.custom || []).forEach(function (r) {
      (r.matched || []).forEach(function (i) { if (byIndex[i]) byIndex[i].rules.push({ id: r.id, sentence: r.sentence }); });
    });
    CUR = t;
    S.t = t.key;
    S.expanded = {};
    S.i = keepI ? TV.clamp(keepI, 1, t.n) : 0;
    if (!S.i) S.panel = false;
    var src = res.source || {};
    if (!OPTS.bug && src.bug) $('#bug').value = src.bug;
    $('#bug').placeholder = src.bug ? src.bug : 'id';
    $('#fname').textContent = src.name || FILE.name;
    $('#fmeta').innerHTML = TV.agentHTML(src.agent || t.agent) + (src.model ? '<span class="model mono">' + esc(src.model) + '</span>' : '') +
      '<span class="muted">' + esc({ atif: 'ATIF file', claude_agent_sdk_repr: 'Claude Agent SDK dump', claude_code_stream_json: 'Claude Code JSON log', codex_rollout_jsonl: 'Codex CLI log', qwen_stream_json: 'Qwen Code log' }[src.format] || src.format || '') + '</span>' +
      (src.bug ? '<span class="muted">bug-' + esc(src.bug) + (src.bug_inferred ? ' (found in the log)' : '') + '</span>' : '');
    document.title = (src.name || 'Analyze') + ' · TrajecTiers';
    $('#drop').hidden = true;
    $('#filebar').hidden = false;
    $('#result').hidden = false;
    document.body.classList.add('has-result');
    $('#notes').innerHTML = (res.warnings || []).map(function (w) { return '<p class="note">' + esc(w) + '</p>'; }).join('');
    renderSummary();
    renderRules();
    state(appliedText(), 'ok');
    setView(S.view, true);
    syncPanel();
    updateCursorUI();
    measureSticky();
  }
  function appliedText() {
    var ran = (REPORT.optional || []).filter(function (r) { return r.matched; })
      .concat((REPORT.custom || []).filter(function (r) { return r.enabled; }));
    var changed = ran.reduce(function (s, r) { return s + r.matched.length; }, 0);
    return ran.length ? 'applied · matching rules changed ' + TV.plural(changed, 'action') : 'applied';
  }
  function busy(text) {
    var b = $('#busy');
    if (!text) { b.hidden = true; return; }
    $('#busyText').textContent = text;
    b.hidden = false;
  }
  function showError(msg) {
    var e = $('#err');
    e.innerHTML = '<b>Could not analyse the log.</b> ' + esc(msg);
    e.hidden = false;
  }
  function state(text, cls) {
    var el = $('#rulesState');
    el.textContent = text;
    el.className = 'rules-state' + (cls ? ' ' + cls : '');
  }

  /* bug id and harness outcome: the analysis' inputs besides the rules */
  var bugTimer = 0;
  $('#bug').addEventListener('input', function () {
    clearTimeout(bugTimer);
    var v = this.value.replace(/^bug-/, '').trim();
    bugTimer = setTimeout(function () { OPTS.bug = v; if (FILE) analyze(false); }, 600);
  });
  $('#outcomeSeg').addEventListener('click', function (e) {
    var b = e.target.closest('button[data-oc]');
    if (!b) return;
    OPTS.outcome = b.dataset.oc === 'pass' ? true : b.dataset.oc === 'fail' ? false : null;
    $$('#outcomeSeg button').forEach(function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
    if (FILE) analyze(false);
  });

  /* ---------------------------------------------------------------- summary */
  function renderSummary() {
    var t = CUR, m = t.metrics || {}, dur = t.stats.duration_s != null ? t.stats.duration_s : t.stats.reported_duration_s;
    function tile(label, value, tip) { return '<div class="tile"' + (tip ? ' data-tip="' + esc(tip) + '"' : '') + '><b>' + value + '</b><span>' + label + '</span></div>'; }
    var failedAtt = t.attempts.filter(function (a) { return a.outcome === 'failed'; }).length;
    var h = '<div class="tiles">' +
      tile('actions', t.n, TV.plural(t.n_steps || 0, 'agent step') + ' (LLM turns)') +
      tile('phases', t.phases.length, 'phase stretches; a phase may come back') +
      tile('subphases', t.subs.length, 'stretches of one phase with one outcome') +
      tile('repair attempts', t.attempts.length + (failedAtt ? '<small> · ' + failedAtt + ' failed</small>' : ''), 'edits of app code up to the run that checks them (G4)') +
      tile('first fix', t.anchor ? '#' + t.anchor : '–', t.anchor ? 'the first edit of app source' : 'the log never edits app source') +
      (dur != null ? tile('duration', TV.fmtDur(dur)) : '') + '</div>';
    var share = TV.PHASE_ORDER.map(function (p) { return [p, m[p + '_actions'] || 0]; }).filter(function (x) { return x[1]; });
    var tot = TV.sum(share.map(function (x) { return x[1]; })) || 1;
    h += '<div class="sumrow"><span class="pass-wrap">' + TV.passPill(t.outcome.pass) + '</span>' +
      '<span class="share" aria-label="actions per phase">' + share.map(function (x) {
        return '<span class="sh" data-tip="' + esc(x[0] + ': ' + TV.plural(x[1], 'action') + ' (' + Math.round(100 * x[1] / tot) + '%)') + '">' + TV.phaseChip(x[0]).replace('</span>', ' <b class="num">' + Math.round(100 * x[1] / tot) + '%</b></span>') + '</span>';
      }).join('') + '</span>' +
      '<span class="badges">' + TV.badgeHTML(t.badges, t.outcome.pass) + '</span></div>';
    $('#summary').innerHTML = h;
  }

  /* ---------------------------------------------------------------- rules card */
  function setOpen(open) {
    $('#rulesToggle').setAttribute('aria-expanded', open ? 'true' : 'false');
    $('#rulesToggle .caret').textContent = open ? '▾' : '▸';
    $('#rulesBody2').hidden = !open;
    save(OPEN, open ? '1' : '0');
  }
  $('#rulesToggle').addEventListener('click', function () { setOpen(this.getAttribute('aria-expanded') !== 'true'); });

  var LOCK = '<svg class="lockic" width="11" height="12" viewBox="0 0 11 12" aria-hidden="true"><rect x="1" y="5" width="9" height="6.5" rx="1.4" fill="currentColor"/><path d="M3 5V3.6a2.5 2.5 0 0 1 5 0V5" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>';
  function mandatoryRules() {
    return INFO.mandatory.map(function (r) {
      return '<li class="rule locked"><span class="rid">' + esc(r.id) + '</span><span class="rtext"><b>' + esc(r.title) + '.</b> ' + esc(r.sentence) + '</span>' +
        '<span class="fixed" data-tip="mandatory: always applied; it cannot be switched off or removed">' + LOCK + 'required</span></li>';
    }).join('');
  }
  /* the matched / skipped badges of a rule that ran (optional ready-made or custom) */
  function hitsHTML(x) {
    if (!x || !x.matched || !CUR) return '';
    var h = x.matched.length ? '<button type="button" class="hits" data-jump="' + x.matched[0] + '" data-tip="' + esc('actions ' + x.matched.map(function (i) { return '#' + i; }).join(', ') + ' · click: the first one') + '">' + TV.plural(x.matched.length, 'action') + '</button>' :
      '<span class="hits none" data-tip="no action of this log matches">no match</span>';
    if (x.skipped && x.skipped.length) h += '<span class="hits warn" data-tip="' + esc(x.skipped.map(function (s) { return '#' + s.i + ': ' + s.why; }).join(' · ')) + '">' + x.skipped.length + ' skipped</span>';
    return '<span class="hitrow">' + h + '</span>';
  }
  function added() {
    var on = {};
    RULES.optional.forEach(function (o) { on[o.id] = o; });
    return on;
  }
  /* the optional rules: one card each, "+ Add" or "Added · Remove" */
  function optionalRules() {
    var on = added(), rep = {};
    ((REPORT || {}).optional || []).forEach(function (r) { rep[r.id] = r; });
    return INFO.optional.map(function (r) {
      var is = !!on[r.id];
      return '<li class="rule opt' + (is ? ' added' : '') + '"><span class="rid">' + esc(r.id) + '</span><span class="rtext"><b>' + esc(r.title) + '.</b> ' + esc(r.sentence) + (is ? hitsHTML(rep[r.id]) : '') + '</span>' +
        '<span class="rbtns">' + (is ? '<span class="addedpill" aria-hidden="true">✓ Added</span><button type="button" class="btn ghost small" data-remove="' + r.id + '" aria-label="Remove rule ' + esc(r.id) + '">Remove</button>' :
          '<button type="button" class="btn small" data-add="' + r.id + '" aria-label="Add rule ' + esc(r.id) + '">+ Add</button>') + '</span></li>';
    }).join('');
  }
  function customRules() {
    if (!RULES.custom.length) return '<li class="empty muted">No custom rules yet. Build one here, or open an action of the trajectory and use <b>+ Rule from this action</b>.</li>';
    var rep = {};
    ((REPORT || {}).custom || []).forEach(function (r) { rep[r.id] = r; });
    return RULES.custom.map(function (r, k) {
      var on = r.enabled !== false, hits = on ? hitsHTML(rep[r.id]) : '';
      return '<li class="rule' + (on ? '' : ' off') + (FORM.editing === r.id ? ' editing' : '') + '" data-k="' + k + '"><span class="rid">' + esc(r.id) + '</span>' +
        '<span class="rtext">' + esc(TV.ruleSentence(r)) + hits + '</span>' +
        '<span class="rbtns"><label class="switch" title="' + (on ? 'Switch off' : 'Switch on') + '"><input type="checkbox" data-enable="' + k + '"' + (on ? ' checked' : '') + '><span aria-hidden="true"></span><span class="sr">enabled</span></label>' +
        '<button type="button" class="btn ghost icon small" data-edit="' + k + '" title="Edit" aria-label="Edit rule ' + esc(r.id) + '">✎</button>' +
        '<button type="button" class="btn ghost icon small" data-del="' + k + '" title="Delete" aria-label="Delete rule ' + esc(r.id) + '">✕</button></span></li>';
    }).join('');
  }
  function renderRules() {
    if (!INFO) return;
    $('#mandList').innerHTML = mandatoryRules();
    $('#optList').innerHTML = optionalRules();
    $('#customList').innerHTML = customRules();
    var mine = RULES.custom.filter(function (r) { return r.enabled !== false; }).length, n = RULES.optional.length;
    $('#optCount').textContent = n + ' of ' + INFO.optional.length + ' added';
    $('#rulesSum').innerHTML = INFO.mandatory.length + ' mandatory · ' + (n ? '<b>' + n + ' optional</b>' : 'no optional') +
      ' · ' + (mine ? '<b>' + mine + ' custom</b>' : 'no custom');
    $('#resetOptional').hidden = !n;
    renderForm();
  }
  $('#optList').addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.jump) { TV.setCursor(+b.dataset.jump); scrollToCur(); return; }
    if (b.dataset.remove) {
      RULES.optional = RULES.optional.filter(function (o) { return o.id !== b.dataset.remove; });
      reanalyze();
    } else if (b.dataset.add) {
      var order = INFO.optional.map(function (o) { return o.id; });
      RULES.optional.push({ id: b.dataset.add });
      RULES.optional.sort(function (x, y) { return order.indexOf(x.id) - order.indexOf(y.id); });
      reanalyze();
    }
  });
  $('#resetOptional').addEventListener('click', function () { RULES.optional = []; reanalyze(); });
  $('#customList').addEventListener('change', function (e) {
    var k = e.target.dataset.enable;
    if (k == null) return;
    RULES.custom[+k].enabled = e.target.checked;
    reanalyze();
  });
  $('#customList').addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.jump) { TV.setCursor(+b.dataset.jump); scrollToCur(); return; }
    if (b.dataset.del != null) {
      var gone = RULES.custom.splice(+b.dataset.del, 1)[0];
      if (gone && FORM.editing === gone.id) resetForm();
      reanalyze();
    } else if (b.dataset.edit != null) {
      var r = RULES.custom[+b.dataset.edit];
      FORM = { kind: r.kind, field: r.field || 'target', regex: !!r.regex, match: r.match, value: r.value, editing: r.id };
      renderRules();
      $('#rfMatch').focus();
    }
  });

  /* the rule builder: a sentence with its blanks as fields */
  var FORM = { kind: 'phase', field: 'target', regex: false, match: '', value: '', editing: null };
  function options(list, cur, labels) {
    return list.map(function (v) { return '<option value="' + esc(v) + '"' + (v === cur ? ' selected' : '') + '>' + esc((labels || {})[v] || v.replace(/_/g, ' ')) + '</option>'; }).join('');
  }
  function valuesFor(kind) {
    if (kind === 'category') return INFO.categories;
    if (kind === 'file_role') return INFO.file_roles;
    return INFO.phases.concat([INFO.follow]);
  }
  function renderForm() {
    if (!INFO) return;
    var f = FORM, vals = valuesFor(f.kind);
    if (vals.indexOf(f.value) < 0) f.value = vals[0];
    $$('#ruleForm [data-kind]').forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.kind === f.kind ? 'true' : 'false'); });
    var op = '<select id="rfOp" aria-label="How to match">' + options(['contains', 'regex'], f.regex ? 'regex' : 'contains', { contains: 'contains', regex: 'matches the regex' }) + '</select>';
    var match = '<input id="rfMatch" type="text" class="rf-match" value="' + esc(f.match) + '" placeholder="' + (f.kind === 'file_role' ? 'src/sharedTest/' : f.field === 'tool' ? 'update_plan' : './gradlew lint') + '" aria-label="Text to match" spellcheck="false">';
    var val = '<select id="rfValue" aria-label="Value">' + options(vals, f.value, { follow: 'the phase of the work around them' }) + '</select>';
    var h;
    if (f.kind === 'file_role') h = '<span>Files whose path</span>' + op + match + '<span>are</span>' + val + '<span>files.</span>';
    else {
      h = '<span>Actions whose</span><select id="rfField" aria-label="What to match">' + options(INFO.fields, f.field, { target: 'command or target', tool: 'tool name', any: 'tool, command or target' }) + '</select>' +
        op + match + '<span>' + (f.kind === 'category' ? 'count as' : 'belong to') + '</span>' + val + '<span>.</span>';
    }
    var focused = document.activeElement && document.activeElement.id;
    var pos = focused === 'rfMatch' ? document.activeElement.selectionStart : null;
    $('#rfSentence').innerHTML = h;
    if (focused && $('#' + focused)) { $('#' + focused).focus(); if (pos != null) try { $('#rfMatch').setSelectionRange(pos, pos); } catch (e) { /* ignore */ } }
    $('#rfAdd').textContent = f.editing ? 'Save ' + f.editing : 'Add rule';
    $('#rfCancel').hidden = !f.editing;
  }
  function resetForm() { FORM = { kind: FORM.kind, field: 'target', regex: false, match: '', value: '', editing: null }; $('#rfErr').textContent = ''; }
  $('#ruleForm').addEventListener('click', function (e) {
    var b = e.target.closest('[data-kind]');
    if (b) { FORM.kind = b.dataset.kind; FORM.value = ''; renderForm(); }
  });
  $('#ruleForm').addEventListener('input', function (e) {
    var id = e.target.id;
    if (id === 'rfMatch') FORM.match = e.target.value;
    $('#rfErr').textContent = '';
  });
  $('#ruleForm').addEventListener('change', function (e) {
    var id = e.target.id, v = e.target.value;
    if (id === 'rfField') FORM.field = v;
    else if (id === 'rfOp') FORM.regex = v === 'regex';
    else if (id === 'rfValue') FORM.value = v;
    else return;
    renderForm();
  });
  $('#rfCancel').addEventListener('click', function () { resetForm(); renderRules(); });
  $('#ruleForm').addEventListener('submit', function (e) {
    e.preventDefault();
    var f = FORM, m = (f.match || '').trim();
    if (!m) { $('#rfErr').textContent = 'Type the text to match.'; $('#rfMatch').focus(); return; }
    if (f.regex) { try { new RegExp(m); } catch (err) { $('#rfErr').textContent = 'Not a valid regular expression.'; return; } }
    var rule = { kind: f.kind, field: f.kind === 'file_role' ? 'path' : f.field, match: m, regex: f.regex, value: f.value, enabled: true };
    if (f.editing) {
      var k = RULES.custom.map(function (r) { return r.id; }).indexOf(f.editing);
      rule.id = f.editing;
      rule.enabled = k >= 0 ? RULES.custom[k].enabled !== false : true;
      if (k >= 0) RULES.custom[k] = rule; else RULES.custom.push(rule);
    } else {
      rule.id = nextId();
      RULES.custom.push(rule);
    }
    resetForm();
    reanalyze();
  });
  function nextId() {
    var used = {};
    RULES.custom.forEach(function (r) { used[r.id] = 1; });
    for (var n = 1; ; n++) if (!used['R' + n]) return 'R' + n;
  }

  /* start a rule from an action: its command head (or file name, or tool) and its phase */
  function suggest(a) {
    var tgt = (a.cmd || a.target || '').trim();
    if (!tgt) return { field: 'tool', match: a.tool };
    if (/^[^\s]+\.[A-Za-z0-9]{1,6}$/.test(tgt)) return { field: 'target', match: tgt.split('/').pop() };
    var parts = tgt.split(/\s*(?:&&|\|\||;|\|)\s*/).filter(function (p) { return p && !/^(cd|export|set|source)\b/.test(p); });
    var words = (parts[0] || tgt).split(/\s+/).filter(function (w) { return w && !/^\d+>/.test(w); });
    return { field: 'target', match: words.slice(0, words[0] && /^(\.\/)?(gradlew|git|adb|python3?|npm|mvn)$/.test(words[0].split('/').pop()) ? 2 : 1).join(' ') };
  }
  TV.ruleFromAction = function (i) {
    var a = CUR && CUR.actions[i - 1];
    if (!a) return;
    var s = suggest(a);
    FORM = { kind: 'phase', field: s.field, regex: false, match: s.match, value: a.phase, editing: null };
    setOpen(true);
    renderRules();
    $('#rules').scrollIntoView({ block: 'start', behavior: 'smooth' });
    setTimeout(function () { var m = $('#rfMatch'); if (m) { m.focus(); m.select(); } }, 250);
  };

  /* export / import (the same JSON the CLI's --rules reads) */
  $('#exportRules').addEventListener('click', function () {
    var blob = new Blob([JSON.stringify({ schema: RULES.schema, optional: RULES.optional, custom: RULES.custom }, null, 2) + '\n'], { type: 'application/json' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'rules.json';
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  });
  $('#importRules').addEventListener('click', function () { $('#importFile').click(); });
  $('#importFile').addEventListener('change', function () {
    var f = this.files[0];
    this.value = '';
    if (!f) return;
    f.text().then(function (text) {
      var obj = JSON.parse(text);
      if (!obj || typeof obj !== 'object' || (!obj.optional && !obj.settings && !obj.custom)) throw new Error('not a rules file');
      RULES = fromFile(obj);
      resetForm();
      setOpen(true);
      reanalyze();
    }).catch(function (err) { state('import failed: ' + err.message, 'bad'); });
  });

  /* ---------------------------------------------------------------- the views' shell */
  TV.traj = function () { return CUR; };
  TV.applyLevel = function (t, level) {
    var e = S.expanded[t.id] || (S.expanded[t.id] = { p: {}, s: {} });
    e.p = {}; e.s = {};
    if (level === 'subphases' || level === 'steps') t.phases.forEach(function (p) { e.p[p.id] = 1; });
    if (level === 'steps') t.subs.forEach(function (s) { e.s[s.id] = 1; });
  };
  TV.exp = function (t) {
    t = t || CUR;
    var e = S.expanded[t.id];
    if (!e) { e = S.expanded[t.id] = { p: {}, s: {} }; TV.applyLevel(t, S.level); }
    return e;
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
  TV.select = function () { /* one trajectory only */ };
  function scrollToCur() {
    setTimeout(function () { var n = $('#view .cur'); if (n) n.scrollIntoView({ block: 'center', behavior: 'smooth' }); }, 30);
  }
  function setView(v, force) {
    if (VIEWS.indexOf(v) < 0) v = 'trajectory';
    var changed = v !== S.view;
    S.view = v;
    $$('.tabs [data-view]').forEach(function (b) { b.setAttribute('aria-selected', b.dataset.view === v ? 'true' : 'false'); });
    if (changed || force) render();
  }
  function tabCtl() {
    var h = '';
    if (S.view === 'trajectory') {
      h = '<span class="seg small" role="group" aria-label="Level">' + [['phases', 'Phases'], ['subphases', '+ Subphases'], ['steps', '+ Steps']].map(function (x) {
        return '<button type="button" data-level="' + x[0] + '" aria-pressed="' + (S.level === x[0]) + '">' + x[1] + '</button>';
      }).join('') + '</span>';
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
    resizeTimer = setTimeout(function () { measureSticky(); relayout(); }, 120);
  });
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
        (a.verdict !== 'none' ? ' <span class="vg v-' + a.verdict + '">' + TV.VERDICT_GLYPH[a.verdict] + '</span>' : '') +
        (a.sub ? ' <span class="opill mini o-' + a.sub.outcome + '"><b aria-hidden="true">' + TV.OUTCOME_GLYPH[a.sub.outcome] + '</b><span class="ell">' + esc(a.sub.p.phase) + '</span></span>' : '')
      : '<b>#–</b><span class="muted">/' + t.n + ' · press ▶ or j</span>';
  }

  /* ---------------------------------------------------------------- details panel */
  function syncPanel() {
    var want = !!(CUR && S.i && S.panel);
    var was = document.body.classList.contains('panel-open');
    document.body.classList.toggle('panel-open', want);
    if (want) renderPanel();
    if (want !== was) setTimeout(relayout, 180);
  }
  function closePanel() { S.panel = false; syncPanel(); }
  TV.closePanel = closePanel;
  function renderPanel() {
    var t = CUR, a = t.actions[S.i - 1];
    if (!a) return;
    $('#dtI').textContent = '#' + a.i;
    $('#dtOf').textContent = 'of ' + t.n + ' · ' + t.agent;
    $('#dtPrev').disabled = a.i <= 1;
    $('#dtNext').disabled = a.i >= t.n;
    $('#dtBody').innerHTML = '<div class="dt-acts"><button type="button" class="btn small" id="dtRule" title="Start a rule that matches actions like this one">+ Rule from this action</button></div>' +
      TV.actionDetailsHTML(t, a);
    $('#dtBody').scrollTop = 0;
  }
  $('#dtBody').addEventListener('click', function (e) { if (e.target.closest('#dtRule')) TV.ruleFromAction(S.i); });
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
    else if (k === '1' || k === '2') setView(VIEWS[+k - 1]);
  });

  setTimeout(function () { document.body.classList.remove('preload'); }, 400);
  start();
})();
