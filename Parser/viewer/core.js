/* TrajecTiers viewer - shared core for index.html (overview) and bug.html (one bug):
 * helpers, vocabularies and labels (phases, subphase outcomes, categories, flags, badges),
 * theme, tooltip, trajectory preparation (trajview/3), small HTML snippets.
 * Plain script (no modules, no fetch) so that both pages work from file://. */
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
  TV.PHASE_ORDER = ['understanding', 'localization', 'reproduction', 'repair', 'validation'];
  TV.phaseVar = function (p) { return 'var(--p-' + (TV.PHASE_ORDER.indexOf(p) >= 0 ? p : 'other') + ')'; };
  TV.phaseTextVar = function (p) { return 'var(--pt-' + (TV.PHASE_ORDER.indexOf(p) >= 0 ? p : 'other') + ')'; };
  TV.phaseDef = function (p) {
    var x = ((TV.vocab.text || {}).phases || {})[p];
    return x ? p + ': ' + x.doing + ' (' + x.where + ')' : p;
  };
  /* subphase outcomes: one question per stretch, the same in every phase (did its check show
   * that the phase's goal was reached?); atif/phase.py OUTCOMES */
  TV.OUTCOMES = ['succeeded', 'failed', 'blocked', 'unchecked'];
  TV.OUTCOME_GLYPH = { succeeded: '✓', failed: '✗', blocked: '⊘', unchecked: '○' };
  TV.OUTCOME_LABEL = {
    succeeded: 'succeeded: the check in the stretch shows the phase\'s goal was reached',
    failed: 'failed: the check shows the goal was not reached',
    blocked: 'blocked: a check was attempted, but the environment stopped it',
    unchecked: 'unchecked: no check was attempted'
  };
  TV.outcomeOf = function (o) { return TV.OUTCOMES.indexOf(o) >= 0 ? o : 'unchecked'; };
  /* the codebook's meaning of an outcome in one phase (Table 6), else the general label */
  TV.outcomeDef = function (phase, o) {
    var row = ((TV.vocab.text || {}).outcomes || {})[phase];
    if (!row || !row[o] || row[o] === '–') return TV.OUTCOME_LABEL[o] || o;
    return phase + ' ' + o + ': ' + row[o] + ' (check: ' + row.check + ')';
  };
  TV.EVIDENCE = ['test', 'build', 'target_file', 'none'];
  TV.EVIDENCE_LABEL = { test: 'a test run', build: 'a build', target_file: 'the files of the agent\'s patch', none: 'no check' };
  TV.EVIDENCE_SHORT = { test: 'test', build: 'build', target_file: 'patch files', none: '' };
  TV.VERDICT_GLYPH = { pass: '✓', fail: '✗', none: '' };
  TV.FAIL_KINDS = ['test', 'build', 'env', 'exit'];
  TV.FAIL_KIND_LABEL = { test: 'a test ran and failed', build: 'compile / build error', env: 'environment / sandbox', exit: 'other non-zero exit' };
  TV.failGlyphSVG = function (kind, cx, cy, r) {
    var c = 'class="fk fk-' + (kind || 'exit') + '"';
    switch (kind) {
      case 'test': return '<path ' + c + ' d="M' + cx + ' ' + (cy - r) + 'L' + (cx + r) + ' ' + (cy + r * 0.8) + 'L' + (cx - r) + ' ' + (cy + r * 0.8) + 'Z"/>';
      case 'build': return '<rect ' + c + ' x="' + (cx - r * 0.8) + '" y="' + (cy - r * 0.8) + '" width="' + (r * 1.6) + '" height="' + (r * 1.6) + '"/>';
      case 'env': return '<path ' + c + ' d="M' + cx + ' ' + (cy - r) + 'L' + (cx + r) + ' ' + cy + 'L' + cx + ' ' + (cy + r) + 'L' + (cx - r) + ' ' + cy + 'Z"/>';
      default: return '<path ' + c + ' d="M' + (cx - r * 0.75) + ' ' + (cy - r * 0.75) + 'L' + (cx + r * 0.75) + ' ' + (cy + r * 0.75) + 'M' + (cx + r * 0.75) + ' ' + (cy - r * 0.75) + 'L' + (cx - r * 0.75) + ' ' + (cy + r * 0.75) + '"/>';
    }
  };
  /* L1 action categories (Table 2), in vocabulary order, with two-letter abbreviations */
  TV.CATEGORIES = ['read_file', 'search_code', 'orient', 'vcs', 'diff', 'web', 'edit_file', 'shell_edit', 'build', 'run_test',
    'device_ops', 'run_shell', 'env_setup', 'plan', 'delegate', 'wait_process', 'other'];
  TV.CAT_ABBR = { read_file: 'rd', search_code: 'sr', orient: 'or', vcs: 'vc', diff: 'df', web: 'wb', edit_file: 'ed', shell_edit: 'se',
    build: 'bd', run_test: 'rt', device_ops: 'dv', run_shell: 'sh', env_setup: 'en', plan: 'pl', delegate: 'dg', wait_process: 'wt', other: 'ot' };
  TV.catAbbr = function (c) { return TV.CAT_ABBR[c] || String(c || '?').slice(0, 2); };
  TV.catDef = function (c) {
    var x = ((TV.vocab.text || {}).categories || {})[c];
    return x ? c + ' (' + x.family + '): ' + x.does + ' · ' + x.tools : c;
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
  TV.SELF_REPORT_LABEL = {
    reports_failure: 'reports a failure', claims_suite_pass: 'claims the test suite passes', claims_target_pass: 'claims the bug test passes',
    claims_unit_tests: 'claims unit tests pass', claims_build_only: 'claims only that it builds', no_test_claim: 'makes no test claim', empty: 'no final message'
  };

  /* subphase flags (Table 7): a short label; the definition comes from the codebook */
  TV.FLAGS = ['test_modified', 'environment_workaround', 'repeated_failure', 'repeated_reads', 'manual_ui_check'];
  TV.FLAG_INFO = {
    test_modified: ['test modified', 'changes test code or the benchmark\'s test script', 'bad'],
    environment_workaround: ['env workaround', 'changes build files, or changes environment settings and runs again after a failure', 'warn'],
    repeated_failure: ['repeated failure', 'repeats a run that failed, the same way, with nothing changed in between', 'bad'],
    repeated_reads: ['repeated reads', 'reads one file three or more times', 'info'],
    manual_ui_check: ['manual UI check', 'drives the app on a device (taps, screenshots): a check with no automatic result', 'info']
  };
  TV.flagLabel = function (f) { return (TV.FLAG_INFO[f] || [TV.humanize(f)])[0]; };
  TV.flagDef = function (f) {
    var text = ((TV.vocab.text || {}).flags || {})[f] || (TV.FLAG_INFO[f] || [])[1] || TV.humanize(f);
    return f + ': ' + text;
  };
  TV.flagHTML = function (f) {
    return '<span class="flag sev-' + ((TV.FLAG_INFO[f] || [])[2] || 'info') + '" data-tip="' + TV.esc(TV.flagDef(f)) + '">' + TV.esc(TV.flagLabel(f)) + '</span>';
  };
  TV.isProblemSub = function (s) {
    return s.outcome === 'failed' || s.outcome === 'blocked' || s.flags.indexOf('repeated_failure') >= 0 || s.flags.indexOf('test_modified') >= 0;
  };

  /* trajectory-level process badges (atif/outcomes.py phase_badges): plain words, a definition,
   * a severity. Only the ones that hold are shown; "claims pass, harness fails" replaces "claims pass". */
  TV.BADGES = [
    { key: 'claims_but_fails', label: 'claims pass, harness fails', sev: 'bad',
      def: 'The final message claims the tests pass, but the harness outcome is fail.',
      test: function (b, pass) { return !!b.self_claims_pass && pass === false; } },
    { key: 'self_claims_pass', label: 'claims tests pass', sev: 'info',
      def: 'The final message claims the bug test or the suite passes.',
      test: function (b, pass) { return !!b.self_claims_pass && pass !== false; } },
    { key: 'reproduced_before_fix', label: 'reproduced first', sev: 'good',
      def: 'A Reproduction subphase succeeded: the bug\'s test failed as reported before the first fix.',
      test: function (b) { return !!b.reproduced_before_fix; } },
    { key: 'test_modified', label: 'modified tests', sev: 'bad',
      def: 'A subphase changes test code or the benchmark\'s test script (flag test_modified).',
      test: function (b) { return !!b.test_modified; } },
    { key: 'repeated_failure', label: 'repeated failure', sev: 'bad',
      def: 'A subphase repeats a failed run the same way, with nothing changed in between (flag repeated_failure).',
      test: function (b) { return !!b.repeated_failure; } },
    { key: 'blocked_checks', label: 'blocked checks', sev: 'warn',
      def: 'Subphases whose check the environment stopped (outcome blocked).',
      test: function (b) { return (b.blocked_checks || 0) > 0; },
      text: function (b) { return 'blocked checks: ' + b.blocked_checks; } },
    { key: 'patch_unchecked', label: 'final change never run', sev: 'warn',
      def: 'The last Repair subphase is unchecked: the final change was never built or tested.',
      test: function (b) { return b.final_repair_outcome === 'unchecked'; } },
    { key: 'build_only', label: 'final check: build only', sev: 'info',
      def: 'The last Repair subphase succeeded on a build, not a test: the patch compiles, but no test judged it.',
      test: function (b) { return b.final_repair_outcome === 'succeeded' && b.final_repair_evidence === 'build'; } },
    { key: 'last_test_fail', label: 'last test failed', sev: 'warn',
      def: 'The last test run in the trajectory failed.',
      test: function (b) { return b.last_test_verdict === 'fail'; } }
  ];
  TV.badgesFor = function (badges, pass) {
    badges = badges || {};
    return TV.BADGES.filter(function (x) { return x.test(badges, pass); });
  };
  TV.badgeHTML = function (badges, pass) {
    return TV.badgesFor(badges, pass).map(function (x) {
      return '<span class="badge sev-' + x.sev + '" data-tip="' + TV.esc(x.def) + '">' + TV.esc(x.text ? x.text(badges) : x.label) + '</span>';
    }).join('');
  };

  /* ------------------------------------------------------------------ snippets */
  TV.agentHTML = function (a, extra) {
    return '<span class="agent"><i class="adot ' + TV.esc(a) + '" aria-hidden="true"></i>' + TV.esc(a) + (extra || '') + '</span>';
  };
  TV.oc = function (pass) { return pass === true ? 'pass' : pass === false ? 'fail' : 'unknown'; };
  TV.markHTML = function (pass, tip) {
    var oc = TV.oc(pass);
    return '<span class="mark ' + oc + '"' + (tip ? ' data-tip="' + TV.esc(tip) + '"' : '') + ' aria-label="' + oc + '">' +
      (oc === 'pass' ? '✓' : oc === 'fail' ? '✗' : '?') + '</span>';
  };
  TV.passPill = function (pass) {
    var oc = TV.oc(pass);
    return '<span class="tpill ' + oc + '" data-tip="Harness outcome: the patched app was built and the bug test run">' +
      (oc === 'pass' ? '✓ pass' : oc === 'fail' ? '✗ fail' : '? no outcome') + '</span>';
  };
  /* three small dots for runs 1..3: filled = pass, ring = fail, grey ring = no outcome */
  TV.runDots = function (byRun, runs, cur, agent) {
    runs = runs || [1, 2, 3];
    var desc = runs.map(function (r) { return 'run ' + r + ': ' + TV.oc((byRun || {})[r]); }).join(', ');
    return '<span class="rdots" data-tip="' + TV.esc((agent ? agent + ' · ' : '') + desc) + '" aria-label="' + TV.esc(desc) + '">' + runs.map(function (r) {
      return '<i class="rdot ' + TV.oc((byRun || {})[r]) + (r === cur ? ' cur' : '') + '"></i>';
    }).join('') + '</span>';
  };
  /* strips: pieces placed by action index (left / width in % of n), so a phase strip and the
   * subphase-outcome strip under it line up exactly; a 1px surface gap separates pieces */
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
  /* subphase-outcome strip from [[outcome, start, end, phase, evidence], ...] (one piece per subphase) */
  TV.subStripHTML = function (subStrip, n, ref, cls) {
    var w = ref ? Math.max(2, 100 * n / ref) : 100, N = stripN(subStrip, n);
    return '<span class="strip outs' + (cls ? ' ' + cls : '') + '" style="width:' + w.toFixed(1) + '%">' + (subStrip || []).map(function (p) {
      var o = TV.outcomeOf(p[0]), ev = TV.EVIDENCE_SHORT[p[4]];
      return piece(p, N, '', 'o-' + o, (p[3] ? p[3] + ' · ' : '') + TV.OUTCOME_GLYPH[o] + ' ' + o + (ev ? ' (' + ev + ')' : ''));
    }).join('') + '</span>';
  };
  /* phase strip with the subphase-outcome strip under it, both scaled to n / ref */
  TV.stripsHTML = function (strip, subStrip, n, ref) {
    var w = ref ? Math.max(2, 100 * n / ref) : 100;
    if (!subStrip || !subStrip.length) return TV.stripHTML(strip, n, ref, 'tall');
    return '<span class="strips" style="width:' + w.toFixed(1) + '%">' + TV.stripHTML(strip, n, 0, 'tall') + TV.subStripHTML(subStrip, n, 0) + '</span>';
  };
  TV.phaseChip = function (p) {
    return '<span class="pchip" data-tip="' + TV.esc(TV.phaseDef(p)) + '"><i style="background:' + TV.phaseVar(p) + '"></i>' + TV.esc(p) + '</span>';
  };
  /* outcome pill; phase = give the codebook's meaning in that phase, ev = the evidence */
  TV.outcomePill = function (o, text, phase, ev) {
    o = TV.outcomeOf(o);
    var evs = ev && TV.EVIDENCE_SHORT[ev];
    return '<span class="opill o-' + o + '" data-tip="' + TV.esc(phase ? TV.outcomeDef(phase, o) : TV.OUTCOME_LABEL[o]) +
      (evs ? TV.esc(' · evidence: ' + TV.EVIDENCE_LABEL[ev]) : '') + '"><b aria-hidden="true">' +
      TV.OUTCOME_GLYPH[o] + '</b>' + TV.esc(text != null ? text : o) + (evs ? '<span class="ev"> · ' + TV.esc(evs) + '</span>' : '') + '</span>';
  };
  TV.phaseLegend = function (used) {
    return TV.PHASE_ORDER.filter(function (p) { return !used || used[p]; }).map(TV.phaseChip).join('');
  };
  /* legend chips: the same solid fills the strips and bars use; used = {outcome: 1} limits them */
  TV.outcomeLegend = function (used) {
    return TV.OUTCOMES.filter(function (o) { return !used || used[o]; }).map(function (o) { return TV.outcomePill(o); }).join('');
  };

  /* ------------------------------------------------------------------ rules (atif/rules.py) */
  /* a custom rule in plain words; the same sentence as rules.describe() */
  TV.ruleSentence = function (r) {
    var how = r.regex ? 'matches' : 'contains', q = '“' + (r.match || '…') + '”';
    if (r.kind === 'file_role') return 'Files whose path ' + how + ' ' + q + ' are ' + r.value + ' files.';
    var subject = { target: 'Actions whose command or target', tool: 'Actions whose tool name', any: 'Actions whose tool, command or target' }[r.field || 'target'];
    if (r.kind === 'category') return subject + ' ' + how + ' ' + q + ' count as ' + r.value + '.';
    if (r.value === 'follow') return subject + ' ' + how + ' ' + q + ' follow the work around them.';
    return subject + ' ' + how + ' ' + q + ' belong to ' + r.value + '.';
  };
  /* read-only list (Rules popover): the mandatory rules, the optional rules that are added
   * (vocab.rules), and, when the data was built with a rule set, the custom ones
   * (vocab.custom_rules). Data of the first rule format has no mandatory flag: all listed. */
  TV.rulesListHTML = function (builtin, custom) {
    function list(rules, locked) {
      return '<ol class="rulelist">' + rules.map(function (r) {
        return '<li class="rule"><span class="rid">' + TV.esc(r.id) + '</span><span class="rtext">' + (r.title ? '<b>' + TV.esc(r.title) + '.</b> ' : '') +
          TV.esc(r.sentence || r.text || TV.ruleSentence(r)) + (locked ? ' <span class="fixed" data-tip="mandatory: always applied; it cannot be switched off or removed">required</span>' : '') + '</span></li>';
      }).join('') + '</ol>';
    }
    builtin = builtin || [];
    var must = builtin.filter(function (r) { return r.mandatory === true || !('mandatory' in r); });
    var opt = builtin.filter(function (r) { return r.mandatory === false && r.on; });
    var h = '<h3 class="rl-h">Mandatory rules</h3>' + list(must, true) +
      '<h3 class="rl-h">Optional rules</h3>' + (opt.length ? list(opt) : '<p class="muted small">None added.</p>');
    if (custom && custom.length) h += '<h3 class="rl-h">Custom rules</h3>' + list(custom.filter(function (r) { return r.enabled !== false; }));
    return h;
  };

  /* ------------------------------------------------------------------ logo */
  /* TrajecTiers mark: three tiers (phases, subphases, actions), each finer than the one above,
   * crossed by the trajectory arc. Same geometry as logo.svg (the favicon), but themed with CSS vars. */
  var LOGO_TOP = [[3, 5, 'understanding'], [9, 6, 'localization'], [16, 8, 'repair'], [25, 4, 'validation']];
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
    /* Rules popover: the built-in rules of the loaded data, in plain words */
    TV.$$('[data-rules-btn]').forEach(function (b) {
      b.addEventListener('click', function () {
        if (!pop) return;
        var rules = (TV.vocab || {}).rules;
        TV.$('#rulesBody').innerHTML = rules && rules.length ? TV.rulesListHTML(rules, TV.vocab.custom_rules) :
          '<p class="note">This data was built before the rules were exported. Regenerate it: <code>python3 -m atif.cli view --all</code></p>';
        pop.hidden = !pop.hidden;
        if (help) help.hidden = true;
      });
    });
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
      var w = tipEl.offsetWidth, h = tipEl.offsetHeight;
      var x = ev.clientX + 14, y = ev.clientY + 16;
      if (x + w > window.innerWidth - 8) x = ev.clientX - w - 12;
      if (y + h > window.innerHeight - 8) y = ev.clientY - h - 12;
      tipEl.style.left = Math.max(4, x) + 'px';
      tipEl.style.top = Math.max(4, y) + 'px';
    },
    hide: function () { if (tipEl) tipEl.hidden = true; }
  };
  /* any element with data-tip gets a hover tooltip (text, escaped) */
  var tipOwner = null;
  document.addEventListener('mouseover', function (ev) {
    var el = ev.target.closest && ev.target.closest('[data-tip]');
    if (el === tipOwner) return;
    tipOwner = el;
    if (el) TV.tip.show(TV.esc(el.getAttribute('data-tip')), ev); else TV.tip.hide();
  });
  document.addEventListener('mousemove', function (ev) { if (tipOwner) TV.tip.move(ev); });
  document.addEventListener('scroll', function () { if (tipOwner) { tipOwner = null; TV.tip.hide(); } }, true);

  /* ------------------------------------------------------------------ trajectory preparation (trajview/3) */
  /* links the levels: t.phases (spans) -> s.subphases; t.subs = every subphase in action order;
   * each action gets a.sub, a.span and a.attempt (the repair attempt whose range holds it) */
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
      a.attempt = attAt[a.i] || null;
      a.tms = a.ts ? Date.parse(a.ts) : NaN;
      if (!isNaN(a.tms)) tsOk++;
    });
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
  /* what an action is to its attempt: "edit", "judging run" or "" */
  TV.attemptRole = function (a) {
    var at = a.attempt;
    if (!at) return '';
    if (at.edits.indexOf(a.i) >= 0) return 'edit';
    return at.judge === a.i ? 'judging run' : 'between';
  };

  /* the details panel's body for one action (bug page and Analyze page) */
  TV.actionDetailsHTML = function (t, a) {
    var s = a.sub, p = a.span, at = a.attempt, h = '';
    h += '<div class="dt-row"><span class="midchip" data-tip="' + TV.esc(TV.catDef(a.category)) + '">' + TV.esc(a.category) + '</span><b>' + TV.esc(a.tool) + '</b>' +
      (a.scope && a.scope !== 'main' ? '<span class="tag" data-tip="' + TV.esc(a.scope) + '">sub-agent</span>' : '') +
      (a.verdict !== 'none' ? '<span class="vg v-' + a.verdict + '">' + TV.VERDICT_GLYPH[a.verdict] + ' ' + a.verdict +
        (a.fail_kind ? ' · ' + TV.esc(TV.FAIL_KIND_LABEL[a.fail_kind] || a.fail_kind) : '') + '</span>' : '') +
      (a.failed_raw && a.verdict !== 'fail' ? '<span class="tag" data-tip="the log marks this tool call as an error">log error</span>' : '') +
      (a.file_role ? '<span class="tag" data-tip="file role (codebook Table 3) of the files this action touches">' + TV.esc(a.file_role) + '</span>' : '') +
      (a.reverts ? '<span class="tag" data-tip="undoes earlier changes (git checkout / restore / stash / reset)">reverts</span>' : '') +
      (t.anchor === a.i ? '<span class="tag" data-tip="the first edit of app source: understanding and reproduction happen only before it, repair and validation only from it on">first fix</span>' : '') +
      (a.rules || []).map(function (r) { return '<span class="tag rule" data-tip="' + TV.esc('your rule ' + r.id + ': ' + r.sentence) + '">rule ' + TV.esc(r.id) + '</span>'; }).join('') + '</div>';
    if (a.target) h += '<div class="dt-k">Target</div><pre class="dt-code">' + TV.esc(a.target) + '</pre>';
    if (a.cmd) h += '<div class="dt-k">Command</div><pre class="dt-code">' + TV.esc(a.cmd) + '</pre>';
    if (a.edits && a.edits.length) h += '<div class="dt-k">Edits</div><pre class="dt-code">' + TV.esc(a.edits.join('\n')) + '</pre>';
    h += '<div class="dt-k">' + (a.thought_source === 'reasoning' ? 'Thought (reasoning)' : a.thought_source === 'narration' ? 'Thought (narration)' : 'Thought') + '</div>' +
      '<div class="dt-text">' + (a.thought ? TV.esc(a.thought) : '<span class="muted">(none)</span>') + '</div>';
    h += '<div class="dt-k">Result</div><pre class="dt-code">' + (a.result ? TV.esc(a.result) : '<span class="muted">(empty)</span>') + '</pre>';
    if (p) h += '<div class="dt-k">Phase</div><div class="dt-row">' + TV.phaseChip(p.phase) + '<span class="muted small">#' + p.start + '–#' + p.end + ' · ' + (a.i < (t.anchor || Infinity) ? 'before' : 'after') + ' the first fix</span>' +
      (a.own_phase ? '<span class="muted small" data-tip="its phase before G7: a single row between two stretches of one phase joins them">· own phase ' + TV.esc(a.own_phase) + '</span>' : '') + '</div>';
    if (s) {
      h += '<div class="dt-k">Subphase</div><div class="dt-seg">' + TV.outcomePill(s.outcome, null, p.phase, s.evidence) +
        ' <span class="muted small">#' + s.start + '–#' + s.end + ' · ' + TV.plural(s.n_actions, 'action') +
        (s.n_attempts ? ' · ' + TV.plural(s.n_attempts, 'attempt') : s.n_events ? ' · ' + TV.plural(s.n_events, 'check') : '') + '</span>' +
        '<div class="dt-text">' + TV.esc(TV.outcomeDef(p.phase, s.outcome)) + '</div>' +
        (s.flags.length ? '<div class="badges">' + s.flags.map(TV.flagHTML).join('') + '</div>' : '') + '</div>';
    }
    if (at) {
      var role = TV.attemptRole(a);
      h += '<div class="dt-k">Repair attempt</div><div class="attline o-' + at.outcome + '">⟲ attempt ' + at.id + ' #' + at.start + '–#' + at.end + ' · ' + TV.plural(at.edits.length, 'edit') +
        ' · ' + (at.judge ? 'judged by #' + at.judge + ': <b>' + TV.OUTCOME_GLYPH[at.outcome] + ' ' + at.outcome + '</b>' + (TV.EVIDENCE_SHORT[at.evidence] ? ' (' + TV.esc(TV.EVIDENCE_LABEL[at.evidence]) + ')' : '') : '<b>never run</b>') +
        (role !== 'between' ? ' · this action is its ' + role : '') + '</div>';
    }
    h += '<div class="dt-meta">step ' + TV.esc(a.step) + (a.ts ? ' · ' + TV.esc(a.ts) : '') + (a.call_id ? '<br>call ' + TV.esc(a.call_id) : '') + '</div>';
    return h;
  };

  TV.actionTip = function (t, a) {
    var s = a.sub;
    var h = '<div class="tt-h">#' + a.i + ' · ' + TV.esc(a.category) + (a.verdict !== 'none' ? ' <span class="v-' + a.verdict + '">' +
      TV.VERDICT_GLYPH[a.verdict] + ' ' + a.verdict + (a.fail_kind ? ' (' + TV.esc(a.fail_kind) + ')' : '') + '</span>' : '') + '</div>';
    h += '<div class="tt-m">' + TV.esc(a.tool) + (a.scope && a.scope !== 'main' ? ' · sub-agent' : '') + (a.file_role ? ' · ' + TV.esc(a.file_role) : '') + '</div>';
    if (a.target) h += '<div class="tt-c">' + TV.esc(a.target.slice(0, 160)) + '</div>';
    if (s) h += '<div class="tt-m">' + TV.esc(s.p.phase) + ' · ' + TV.OUTCOME_GLYPH[s.outcome] + ' ' + s.outcome +
      (TV.EVIDENCE_SHORT[s.evidence] ? ' (' + TV.EVIDENCE_SHORT[s.evidence] + ')' : '') +
      (a.own_phase ? ' · own phase ' + TV.esc(a.own_phase) : '') + '</div>';
    if (a.attempt) h += '<div class="tt-m">attempt ' + a.attempt.id + (TV.attemptRole(a) !== 'between' ? ': ' + TV.attemptRole(a) : '') + '</div>';
    if (t.anchor === a.i) h += '<div class="tt-m"><b>first fix</b> (first edit of app source)</div>';
    if (t.hasTs && !isNaN(a.tms)) h += '<div class="tt-m">+' + TV.fmtDur((a.tms - t.t0) / 1000) + '</div>';
    return h;
  };
})();
