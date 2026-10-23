/* Inceptor, a trace exploration dashboard - shared core of every page (index, bug, analyze,
 * tables): helpers, vocabularies and labels (phases, phase outcomes, categories, verdicts),
 * search, the user's lookup-table rows (TV.ruleset), theme, tooltip, trajectory preparation
 * (trajview/3), small HTML snippets. Plain script (no modules, no fetch) so that the corpus
 * pages work from file://. */
(function () {
  'use strict';
  var TV = (window.TV = window.TV || {});
  TV.views = TV.views || {};

  /* ------------------------------------------------------------------ helpers */
  var ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  TV.esc = function (s) {
    return s == null ? '' : String(s).replace(/[&<>"']/g, function (c) { return ESC[c]; });
  };
  TV.$ = function (sel, root) { return (root || document).querySelector(sel); };
  TV.$$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
  TV.pct = function (x) { return x == null || isNaN(x) ? '–' : Math.round(x * 100) + '%'; };
  TV.fmtDur = function (s) {
    if (s == null || isNaN(s)) return '–';
    s = Math.round(s);
    if (s < 60) return s + 's';
    var m = Math.floor(s / 60), r = s % 60;
    if (m < 60) return m + 'm' + (r ? ' ' + r + 's' : '');
    return Math.floor(m / 60) + 'h ' + (m % 60) + 'm';
  };
  TV.median = function (xs) {
    var a = xs.filter(function (x) { return x != null && !isNaN(x); }).sort(function (p, q) { return p - q; });
    if (!a.length) return null;
    var h = Math.floor(a.length / 2);
    return a.length % 2 ? a[h] : (a[h - 1] + a[h]) / 2;
  };
  TV.sum = function (xs) { return xs.reduce(function (s, x) { return s + (x || 0); }, 0); };
  TV.humanize = function (s) { return s == null ? '' : String(s).replace(/_/g, ' '); };
  TV.clamp = function (x, lo, hi) { return Math.max(lo, Math.min(hi, x)); };
  TV.plural = function (n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); };
  TV.bugSort = function (a, b) { var x = +a, y = +b; return (isNaN(x) || isNaN(y)) ? String(a).localeCompare(b) : x - y; };
  /* a bug's key, as the corpus keys it: "bug-1130", "bug_1130" and "1130" are one bug; any
   * other name (an instance id) is kept as it is. '' when there is none. */
  TV.bugKey = function (x) {
    var s = x == null ? '' : String(x).trim(), m = /^bug[-_ ]?(.+)$/i.exec(s);
    return m ? m[1] : s;
  };
  /* a bug key in words: bug-<n> for a number, else the name itself */
  TV.bugName = function (key) { return /^\d+$/.test(String(key)) ? 'bug-' + key : String(key); };
  /* an agent's column: a name that matches a known one up to case, spaces and dashes, or that
   * adds "code" / "cli" to it ("Claude Code", "codex-cli"), is that agent; any other name is
   * kept as it is (trimmed) and gets a column of its own */
  TV.agentKey = function (x) { return String(x == null ? '' : x).toLowerCase().replace(/[^a-z0-9]/g, ''); };
  TV.normAgent = function (name, known) {
    var s = String(name == null ? '' : name).trim(), k = TV.agentKey(s);
    if (!k) return '';
    var list = TV.AGENT_ORDER.concat(TV.OTHER_AGENTS, known || []);
    for (var i = 0; i < list.length; i++) {
      var c = TV.agentKey(list[i]);
      if (k === c || k === c + 'code' || k === c + 'cli') return list[i];
    }
    return s;
  };

  /* hash <-> object: "a=1&b=two" */
  TV.readHash = function () {
    var q = {};
    (location.hash || '').replace(/^#/, '').split('&').forEach(function (kv) {
      if (!kv) return;
      var p = kv.split('=');
      try { q[decodeURIComponent(p[0])] = decodeURIComponent(p.slice(1).join('=') || ''); } catch (e) { /* bad escape */ }
    });
    return q;
  };
  TV.writeHash = function (obj) {
    var h = Object.keys(obj).filter(function (k) { return obj[k] != null && obj[k] !== ''; })
      .map(function (k) { return k + '=' + encodeURIComponent(obj[k]); }).join('&');
    try { history.replaceState(null, '', '#' + h); } catch (e) { location.hash = h; }
  };

  /* ------------------------------------------------------------------ vocabularies + labels */
  /* The pages set TV.vocab from their data file (vocab of trajview/3); vocab.text carries the
   * codebook's own words (atif/codebook.py), which the tooltips quote. */
  TV.vocab = {};
  TV.AGENT_ORDER = ['claude', 'codex', 'qwen'];
  TV.OTHER_AGENTS = ['swe-agent', 'openhands', 'mini-swe-agent'];   // the other agents the engine reads (atif/detect.py)
  TV.PHASE_ORDER = ['planning', 'localization', 'repair', 'validation'];
  /* what the outcome band shows per phase: Validation a verdict (its check: a build or test);
   * Localization and Repair their files as dots (no verdict can be read from them); Planning
   * nothing */
  TV.VERDICT_PHASES = ['validation'];
  TV.hasVerdict = function (p) { return TV.VERDICT_PHASES.indexOf(p) >= 0; };
  TV.hasFiles = function (p) { return p === 'localization' || p === 'repair'; };
  TV.phaseVar = function (p) { return 'var(--p-' + (TV.PHASE_ORDER.indexOf(p) >= 0 ? p : 'other') + ')'; };
  TV.phaseTextVar = function (p) { return 'var(--pt-' + (TV.PHASE_ORDER.indexOf(p) >= 0 ? p : 'other') + ')'; };
  TV.phaseDef = function (p) {
    var x = ((TV.vocab.text || {}).phases || {})[p];
    return x ? p + ': ' + x.doing + ' (' + x.where + ')' : p;
  };
  /* Two validations, kept apart in every label:
   *  - self-validation: what the agent's own builds, compilations and tests showed. Each such
   *    action is passed (a build, compilation or test passed), errored (it failed, or the
   *    environment stopped it) or executed (it ran, but its output shows no such result: an
   *    exit code 0 alone is not a pass). The Validation phase's outcome is the same reading
   *    over its runs: passed, errored or unchecked (no build, compilation or test result).
   *  - external validation: the benchmark's own verdict on the final patch (the outcome file
   *    of an upload), never the agent's.
   * The engine's outcomes (atif/phase.py OUTCOMES) are folded into the dashboard's three:
   * succeeded -> passed, failed and blocked -> errored. A phase whose checks changed (errored,
   * then passed) has an outcome history; the data keeps each stretch as a subphase. */
  TV.OUTCOMES = ['passed', 'errored', 'unchecked'];
  var OUTCOME_FOLD = { succeeded: 'passed', failed: 'errored', blocked: 'errored' };
  TV.OUTCOME_LABEL = {
    passed: 'passed: a build, compilation or test the agent ran passed',
    errored: 'errored: a build, compilation or test the agent ran failed, or the environment stopped it',
    unchecked: 'unchecked: the agent ran no build, compilation or test with a readable result'
  };
  TV.outcomeOf = function (o) { o = OUTCOME_FOLD[o] || o; return TV.OUTCOMES.indexOf(o) >= 0 ? o : 'unchecked'; };
  TV.outcomeVar = function (o) { return { passed: 'var(--sv-pass)', errored: 'var(--sv-err)' }[TV.outcomeOf(o)] || 'var(--o-unchecked)'; };
  /* the meaning of a Validation outcome (the only phase with one) */
  TV.outcomeDef = function (phase, o) { return (phase ? phase + ' ' : '') + (TV.OUTCOME_LABEL[TV.outcomeOf(o)] || o); };
  TV.EVIDENCE = ['test', 'build', 'target_file', 'none'];
  TV.EVIDENCE_LABEL = { test: 'a test run', build: 'a build', target_file: 'the files of the agent\'s patch', none: 'no check' };
  TV.EVIDENCE_SHORT = { test: 'test', build: 'build', target_file: 'patch files', none: '' };
  /* an action's self-check (atif/verdict.py: pass | fail | none) in the dashboard's words, and
   * its mark: a dot coloured like the action dots of the Fingerprint and Comparison tabs (the
   * square box belongs to the external validation alone). */
  TV.verdictDot = function (v) { return '<i class="vdot v-' + (v || 'none') + '" aria-hidden="true"></i>'; };
  TV.VERDICT_WORD = { pass: 'passed', fail: 'errored', none: 'executed' };
  TV.VERDICT_LABEL = {
    pass: 'passed: its output shows a build, compilation or test that passed',
    fail: 'errored: its output shows a build, compilation or test that failed, or an error that stopped it',
    none: 'executed: it ran, but its output shows no build, compilation or test result (an exit code 0 alone is not a pass)'
  };
  /* the action legend: passed / errored / executed, with the mark each view draws (cls) */
  TV.verdictLegend = function (mark) {
    return ['pass', 'fail', 'none'].map(function (v) {
      return '<span class="lgm" data-tip="' + TV.esc(TV.VERDICT_LABEL[v]) + '"><i class="' + mark + ' v-' + v + '"></i>' + TV.VERDICT_WORD[v] + '</span>';
    }).join('');
  };
  /* action categories (the action table of the Final lookup tables, atif/lookup.py), in table
   * order, with two-letter abbreviations */
  TV.CATEGORIES = ['search', 'read', 'orient', 'edit', 'build', 'test', 'diff', 'vcs', 'plan', 'sub-agent', 'other'];
  TV.CAT_ABBR = { search: 'sr', read: 'rd', orient: 'or', edit: 'ed', build: 'bd', test: 'ts', diff: 'df', vcs: 'vc', plan: 'pl',
    'sub-agent': 'sa', other: 'ot' };
  TV.catAbbr = function (c) { return TV.CAT_ABBR[c] || String(c || '?').slice(0, 2); };
  TV.catDef = function (c) {
    var x = ((TV.vocab.text || {}).categories || {})[c];
    return x ? c + ': ' + x.does + (x.tools ? ' · ' + x.tools : '') : c;
  };
  /* the category lanes of a set of trajectories: vocabulary order, then any unknown ones */
  TV.lanes = function (trajs) {
    var used = {};
    trajs.forEach(function (t) { t.actions.forEach(function (a) { used[a.category] = 1; }); });
    var order = TV.vocab.categories || TV.CATEGORIES;
    var lanes = order.filter(function (c) { return used[c]; });
    Object.keys(used).forEach(function (c) { if (lanes.indexOf(c) < 0) lanes.push(c); });
    return lanes;
  };
  /* ------------------------------------------------------------------ snippets */
  TV.agentHTML = function (a, extra) {
    return '<span class="agent"><i class="adot ' + TV.esc(a) + '" aria-hidden="true"></i>' + TV.esc(a) + (extra || '') + '</span>';
  };
  TV.oc = function (pass) { return pass === true ? 'pass' : pass === false ? 'fail' : 'unknown'; };
  /* the external validation's one mark: a box, green = passed, red = failed, grey outline =
   * unknown (no other label in the dashboard is a square box) */
  TV.extBox = function (pass) { return '<i class="xbox ' + TV.oc(pass) + '" aria-hidden="true"></i>'; };
  TV.markHTML = function (pass, tip) {
    var oc = TV.oc(pass);
    return '<span class="xbox ' + oc + '"' + (tip ? ' data-tip="' + TV.esc(tip) + '"' : '') + ' role="img" aria-label="external validation ' + TV.EXTERNAL_WORD[oc] + '"></span>';
  };
  TV.EXTERNAL_DEF = 'External validation: the benchmark\'s own verdict on the agent\'s final patch (it builds the patched app and runs the bug\'s tests), not the agent\'s';
  TV.EXTERNAL_WORD = { pass: 'passed', fail: 'failed', unknown: 'unknown' };
  TV.passPill = function (pass) {
    var oc = TV.oc(pass);
    return '<span class="tpill ' + oc + '" data-tip="' + TV.esc(TV.EXTERNAL_DEF) + '">' +
      TV.extBox(pass) + TV.EXTERNAL_WORD[oc] + '</span>';
  };
  /* the legend row of the external validation: its pills, or (marks) its boxes, one per run */
  TV.externalLegendRow = function (marks) {
    return ['External validation', marks ? 'by the benchmark · a box per run' : 'by the benchmark',
      [true, false, null].map(function (p) {
        return marks ? '<span class="lgm" data-tip="' + TV.esc(TV.EXTERNAL_DEF) + '">' + TV.markHTML(p) + TV.EXTERNAL_WORD[TV.oc(p)] + '</span>' : TV.passPill(p);
      }).join('')];
  };
  /* strips: pieces placed by action index (left / width in % of n), so a phase strip and the
   * phase-outcome strip under it line up exactly; a 1px surface gap separates pieces */
  function piece(p, n, style, cls, tip) {
    var len = p[2] - p[1] + 1;
    return '<i' + (cls ? ' class="' + cls + '"' : '') + ' style="left:' + (100 * (p[1] - 1) / n).toFixed(3) + '%;width:max(1px, calc(' + (100 * len / n).toFixed(3) + '% - 1px))' +
      (style ? ';' + style : '') + '" data-tip="' + TV.esc(tip + ' · #' + p[1] + '–#' + p[2] + ' (' + TV.plural(len, 'action') + ')') + '"></i>';
  }
  function stripN(strip, n) { return n || (strip && strip.length ? strip[strip.length - 1][2] : 1) || 1; }
  /* phase strip from [[phase, start, end], ...]; width = share of a reference length */
  TV.stripHTML = function (strip, n, ref, cls) {
    var w = ref ? Math.max(2, 100 * n / ref) : 100, N = stripN(strip, n);
    return '<span class="strip' + (cls ? ' ' + cls : '') + '" style="width:' + w.toFixed(1) + '%">' + (strip || []).map(function (p) {
      return piece(p, N, 'background:' + TV.phaseVar(p[0]), '', p[0]);
    }).join('') + '</span>';
  };
  /* phase-outcome strip from [[outcome, start, end, phase, evidence], ...] (sub_strip: one piece per outcome) */
  TV.subStripHTML = function (subStrip, n, ref, cls) {
    var w = ref ? Math.max(2, 100 * n / ref) : 100, N = stripN(subStrip, n);
    return '<span class="strip outs' + (cls ? ' ' + cls : '') + '" style="width:' + w.toFixed(1) + '%">' + (subStrip || []).filter(function (p) {
      return !p[3] || TV.hasVerdict(p[3]);                // only Validation has a verdict
    }).map(function (p) {
      var o = TV.outcomeOf(p[0]), ev = TV.EVIDENCE_SHORT[p[4]];
      return piece(p, N, '', 'o-' + o, 'self-validation · ' + (p[3] ? p[3] + ' · ' : '') + o + (ev ? ' (' + ev + ')' : ''));
    }).join('') + '</span>';
  };
  /* phase strip with the phase-outcome strip under it, both scaled to n / ref */
  TV.stripsHTML = function (strip, subStrip, n, ref) {
    var w = ref ? Math.max(2, 100 * n / ref) : 100;
    if (!subStrip || !subStrip.length) return TV.stripHTML(strip, n, ref, 'tall');
    return '<span class="strips" style="width:' + w.toFixed(1) + '%">' + TV.stripHTML(strip, n, 0, 'tall') + TV.subStripHTML(subStrip, n, 0) + '</span>';
  };
  TV.phaseChip = function (p) {
    return '<span class="pchip" data-tip="' + TV.esc(TV.phaseDef(p)) + '"><i style="background:' + TV.phaseVar(p) + '"></i>' + TV.esc(p) + '</span>';
  };
  /* outcome pill; phase = give the codebook's meaning in that phase, ev = the evidence, cls = extra classes */
  TV.outcomePill = function (o, text, phase, ev, cls) {
    o = TV.outcomeOf(o);
    var evs = ev && TV.EVIDENCE_SHORT[ev];
    return '<span class="opill o-' + o + (cls ? ' ' + cls : '') + '" data-tip="' + TV.esc(phase ? TV.outcomeDef(phase, o) : TV.OUTCOME_LABEL[o]) +
      (evs ? TV.esc(' · evidence: ' + TV.EVIDENCE_LABEL[ev]) : '') + '">' + TV.esc(text != null ? text : o) + (evs ? '<span class="ev"> · ' + TV.esc(evs) + '</span>' : '') + '</span>';
  };
  TV.phaseLegend = function (used) {
    return TV.PHASE_ORDER.filter(function (p) { return !used || used[p]; }).map(TV.phaseChip).join('');
  };
  /* legend chips: the same solid fills the strips and bars use; used = {outcome: 1} limits them */
  TV.outcomeLegend = function (used) {
    return TV.OUTCOMES.filter(function (o) { return !used || used[o]; }).map(function (o) { return TV.outcomePill(o); }).join('');
  };

  /* ------------------------------------------------------------------ search */
  /* a bug matches a query that names it ("8", "bug8", "bug-8") exactly, never by a prefix
   * (bug-81) or a digit inside the id; any other query is looked up in its texts (app, file
   * name, agent). "bug" or "bug-" alone matches everything. */
  TV.queryMatch = function (q, bug, texts) {
    q = String(q || '').trim().toLowerCase();
    if (!q || /^bug[-_ ]?$/.test(q)) return true;
    var m = /^(?:bug[-_ ]?)?(\d+)$/.exec(q);
    if (m) return bug != null && String(bug).replace(/^bug-/, '') === m[1];
    return (texts || []).some(function (x) { return x != null && String(x).toLowerCase().indexOf(q) >= 0; });
  };

  /* ------------------------------------------------------------------ the table file (atif/rules.py) */
  /* One set of lookup-table rows for the whole viewer, kept in localStorage ('tv-rules') and
   * edited on tables.html: every page analyses every trajectory with the codebook's tables
   * plus these rows (the corpus pages re-run the corpus packs, the uploads are re-analysed).
   * Default = no ready-made row added and no row of the user's switched on, which is the
   * corpus data as exported. The engine checks the file again (rules.normalize), so this only
   * keeps its shape. TABLES_VERSION is part of every cache key: results computed by an
   * earlier engine are never reused (t1: codebook version 4; t2: + verdict lines, deciding
   * actions, unrecognised steps, shell-tool rows; t3: the Final lookup tables; t4: an exit
   * code 0 alone is no pass). */
  var RULES_KEY = 'tv-rules', TABLES_VERSION = 't4';
  /* ready-made rows (O1-O4) are no longer offered: the built-in tables cover them, so a
   * file that still lists some keeps only its own rows */
  function cleanRules(rs) {
    rs = rs && typeof rs === 'object' ? rs : {};
    return {
      schema: 'trajectiers-tables/1',
      optional: [],
      custom: (Array.isArray(rs.custom) ? rs.custom : []).filter(function (r) { return r && r.kind && r.match; }).map(function (r, n) {
        return { id: r.id || 'R' + (n + 1), kind: r.kind, field: r.kind === 'file_role' ? 'path' : r.kind === 'shell_tool' ? 'tool' : (r.field || 'target'),
          match: String(r.match), regex: !!r.regex, value: r.value, enabled: r.enabled !== false };
      })
    };
  }
  function activeRules(rs) {
    return { optional: rs.optional.map(function (o) { return o.id; }),
      custom: rs.custom.filter(function (r) { return r.enabled; }).map(function (r) { return [r.id, r.kind, r.field, r.match, r.regex, r.value]; }) };
  }
  function hashText(s) {                     // FNV-1a, 32 bit: a short cache key
    var h = 0x811c9dc5;
    for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
    return ('0000000' + h.toString(16)).slice(-8);
  }
  TV.ruleset = {
    get: function () {
      var raw = null;
      try { raw = JSON.parse(localStorage.getItem(RULES_KEY) || 'null'); } catch (e) { /* blocked or broken: the defaults */ }
      return cleanRules(raw);
    },
    save: function (rs) {
      rs = cleanRules(rs);
      try { localStorage.setItem(RULES_KEY, JSON.stringify(rs)); } catch (e) { /* blocked: this page only */ }
      return rs;
    },
    clean: cleanRules,
    isDefault: function (rs) { var a = activeRules(rs || TV.ruleset.get()); return !a.optional.length && !a.custom.length; },
    /* what the results depend on: the engine's tables, and the added and switched-on rows */
    key: function (rs) {
      rs = rs || TV.ruleset.get();
      return TABLES_VERSION + '-' + (TV.ruleset.isDefault(rs) ? 'default' : 'r' + hashText(JSON.stringify(activeRules(rs))));
    },
    label: function (rs) {
      rs = rs || TV.ruleset.get();
      if (TV.ruleset.isDefault(rs)) return 'Lookup tables';
      var a = activeRules(rs), out = [];
      if (a.optional.length) out.push(a.optional.join(', '));
      if (a.custom.length) out.push(a.custom.length + ' Customized ' + (a.custom.length === 1 ? 'Rule' : 'Rules'));
      return 'Tables + ' + out.join(' + ');
    }
  };
  /* the page was drawn under table file `key`; reload when the rows changed since (in another
   * tab, or on tables.html before the browser brought this page back from its cache) */
  var SHOWN_KEY = null;
  TV.watchRules = function (key) {
    SHOWN_KEY = key;
    function check() { if (TV.ruleset.key() !== SHOWN_KEY) location.reload(); }
    window.addEventListener('storage', function (e) { if (e.key === RULES_KEY) check(); });
    window.addEventListener('pageshow', function (e) { if (e.persisted) check(); });
  };
  /* the page itself now shows the rows of `key` (it added rows and analysed again) */
  TV.rulesShown = function (key) {
    SHOWN_KEY = key;
    TV.$$('[data-rules-state]').forEach(function (el) { el.textContent = TV.ruleset.label(); });
    document.body.classList.toggle('rules-custom', !TV.ruleset.isDefault());
  };
  /* where "+ Row from this action" goes: tables.html with the row's draft and a way back */
  TV.ruleDraftHref = function (a) {
    var tgt = (a.cmd || a.target || '').trim(), draft;
    if (!tgt) draft = { field: 'tool', match: a.tool };
    else if (/^[^\s]+\.[A-Za-z0-9]{1,6}$/.test(tgt)) draft = { field: 'target', match: tgt.split('/').pop() };
    else {
      var parts = tgt.split(/\s*(?:&&|\|\||;|\|)\s*/).filter(function (p) { return p && !/^(cd|export|set|source)\b/.test(p); });
      var words = (parts[0] || tgt).split(/\s+/).filter(function (w) { return w && !/^\d+>/.test(w); });
      draft = { field: 'target', match: words.slice(0, words[0] && /^(\.\/)?(gradlew|git|adb|python3?|npm|mvn)$/.test(words[0].split('/').pop()) ? 2 : 1).join(' ') };
    }
    draft.kind = 'phase';
    draft.value = a.phase;
    return 'tables.html#draft=' + encodeURIComponent(JSON.stringify(draft)) + '&back=' + encodeURIComponent(location.pathname.split('/').pop() + location.hash);
  };

  /* ------------------------------------------------------------------ lookup tables (atif/rules.py) */
  /* a row of the user's in plain words; the same sentence as rules.describe() */
  TV.ruleSentence = function (r) {
    var how = r.regex ? 'matches' : 'contains', q = '“' + (r.match || '…') + '”';
    if (r.kind === 'file_role') return 'Files whose path ' + how + ' ' + q + ' are ' + (TV.TARGET_PHRASE[r.value] || r.value) + '.';
    if (r.kind === 'shell_tool') return 'The tool ' + q + ' runs shell commands (its argument “' + r.value + '”); they are read like Bash commands.';
    if (r.field === 'program' && !r.regex) {
      if (r.kind === 'category') return 'Steps that run ' + q + ' are ' + r.value + '.';
      return 'Steps that run ' + q + (r.value === 'follow' ? ' take the phase of the step before.' : ' belong to ' + r.value + '.');
    }
    var subject = { target: 'Steps whose command', tool: 'Steps whose tool', any: 'Steps whose command or tool', program: 'Steps whose programs' }[r.field || 'target'];
    if (r.kind === 'category') return subject + ' ' + how + ' ' + q + ' are ' + r.value + '.';
    if (r.value === 'follow') return subject + ' ' + how + ' ' + q + ' take the phase of the step before.';
    return subject + ' ' + how + ' ' + q + ' belong to ' + r.value + '.';
  };
  /* a target in a row's sentence (atif/rules.py TARGET_PHRASE) */
  TV.TARGET_PHRASE = { source: 'source files', test: 'test files', docs: 'docs', build: 'build files', other: 'other repository files',
    outside: 'outside the repository' };
  /* the phase table's row of an action (atif/rules.py contents: L1-L15 are rows 1-15, LG the
   * general rule, 'user' a phase row of the user's), as a short label and in words */
  TV.phaseRow = function (id) {
    var v = TV.vocab || {}, rows = (v.lookup || {}).phases || (v.tables || {}).phases || [];
    return rows.filter(function (x) { return x.id === id; })[0] || null;
  };
  TV.phaseRowLabel = function (id) {
    if (id === 'user') return 'your rule';
    if (id === 'LG') return 'the general rule';
    var r = TV.phaseRow(id);
    return 'phase rule ' + (r && r.n ? r.n : String(id).replace(/^[LP]/, ''));
  };
  /* the phase row in a few words: "phase row 6: test, before the first edit of a source file" */
  TV.phaseRowShort = function (id) {
    if (id === 'LG') return 'general rule: the phase of the previous step';
    var r = TV.phaseRow(id);
    if (!r || !r.categories) return TV.phaseRowLabel(id);
    return TV.phaseRowLabel(id) + ': ' + r.categories + (r.target && r.target !== 'any' ? ' · ' + r.target : '') + ' · ' +
      r.position.charAt(0).toLowerCase() + r.position.slice(1);
  };
  TV.phaseRowDef = function (id) {
    if (id === 'user') return 'a phase rule of yours (Lookup tables page) set this phase';
    if (id === 'LG') return 'no rule of the phase table matches this step, so by the general rule it takes the phase of the previous step';
    var r = TV.phaseRow(id);
    if (!r || !r.categories) return TV.phaseRowLabel(id) + ' of the phase table';
    var to = /^\(previous/.test(r.phase) ? 'the phase of the previous step' : r.phase;
    return TV.phaseRowLabel(id) + ' of the phase table: ' + r.categories + (r.target && r.target !== 'any' ? ' on a ' + r.target : '') + ', ' +
      r.position.charAt(0).toLowerCase() + r.position.slice(1) + ' → ' + to;
  };
  /* read-only list (Lookup tables popover): the built-in rows (Table 4, follow, F1), the
   * ready-made rows that are added (vocab.rules), and the user's switched-on rows. Data built
   * before the tables (the grouping rules of codebook version 3) is listed as it is. */
  TV.rulesListHTML = function (builtin, custom) {
    function list(rules, locked) {
      return '<ol class="rulelist">' + rules.map(function (r) {
        return '<li class="rule"><span class="rid">' + TV.esc(/^[LP]\d+$/.test(r.id) ? r.id.slice(1) : /^(FW|F1|LG)$/.test(r.id) ? '·' : r.id) + '</span><span class="rtext">' + (r.title ? '<b>' + TV.esc(r.title) + '.</b> ' : '') +
          TV.esc(r.sentence || r.text || TV.ruleSentence(r)) + (locked ? ' <span class="fixed" data-tip="built in: the Final lookup tables, always applied">built in</span>' : '') + '</span></li>';
      }).join('') + '</ol>';
    }
    builtin = builtin || [];
    var must = builtin.filter(function (r) { return r.mandatory === true || !('mandatory' in r); });
    var h = '<h3 class="rl-h">Phase lookup (built in)</h3>' + list(must, true);
    if (custom && custom.length) h += '<h3 class="rl-h">Your rules</h3>' + list(custom.filter(function (r) { return r.enabled !== false; }));
    return h;
  };

  /* ------------------------------------------------------------------ logo */
  /* Inceptor mark: three tiers (phases, categories, actions), each finer than the one above,
   * crossed by the trajectory arc. Same geometry as logo.svg (the favicon), but themed with CSS vars. */
  var LOGO_TOP = [[3, 5, 'planning'], [9, 6, 'localization'], [16, 8, 'repair'], [25, 4, 'validation']];
  var LOGO_MID = [[3, 2.5, 0], [6, 2, 0], [9, 3.5, 1], [13, 2, 1], [16, 2.5, 2], [19, 2, 2], [21.5, 2.5, 2], [25, 1.75, 3], [27.25, 1.75, 3]];
  TV.logoSVG = function (size) {
    function rect(x, y, w, h, rx, p, op) {
      return '<rect x="' + x + '" y="' + y + '" width="' + w + '" height="' + h + '" rx="' + rx + '" fill="var(--p-' + p + ')"' +
        (op < 1 ? ' fill-opacity="' + op + '"' : '') + '/>';
    }
    var out = LOGO_TOP.map(function (t) { return rect(t[0], 6, t[1], 5, 1.2, t[2], 1); });
    LOGO_MID.forEach(function (m) { out.push(rect(m[0], 13.5, m[1], 3.5, 0.8, LOGO_TOP[m[2]][2], 0.75)); });
    for (var k = 0; k < 13; k++) {
      var x = 3 + 2 * k, p = 'validation';
      for (var i = 0; i < LOGO_TOP.length; i++) if (x < LOGO_TOP[i][0] + LOGO_TOP[i][1] + 1) { p = LOGO_TOP[i][2]; break; }
      out.push(rect(x, 19.5, 1, 2.5, 0.5, p, 0.6));
    }
    var arc = 'M3 28.5C13 28.5 21 20 26.5 4.5';
    return '<svg class="logomark" viewBox="0 0 32 32" width="' + (size || 22) + '" height="' + (size || 22) + '" aria-hidden="true">' + out.join('') +
      '<path d="' + arc + '" fill="none" stroke="var(--surface)" stroke-width="3.6" stroke-linecap="round"/>' +
      '<path d="' + arc + '" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>' +
      '<circle cx="26.5" cy="4.5" r="2.3" fill="currentColor" stroke="var(--surface)" stroke-width="1.6"/></svg>';
  };
  document.addEventListener('DOMContentLoaded', function () {
    TV.$$('[data-logo]').forEach(function (el) { el.insertAdjacentHTML('afterbegin', TV.logoSVG(+el.getAttribute('data-logo') || 22)); });
  });

  /* ------------------------------------------------------------------ theme */
  var THEMES = ['auto', 'light', 'dark'];
  var THEME_ICON = { auto: '◐', light: '☀', dark: '☾' };
  TV.theme = 'auto';
  try { TV.theme = localStorage.getItem('tv-theme') || 'auto'; } catch (e) { /* storage blocked */ }
  var hq = TV.readHash();
  if (THEMES.indexOf(hq.theme) >= 0) TV.theme = hq.theme;
  if (THEMES.indexOf(TV.theme) < 0) TV.theme = 'auto';
  TV.applyTheme = function () {
    if (TV.theme === 'auto') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', TV.theme);
    TV.$$('[data-theme-btn]').forEach(function (b) {
      b.innerHTML = '<span aria-hidden="true">' + THEME_ICON[TV.theme] + '</span><span class="lbl">' + TV.theme[0].toUpperCase() + TV.theme.slice(1) + '</span>';
      b.title = 'Theme: ' + TV.theme + ' (click: auto → light → dark)';
    });
  };
  TV.applyTheme();
  document.addEventListener('DOMContentLoaded', function () {
    TV.applyTheme();
    /* "#33" links (the actions that decided a phase outcome) move the cursor of the page's views */
    document.addEventListener('click', function (e) {
      var b = e.target.closest('[data-goto]');
      if (b && TV.setCursor) { e.preventDefault(); TV.setCursor(+b.getAttribute('data-goto')); }
    });
    TV.$$('[data-theme-btn]').forEach(function (b) {
      b.addEventListener('click', function () {
        TV.theme = THEMES[(THEMES.indexOf(TV.theme) + 1) % THEMES.length];
        try { localStorage.setItem('tv-theme', TV.theme); } catch (e) { /* ignore */ }
        TV.applyTheme();
      });
    });
    var help = TV.$('#help'), pop = TV.$('#rulesPop');
    TV.$$('[data-help-btn]').forEach(function (b) { b.addEventListener('click', function () { help.hidden = !help.hidden; if (pop) pop.hidden = true; }); });
    TV.$$('[data-help-close]').forEach(function (b) { b.addEventListener('click', function () { help.hidden = true; }); });
    /* Lookup tables popover: what this page applies (the built-in rows of the loaded data,
     * with the user's ready-made and own rows from TV.ruleset), in plain words */
    TV.$$('[data-rules-btn]').forEach(function (b) {
      b.addEventListener('click', function () {
        if (!pop) return;
        var rules = (TV.vocab || {}).rules, rs = TV.ruleset.get(), on = {};
        rs.optional.forEach(function (o) { on[o.id] = 1; });
        TV.$('#rulesBody').innerHTML = rules && rules.length ?
          TV.rulesListHTML(rules.map(function (r) { return r.mandatory === false ? Object.assign({}, r, { on: !!on[r.id] }) : r; }),
            rs.custom.map(function (r) { return Object.assign({ sentence: TV.ruleSentence(r) }, r); })) :
          '<p class="note">This data was built before the tables were exported. Regenerate it: <code>python3 -m atif.cli view --all</code></p>';
        pop.hidden = !pop.hidden;
        if (help) help.hidden = true;
      });
    });
    TV.$$('[data-rules-state]').forEach(function (el) { el.textContent = TV.ruleset.label(); });
    document.body.classList.toggle('rules-custom', !TV.ruleset.isDefault());
    TV.$$('[data-rules-close]').forEach(function (b) { b.addEventListener('click', function () { pop.hidden = true; }); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && pop && !pop.hidden) pop.hidden = true; });
  });

  /* ------------------------------------------------------------------ tooltip */
  var tipEl = null;
  TV.tip = {
    show: function (html, ev) {
      if (!tipEl) tipEl = document.getElementById('tip');
      if (!tipEl) return;
      tipEl.innerHTML = html;
      tipEl.hidden = false;
      TV.tip.move(ev);
    },
    move: function (ev) {
      if (!tipEl || tipEl.hidden || !ev) return;
      var z = TV.zoom(), w = tipEl.offsetWidth * z, h = tipEl.offsetHeight * z;   // on screen
      var x = ev.clientX + 14, y = ev.clientY + 16;
      if (x + w > window.innerWidth - 8) x = ev.clientX - w - 12;
      if (y + h > window.innerHeight - 8) y = ev.clientY - h - 12;
      tipEl.style.left = Math.max(4, x) / z + 'px';
      tipEl.style.top = Math.max(4, y) / z + 'px';
    },
    hide: function () { if (tipEl) tipEl.hidden = true; }
  };
  /* the page is drawn larger with CSS zoom on body (viewer.css --zoom): mouse positions are
   * in screen pixels, lengths inside the page in CSS pixels */
  TV.zoom = function () { return parseFloat(getComputedStyle(document.body).zoom) || 1; };
  /* the mouse position inside an SVG, in its own units, whatever the zoom */
  TV.svgPoint = function (svg, ev) {
    var r = svg.getBoundingClientRect(), k = (svg.width.baseVal.value || r.width) / (r.width || 1);
    return { x: (ev.clientX - r.left) * k, y: (ev.clientY - r.top) * k };
  };
  /* any element with data-tip gets a hover tooltip (text, escaped) */
  var tipOwner = null;
  /* data-phase-tip="<phase id>": the phase pop-up of the selected trajectory (its outcomes and
   * the files it edited and looked at), the same one the Fingerprint tab shows */
  function phaseTipHTML(el) {
    var t = TV.traj && TV.traj(), id = el.getAttribute('data-phase-tip');
    var p = t && (t.phases || []).filter(function (x) { return String(x.id) === id; })[0];
    return p ? TV.phaseTip(t, p) : null;
  }
  document.addEventListener('mouseover', function (ev) {
    var el = ev.target.closest && ev.target.closest('[data-tip], [data-phase-tip]');
    if (el === tipOwner) return;
    tipOwner = el;
    if (!el) { TV.tip.hide(); return; }
    var html = el.hasAttribute('data-phase-tip') ? phaseTipHTML(el) : null;
    TV.tip.show(html || TV.esc(el.getAttribute('data-tip') || '').replace(/\n/g, '<br>'), ev);   // a line break in a plain tip is kept
  });
  document.addEventListener('mousemove', function (ev) { if (tipOwner) TV.tip.move(ev); });
  document.addEventListener('scroll', function () { if (tipOwner) { tipOwner = null; TV.tip.hide(); } }, true);

  /* ------------------------------------------------------------------ trajectory preparation (trajview/3) */
  /* links the levels: t.phases (spans) -> p.groups (consecutive actions of one category: the
   * Trajectory view's middle level) -> actions. A phase's outcome history is p.subphases (the
   * data's subphases, shown only as outcomes); t.subs = all of them in action order. Each action
   * gets a.sub (its outcome stretch), a.span, a.group and a.attempt (the repair attempt whose
   * range holds it) */
  TV.prepTraj = function (t) {
    t.badges = t.badges || {};
    t.stats = t.stats || {};
    t.metrics = t.metrics || {};
    t.outcome = t.outcome || {};
    t.oc = TV.oc(t.outcome.pass);
    t.actions = t.actions || [];
    t.phases = t.phases || [];
    t.attempts = t.attempts || [];
    t.n = t.n_actions || t.actions.length;
    t.key = t.agent + '-r' + t.run;
    t.subs = [];
    t.subById = {};
    t.phases.forEach(function (p, pi) {
      p._k = pi;
      (p.subphases || (p.subphases = [])).forEach(function (s) {
        s.p = p;
        s.t = t;
        s._k = t.subs.length;
        s.flags = s.flags || [];
        s.outcome = TV.outcomeOf(s.outcome);
        s.own_phases = s.own_phases || {};
        s.absorbed = Object.keys(s.own_phases).filter(function (k) { return k !== p.phase; });
        t.subs.push(s);
        t.subById[s.id] = s;
      });
    });
    t.subStrip = t.subs.map(function (s) { return [s.outcome, s.start, s.end, s.p.phase, s.evidence]; });
    t.strip = t.phases.map(function (p) { return [p.phase, p.start, p.end]; });
    t.groups = [];
    t.phases.forEach(function (p) {
      p.groups = [];
      for (var i = p.start; i <= p.end; i++) {
        var a = t.actions[i - 1], g = p.groups[p.groups.length - 1];
        if (!a) continue;
        if (g && g.cat === a.category && g.end === i - 1) { g.end = i; }
        else { g = { id: p.id + '.c' + (p.groups.length + 1), p: p, cat: a.category, start: i, end: i }; p.groups.push(g); t.groups.push(g); }
        a.group = g;
      }
    });
    var subAt = [], attAt = [];
    t.subs.forEach(function (s) { for (var i = s.start; i <= s.end; i++) subAt[i] = s; });
    t.attempts.forEach(function (at) {
      at.outcome = TV.outcomeOf(at.outcome);
      for (var i = at.start; i <= at.end; i++) attAt[i] = at;
    });
    var tsOk = 0;
    t.actions.forEach(function (a) {
      a.sub = subAt[a.i] || null;
      a.span = a.sub ? a.sub.p : null;
      a.group = a.group || null;
      a.attempt = attAt[a.i] || null;
      a.tms = a.ts ? Date.parse(a.ts) : NaN;
      if (!isNaN(a.tms)) tsOk++;
    });
    t.targets = t.targets || { source: 'none', files: [] };
    t.actions.forEach(function (a) {
      a.stepOutcome = TV.outcomeOf(a.step_outcome);
      a.edited = a.category === 'edit' ? (a.edits || a.files || []) : [];
      a.opened = a.category === 'edit' ? [] : (a.files || []);
      a.found = a.found || [];
    });
    /* localization -> repair cycles: a Repair span opens a new cycle when a Localization span
     * came after the previous Repair span (or none came before it); p.cyc = its cycle */
    var cyc = 0, locSince = true;
    t.phases.forEach(function (p) {
      if (p.phase === 'localization') locSince = true;
      if (p.phase === 'repair') { if (locSince) { cyc++; locSince = false; } p.cyc = cyc; }
    });
    t.nCycles = cyc;
    t.hasTs = tsOk >= 2 && tsOk >= 0.8 * t.actions.length;
    if (t.hasTs) {
      var last = NaN;
      t.actions.forEach(function (a) { if (isNaN(a.tms)) a.tms = last; else last = a.tms; });
      var first = t.actions.filter(function (a) { return !isNaN(a.tms); })[0];
      t.actions.forEach(function (a) { if (isNaN(a.tms)) a.tms = first.tms; });
      t.t0 = t.actions[0].tms;
      t.t1 = t.actions[t.actions.length - 1].tms;
    }
    return t;
  };
  /* the Trajectory view's levels (hash lvl): phases -> categories (runs of one action category
   * within a phase) -> steps; links of earlier versions open the level that replaced theirs */
  TV.LEVELS = [['phases', 'Phase'], ['categories', '+ Action category'], ['steps', '+ Step']];
  var LEVEL_ALIAS = { purposes: 'phases', subphases: 'categories', segments: 'categories' };
  TV.levelOf = function (v) {
    v = LEVEL_ALIAS[v] || v;
    return TV.LEVELS.some(function (x) { return x[0] === v; }) ? v : null;
  };
  /* what is open at a level: e.p = phases, e.g = category groups */
  TV.levelExpansion = function (t, level) {
    var e = { p: {}, g: {} };
    if (level === 'categories' || level === 'steps') t.phases.forEach(function (p) { e.p[p.id] = 1; });
    if (level === 'steps') t.groups.forEach(function (g) { e.g[g.id] = 1; });
    return e;
  };
  TV.levelCtlHTML = function (level) {
    return '<span class="seg small" role="group" aria-label="Level">' + TV.LEVELS.map(function (x) {
      return '<button type="button" data-level="' + x[0] + '" aria-pressed="' + (level === x[0]) + '">' + x[1] + '</button>';
    }).join('') + '</span>';
  };
  /* ------------------------------------------------------------------ file dots (Localization, Repair) */
  /* A Localization span's files are the ones its steps read or searched in (not the names a
   * search only listed); each is grey, or wears the colour of the cycle whose Repair first
   * edits it after the span. A Repair span's files are the ones it edits, in its cycle's
   * colour. Edited files come first, so the marks a band has room for show them; the rest is "+n". */
  TV.CYCLE_COLORS = 4;
  TV.cycVar = function (k) { return k ? 'var(--cy-' + ((k - 1) % TV.CYCLE_COLORS + 1) + ')' : 'var(--f-seen)'; };
  TV.spanFiles = function (t, p) {
    if (p._files) return p._files;
    var rows = [];
    function add(f, a) {
      var r = rows.filter(function (x) { return TV.sameFile(x.f, f); })[0];
      if (!r) rows.push(r = { f: f, steps: [] });
      if (r.steps.indexOf(a) < 0) r.steps.push(a);
    }
    for (var i = p.start; i <= p.end; i++) {
      var a = t.actions[i - 1];
      if (!a) continue;
      (p.phase === 'repair' ? a.edited : a.category === 'edit' ? [] : a.opened).forEach(function (f) { add(f, a); });
    }
    rows.forEach(function (r) {
      if (p.phase === 'repair') { r.cyc = p.cyc || 0; return; }
      var ed = t.actions.filter(function (b) {
        return b.i > p.end && b.span && b.span.phase === 'repair' && b.edited.some(function (g) { return TV.sameFile(g, r.f); });
      })[0];
      r.cyc = ed ? ed.span.cyc || 0 : 0;
      r.editAt = ed || null;
    });
    if (p.phase === 'localization') rows = rows.filter(function (r) { return r.cyc; }).concat(rows.filter(function (r) { return !r.cyc; }));
    return (p._files = rows);
  };
  /* the dots as SVG circles centred on cx (gap = centre to centre); '' when they do not fit in w */
  /* how many file marks fit in `avail` px (mark width + gap = step): all of them, or as many
   * as leave room for a "+n" label (fs = its font size); k = 0 with more > 0 is the label alone,
   * null = not even that fits */
  TV.marksFit = function (n, avail, step, gap, fs) {
    var k = Math.min(n, Math.floor((avail + gap) / step));
    if (k >= n) return { k: n, more: 0, lw: 0 };
    for (; k >= 0; k--) {
      var lw = String('+' + (n - k)).length * fs * 0.62 + 2;
      if ((k ? k * step - gap + 3 : 0) + lw <= avail) return { k: k, more: n - k, lw: lw };
    }
    return null;
  };
  /* the file marks of a span as SVG rounded rectangles centred in [a, b]: as many as fit, then "+n" */
  TV.marksSVG = function (rows, a, b, cy, mw, mh, gap, fs) {
    var step = mw + gap, f = rows.length ? TV.marksFit(rows.length, b - a - 4, step, gap, fs) : null;
    if (!f) return '';
    var marks = f.k ? f.k * step - gap : 0, total = marks + (f.more ? (f.k ? 3 : 0) + f.lw : 0);
    var x = (a + b) / 2 - total / 2, s = '';
    for (var i = 0; i < f.k; i++) s += '<rect class="fdot" x="' + (x + i * step).toFixed(2) + '" y="' + (cy - mh / 2) + '" width="' + mw + '" height="' + mh + '" rx="1.5" fill="' + TV.cycVar(rows[i].cyc) + '"/>';
    if (f.more) s += '<text class="fmore" x="' + (x + marks + (f.k ? 3 : 0)).toFixed(2) + '" y="' + (cy + 0.5) + '" dominant-baseline="middle" style="font-size:' + fs + 'px">+' + f.more + '</text>';
    return s;
  };
  TV.dotHTML = function (cyc) { return '<i class="fdot" style="background:' + TV.cycVar(cyc) + '"></i>'; };
  /* the file marks in HTML: the first `max` (default all), then "+n" */
  TV.dotsHTML = function (rows, tip, max) {
    if (!rows.length) return '<span class="fdots none"' + (tip ? ' ' + tip : '') + '>no file</span>';
    var k = max == null ? rows.length : Math.min(max, rows.length);
    return '<span class="fdots"' + (tip ? ' ' + tip : '') + '>' + rows.slice(0, k).map(function (r) { return TV.dotHTML(r.cyc); }).join('') +
      (rows.length > k ? '<span class="more">+' + (rows.length - k) + '</span>' : '') + '</span>';
  };
  /* "2 of 7 edited" / "3 files edited" */
  TV.filesSummary = function (p, rows) {
    if (p.phase === 'repair') return TV.plural(rows.length, 'file') + ' edited';
    var ed = rows.filter(function (r) { return r.cyc; }).length;
    return rows.length ? ed + ' of ' + TV.plural(rows.length, 'file') + ' localized and edited' : 'no file read or searched';
  };
  /* a structured legend: one row per item, [label, note, items HTML]; rows without items are left out */
  TV.legendCardHTML = function (rows, cls) {
    return '<div class="legendcard lg-compact' + (cls ? ' ' + cls : '') + '">' + rows.filter(function (r) { return r && r[2]; }).map(function (r) {
      return '<div class="lg-row' + (r[0] ? '' : ' lg-cont') + '"><span class="lg-k"><b>' + r[0] + '</b>' + (r[1] ? '<span class="muted">' + r[1] + '</span>' : '') + '</span><span class="lg-v">' + r[2] + '</span></div>';
    }).join('') + '</div>';
  };
  /* the legend of the dots: grey = localized only, one colour per localization -> repair attempt
   * (the code's cycles) the trajectories have */
  TV.fileLegend = function (nCycles) {
    var h = '<span class="lgm" data-tip="Localization: a file read or searched in, never edited after (one mark per file)">' + TV.dotHTML(0) + 'localized only</span>';
    var n = Math.max(1, Math.min(nCycles || 1, TV.CYCLE_COLORS));
    for (var k = 1; k <= n; k++) {
      h += '<span class="lgm" data-tip="' + TV.esc('localized, then edited in Repair' + (nCycles > 1 ? ' at attempt ' + k + ' (a localization followed by a repair)' + (nCycles > TV.CYCLE_COLORS && k === 1 ? '; attempts ' + (TV.CYCLE_COLORS + 1) + ', … repeat the colours' : '') : '') +
        '; the same colour marks the file in Localization and in Repair') + '">' + TV.dotHTML(k) + 'localized and repaired' + (nCycles > 1 ? ' at attempt ' + k : '') + '</span>';
    }
    return h;
  };
  /* the legend rows of the outcome band: Validation's self-validation, then the file marks */
  TV.bandLegendRows = function (used, nCycles) {
    var vs = TV.OUTCOMES.filter(function (o) { return (used || {})[o]; });
    return [
      [vs.length ? 'Phase outcome' : '', 'validation · self-validation by the agent', vs.length ? TV.outcomeLegend(used) : ''],
      [vs.length ? '' : 'Phase outcome', 'localization, repair · a mark per file', TV.fileLegend(nCycles)]
    ];
  };
  /* the file list of a Localization / Repair span: dot, name, where it was edited or localized */
  TV.spanFilesHTML = function (t, p, max) {
    var rows = TV.spanFiles(t, p);
    max = max || 10;
    if (!rows.length) return '';
    return '<ul class="tt-files dotted">' + rows.slice(0, max).map(function (r) {
      var rel;
      if (p.phase === 'repair') rel = fileRelation(t, r.f, r.steps[0], 'edited');
      else rel = r.editAt ? '<span class="rel ok">localized and edited at #' + r.editAt.i + (t.nCycles > 1 ? ' · attempt ' + r.cyc : '') + '</span>' : '<span class="rel">localized only</span>';
      return '<li>' + TV.dotHTML(r.cyc) + '<span class="fn" title="' + TV.esc(r.f) + '">' + TV.esc(TV.fileName(r.f)) + '</span>' +
        '<span class="cnt">' + (r.steps.length > 1 ? '×' + r.steps.length : '#' + r.steps[0].i) + '</span>' + rel + '</li>';
    }).join('') + (rows.length > max ? '<li class="more">+' + (rows.length - max) + ' more</li>' : '') + '</ul>';
  };

  /* what an action is to its attempt: "edit", "judging run" or "" */
  TV.attemptRole = function (a) {
    var at = a.attempt;
    if (!at) return '';
    if (at.edits.indexOf(a.i) >= 0) return 'edit';
    return at.judge === a.i ? 'judging run' : 'between';
  };

  /* how an action's verdict was read: the result's line that decided it (atif/verdict.py
   * evidence_line), so a pass or fail can be checked against the output */
  TV.evidenceHTML = function (a) {
    if (!a.evidence) return '';
    var line = a.evidence_line ? '<code class="evl">' + TV.esc(a.evidence_line) + '</code>' : '';
    if (a.verdict === 'none') {
      if (a.evidence === 'no_test_evidence') return '<div class="dt-ev">executed, not passed: a test run needs a test result, and the output shows only ' + (line || 'an exit code') + '</div>';
      if (a.evidence === 'no_check_evidence') return '<div class="dt-ev">executed, not passed: the output shows only ' + (line || 'an exit code') + ', no build, compilation or test result</div>';
      return '';
    }
    return '<div class="dt-ev v-' + a.verdict + '">' + TV.VERDICT_WORD[a.verdict] + ' (self-check by the agent), read from ' +
      (line || (a.evidence === 'exit' ? 'the log, which marks this call as an error' : TV.esc(TV.humanize(a.evidence)))) + '</div>';
  };
  /* the deciding actions of an outcome stretch (s.checks) that lie outside it: the edits of a
   * repair attempt are judged by the build or test after them */
  TV.outsideChecks = function (s) { return (s.checks || []).filter(function (c) { return c < s.start || c > s.end; }); };
  TV.judgedByHTML = function (t, s) {
    var out = TV.outsideChecks(s);
    if (!out.length) return '';
    var a = t.actions[out[0] - 1] || {};
    return '<span class="jby" data-tip="' + TV.esc('These edits hold no check of their own. They belong to a repair attempt, and the ' + (a.category || 'run') +
      ' at #' + out.join(', #') + ' judged that attempt' + (a.evidence_line ? ': ' + a.evidence_line : '') + '.') + '">by #' + out.join(', #') + '</span>';
  };
  /* an outcome in words (self-validation: what the agent's own runs showed) */
  TV.outcomeText = function (s) { return TV.OUTCOME_LABEL[s.outcome]; };
  /* a phase's outcome: the final one as a solid pill (with its evidence, and "by #N" when a
   * later run judged it). A phase whose checks changed shows its earlier outcomes first, as
   * hollow pills (errored → passed); cur = the stretch of the action in the details panel (ringed). */
  TV.phaseOutcomeHTML = function (t, p, cur) {
    if (TV.hasFiles(p.phase)) return TV.dotsHTML(TV.spanFiles(t, p), 'data-phase-tip="' + TV.esc(p.id) + '"');
    var subs = p.subphases || [], last = subs[subs.length - 1];
    if (!last || !TV.hasVerdict(p.phase)) return '';
    var multi = subs.length > 1;
    var h = subs.slice(0, -1).map(function (s) {
      var ev = TV.EVIDENCE_SHORT[s.evidence], out = TV.outsideChecks(s);
      return '<span class="opill hist o-' + s.outcome + (s === cur ? ' cur' : '') + '" aria-label="' + s.outcome + '" data-tip="' +
        TV.esc('#' + s.start + '–#' + s.end + ' · ' + TV.outcomeDef(p.phase, s.outcome) + (ev ? ' · evidence: ' + TV.EVIDENCE_LABEL[s.evidence] : '') +
          (out.length ? ' · decided by #' + out.join(', #') : '')) + '">' + s.outcome + '</span><i class="oh-arr" aria-hidden="true">→</i>';
    }).join('');
    return '<span class="ohist">' + h + TV.outcomePill(last.outcome, null, p.phase, last.evidence, 'final' + (multi && last === cur ? ' cur' : '')) + TV.judgedByHTML(t, last) + '</span>';
  };
  /* the details panel's actions: start a lookup-table row from the action, see its raw step */
  TV.detailsActsHTML = function (a) {
    return '<div class="dt-acts"><a class="btn small" href="' + TV.esc(TV.ruleDraftHref(a)) + '" title="Start a rule of a lookup table, on the Lookup tables page, that matches actions like this one">+ Rule from this action</a>' +
      '<button type="button" class="btn small" data-raw aria-pressed="false" title="This step as the log recorded it (its ATIF JSON): the message, the tool call and the full output">{ } Raw JSON</button></div>';
  };

  /* the details panel's body for one action (bug page and Analyze page) */
  TV.actionDetailsHTML = function (t, a) {
    var p = a.span, h = '';
    h += '<div class="dt-row"><span class="midchip" data-tip="' + TV.esc(TV.catDef(a.category)) + '">' + TV.esc(a.category) + '</span><b>' + TV.esc(a.tool) + '</b>' +
      (a.scope && a.scope !== 'main' ? '<span class="tag" data-tip="a step of a sub-agent the agent delegated work to">sub-agent</span>' : '') +
      '<span class="vg v-' + a.verdict + '" data-tip="' + TV.esc(TV.VERDICT_LABEL[a.verdict]) + '">' + TV.verdictDot(a.verdict) + TV.VERDICT_WORD[a.verdict] + '</span>' +
      (t.anchor === a.i ? '<span class="tag" data-tip="the first edit of a source file: repair and validation happen only from it on">first fix</span>' : '') +
      (a.rules || []).map(function (r) {
        var who = /^O\d/.test(r.id) ? 'ready-made rule' : 'your rule';
        return '<span class="tag rule" data-tip="' + TV.esc(who + ' (Lookup tables page): ' + r.sentence) + '">' + who + '</span>';
      }).join('') + '</div>';
    h += TV.evidenceHTML(a);
    /* summary, thought, action, result: what it does in short, why, what it ran, what came back */
    if (a.target) h += '<div class="dt-k">Summary</div><pre class="dt-code">' + TV.esc(a.target) + '</pre>';
    h += '<div class="dt-k">' + (a.thought_source === 'reasoning' ? 'Thought (reasoning)' : a.thought_source === 'narration' ? 'Thought (narration)' : 'Thought') +
      '<span class="dt-full" data-full-note="thought"></span></div>' +
      '<div class="dt-text dt-long" data-full="thought">' + (a.thought ? TV.esc(a.thought) : '<span class="muted">(none)</span>') + '</div>';
    if (a.cmd || a.tool) h += '<div class="dt-k">Action</div><pre class="dt-code">' + TV.esc(a.cmd || a.tool) + '</pre>';   // a tool call without a command line: its tool
    if (a.edits && a.edits.length) h += '<div class="dt-k">Edits</div><pre class="dt-code">' + TV.esc(a.edits.join('\n')) + '</pre>';
    h += '<div class="dt-k">Result<span class="dt-full" data-full-note="result"></span></div><pre class="dt-code dt-long" data-full="result">' + (a.result ? TV.esc(a.result) : '<span class="muted">(empty)</span>') + '</pre>';
    h += '<div class="dt-raw" hidden></div>';
    if (p) {
      h += '<div class="dt-k">Phase</div><div class="dt-row">' + TV.phaseChip(p.phase) + '<span class="muted small">#' + p.start + '–#' + p.end + '</span></div>';
      if (a.row) h += '<div class="dt-why"><b>Phase explanation</b> ' + TV.esc(TV.phaseRowShort(a.row)) + '</div>';
    }
    if (a.item) h += '<div class="dt-why"><b>Action explanation</b> action table entry “' + TV.esc(a.item) + '”</div>';
    /* no phase outcome here: the outcome band and the phase pop-up show it */
    if (a.ts) h += '<div class="dt-meta">' + TV.esc(a.ts) + '</div>';
    return h;
  };

  /* ------------------------------------------------------------------ files in the pop-ups */
  /* The pop-ups name files, not paths: localized here, edited here, tested here. A file of one
   * step is matched with the others like the engine matches a target file (atif/phase.py
   * _match): same name, and one path ends with the other (a search's "-name Foo.java" gives
   * the name only). */
  TV.fileName = function (p) { return String(p || '').replace(/\/+$/, '').split('/').pop(); };
  TV.sameFile = function (p, q) {
    if (TV.fileName(p) !== TV.fileName(q)) return false;
    p = String(p); q = String(q);
    return p === q || p.slice(-q.length - 1) === '/' + q || q.slice(-p.length - 1) === '/' + p;
  };
  /* long paths in a command or target, as their file names */
  TV.shortPaths = function (s) {
    return String(s || '').replace(/(^|[\s"'=(:])((?:~|\.{1,2})?\/?(?:[\w.\-+@$]+\/){2,})([\w.\-+@]*)/g, function (m, pre, dir, name) {
      return pre + (name || TV.fileName(dir) + '/');
    });
  };
  function stepsWith(t, file, key, before) {
    var out = [];
    t.actions.forEach(function (b) {
      if (before && b.i >= before) return;
      if (b[key].some(function (f) { return TV.sameFile(f, file); })) out.push(b);
    });
    return out;
  }
  function links(steps, max) {
    return steps.slice(0, max || 3).map(function (b) { return '#' + b.i; }).join(', ') + (steps.length > (max || 3) ? ', …' : '');
  }
  /* how a file relates to the rest of the trajectory, in a few words with a mark:
   * looked at -> was it edited later; edited -> was it localized before */
  function fileRelation(t, f, a, kind) {
    if (kind === 'edited') {
      var loc = t.actions.filter(function (b) {
        return b.i < a.i && b.phase === 'localization' && b.opened.concat(b.found).some(function (g) { return TV.sameFile(g, f); });
      });
      if (loc.length) return '<span class="rel ok">localized at ' + links(loc) + '</span>';
      var seen = stepsWith(t, f, 'opened', a.i).concat(stepsWith(t, f, 'found', a.i));
      if (seen.length) return '<span class="rel">seen at ' + links(seen.sort(function (x, y) { return x.i - y.i; })) + ', not in Localization</span>';
      return '<span class="rel no">never looked at before</span>';
    }
    var ed = stepsWith(t, f, 'edited');
    if (ed.length) return '<span class="rel ok">→ edited at ' + links(ed) + '</span>';
    return '<span class="rel">not edited</span>';
  }
  function fileRows(t, a, files, kind, max) {
    max = max || 8;
    return files.slice(0, max).map(function (f) {
      return '<li><span class="fn" title="' + TV.esc(f) + '">' + TV.esc(TV.fileName(f)) + '</span>' + fileRelation(t, f, a, kind) + '</li>';
    }).join('') + (files.length > max ? '<li class="more">+' + (files.length - max) + ' more</li>' : '');
  }
  /* a test filter without its package: com.foo.BarTest.method -> BarTest.method */
  TV.testName = function (x) {
    x = String(x || '');
    if (/\s/.test(x) || /\.(java|kt|py|sh)$/.test(x)) return x;
    var parts = x.split('.'), k = 0;
    while (k < parts.length - 1 && !/^[A-Z*]/.test(parts[k])) k++;
    return /^[A-Z]/.test(parts[k]) || /^\*\w/.test(parts[k]) ? parts.slice(k).join('.') : x;
  };
  /* the files block of one step: edited here, opened here, listed by a search here, tested here */
  TV.stepFilesHTML = function (t, a) {
    var h = '';
    if (a.edited.length) h += '<div class="tt-k">' + (a.edited.length > 1 ? a.edited.length + ' files edited' : '1 file edited') + '</div><ul class="tt-files">' + fileRows(t, a, a.edited, 'edited') + '</ul>';
    if (a.opened.length) h += '<div class="tt-k">' + (a.category === 'read' ? 'Read' : a.category === 'search' ? 'Searched in' : 'Files') + ' (' + a.opened.length + ')</div><ul class="tt-files">' + fileRows(t, a, a.opened, 'looked') + '</ul>';
    if (a.found.length) {
      var n = a.n_found || a.found.length;
      h += '<div class="tt-k">Found by this search (' + (n > a.found.length ? a.found.length + ' of ' + n : n) + ')</div><ul class="tt-files">' + fileRows(t, a, a.found, 'looked', 6) + '</ul>';
    }
    if (a.tests && a.tests.length) h += '<div class="tt-k">Tests</div><ul class="tt-files">' + a.tests.map(function (x) {
      return '<li><span class="fn" title="' + TV.esc(x) + '">' + TV.esc(TV.testName(x)) + '</span></li>';
    }).join('') + '</ul>';
    return h;
  };
  /* the outcome this one step shows (atif/phase.py step_outcomes), else unchecked */
  TV.stepOutcomeHTML = function (t, a) {
    var o = a.stepOutcome, ev = a.step_evidence, why;
    if (!TV.hasVerdict(a.phase)) return '';
    if (o === 'unchecked') {
      why = a.phase === 'localization' ? (t.targets.files.length ? 'touches no file of the agent\'s patch' : 'no patch to check against') :
        a.category === 'edit' ? (a.attempt && !a.attempt.judge ? 'its attempt was never built or tested' : 'no run judged this edit') : 'no evidence at this step';
    } else if (a.category === 'edit' && a.attempt && a.attempt.judge && a.attempt.judge !== a.i) {
      why = 'judged by #' + a.attempt.judge + (TV.EVIDENCE_SHORT[ev] ? ' (' + TV.EVIDENCE_SHORT[ev] + ')' : '');
    } else {
      why = ev === 'target_file' ? 'touches a file of the agent\'s patch' : TV.EVIDENCE_SHORT[ev] ? 'this ' + TV.EVIDENCE_SHORT[ev] + ' run' : '';
    }
    return '<div class="tt-o"><span class="tt-ok">Step outcome</span><span class="opill mini o-' + o + '">' + o + '</span>' +
      (why ? '<span class="tt-m"> ' + TV.esc(why) + '</span>' : '') + '</div>';
  };

  /* the playbar's phase of the current action: Validation with its outcome, else the phase */
  TV.cursorPhaseHTML = function (a) {
    var s = a.sub;
    if (!s) return '';
    if (!TV.hasVerdict(s.p.phase)) return ' ' + TV.phaseChip(s.p.phase);
    return ' <span class="opill mini o-' + s.outcome + '" data-tip="' + TV.esc(s.p.phase + ' outcome (self-validation): ' + TV.OUTCOME_LABEL[s.outcome]) + '"><span class="ell">' + TV.esc(s.p.phase) + '</span></span>';
  };
  TV.actionTip = function (t, a) {
    var s = a.sub;
    var h = '<div class="tt-h">#' + a.i + ' · ' + TV.esc(a.category) + (a.verdict !== 'none' ? ' <span class="v-' + a.verdict + '">' +
      TV.verdictDot(a.verdict) + TV.VERDICT_WORD[a.verdict] + '</span>' : '') +
      (s ? ' <span class="tt-ph"><i style="background:' + TV.phaseVar(s.p.phase) + '"></i>' + TV.esc(s.p.phase) + '</span>' : '') + '</div>';
    h += '<div class="tt-m">' + TV.esc(a.tool) + (a.scope && a.scope !== 'main' ? ' · sub-agent' : '') + '</div>';
    var tg = a.cmd || a.target;
    var only = a.opened.concat(a.edited);                   // a target that is just the one file listed below is not repeated
    if (tg && !(only.length === 1 && TV.fileName(tg) === TV.fileName(only[0]))) h += '<div class="tt-c">' + TV.esc(TV.shortPaths(tg).slice(0, 160)) + '</div>';
    h += TV.stepFilesHTML(t, a);
    h += TV.stepOutcomeHTML(t, a);
    if (s && TV.hasVerdict(s.p.phase)) h += '<div class="tt-m">' + TV.esc(s.p.phase) + ' outcome (self-validation): ' + s.outcome +
      (TV.EVIDENCE_SHORT[s.evidence] ? ' (' + TV.EVIDENCE_SHORT[s.evidence] + ')' : '') + '</div>';
    if (t.anchor === a.i) h += '<div class="tt-m"><b>first fix</b> (first edit of a source file)</div>';
    if (t.hasTs && !isNaN(a.tms)) h += '<div class="tt-m">+' + TV.fmtDur((a.tms - t.t0) / 1000) + '</div>';
    return h;
  };

  /* a phase span's pop-up: its outcome (Validation: its self-validation; Localization, Repair: the
   * file dots, each file with where it was edited or localized), and the other files of the
   * span (Validation: what the runs tested) */
  TV.phaseTip = function (t, p) {
    var h = '<div class="tt-h"><span class="tt-ph"><i style="background:' + TV.phaseVar(p.phase) + '"></i>' + TV.esc(p.phase) + '</span> #' + p.start + '–#' + p.end +
      ' <span class="muted">· ' + TV.plural(p.end - p.start + 1, 'action') + '</span></div>';
    if (TV.hasVerdict(p.phase)) h += '<div class="tt-o"><span class="tt-ok">Self-validation</span>' + (p.subphases || []).map(function (s) {
      var ev = TV.EVIDENCE_SHORT[s.evidence];
      return '<span class="opill mini o-' + s.outcome + '">' + s.outcome + (ev ? ' · ' + TV.esc(ev) : '') + '</span>';
    }).join('<i class="oh-arr">→</i>') + '</div>';
    var dotted = TV.hasFiles(p.phase) ? TV.spanFiles(t, p) : null;
    if (dotted) h += '<div class="tt-o">' + TV.dotsHTML(dotted) + '<span class="tt-m"> ' + TV.esc(TV.filesSummary(p, dotted)) + '</span></div>' + TV.spanFilesHTML(t, p, 10);
    var acts = t.actions.slice(p.start - 1, p.end);
    function collect(key) {                       // [file, [steps]] in order of first use
      var out = [];
      acts.forEach(function (a) {
        a[key].forEach(function (f) {
          var row = out.filter(function (r) { return TV.sameFile(r[0], f); })[0];
          if (!row) out.push(row = [f, []]);
          if (row[1].indexOf(a) < 0) row[1].push(a);
        });
      });
      return out;
    }
    function rows(list, kind, max) {
      max = max || 10;
      return '<ul class="tt-files">' + list.slice(0, max).map(function (r) {
        var first = r[1][0];
        return '<li><span class="fn" title="' + TV.esc(r[0]) + '">' + TV.esc(TV.fileName(r[0])) + '</span><span class="cnt">' + (r[1].length > 1 ? '×' + r[1].length : '#' + first.i) + '</span>' +
          fileRelation(t, r[0], first, kind) + '</li>';
      }).join('') + (list.length > max ? '<li class="more">+' + (list.length - max) + ' more</li>' : '') + '</ul>';
    }
    var edited = collect('edited'), opened = collect('opened');
    if (edited.length && p.phase !== 'repair') h += '<div class="tt-k">Files edited (' + edited.length + ')</div>' + rows(edited, 'edited');
    if (opened.length && p.phase !== 'localization') h += '<div class="tt-k">Files looked at (' + opened.length + ')</div>' + rows(opened, 'looked', edited.length ? 5 : 10);
    var tests = [];
    acts.forEach(function (a) { (a.tests || []).forEach(function (x) { if (tests.indexOf(x) < 0) tests.push(x); }); });
    if (tests.length) h += '<div class="tt-k">Tests run (' + tests.length + ')</div><ul class="tt-files">' + tests.slice(0, 6).map(function (x) {
      return '<li><span class="fn" title="' + TV.esc(x) + '">' + TV.esc(TV.testName(x)) + '</span></li>';
    }).join('') + '</ul>';
    if (!edited.length && !opened.length && !tests.length) h += '<div class="tt-m">No file named in this phase.</div>';
    return h;
  };
})();
