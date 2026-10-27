/* Inceptor dashboard - the user's uploaded trajectories (needs engine.js).
 *
 * An upload is one log (or ATIF file) the user added. It is kept in this browser only
 * (IndexedDB: 'uploads' holds the record and its analysis, 'texts' the file itself and, under
 * '<id>|atif', the trajectory as ATIF for the details panel's full texts and raw JSON) and is
 * analysed again whenever the rule set changes, so uploads and corpus always share one rule
 * set. Record: {id, name, size, added, hash (of the text, to find a file uploaded twice), bug
 * (the user's or the folder's bug id, or null: inferred), agentName (the folder's agent, or
 * absent: the log's), slot (its run in the corpus table, or absent: after the cell's last run),
 * outcome (true | false | null), dataset (the uploaded folder's name), path (the file's path in
 * it), rulesKey, result (atif.upload.request: trajectory, vocab, rules, source, warnings,
 * unrecognized), group ({id, kind, name} when it belongs to a comparison set up on upload.html,
 * else absent), run (its run number in a 'runs' group)}. A group is 'agents' (one bug, several
 * agents) or 'runs' (one agent's runs of one bug); it exists only through its members' records.
 *
 * The corpus table (TV.uploads.layout) places every upload in the cell of its bug and agent,
 * beside the corpus's runs: a new agent is a new column, a new bug a new row. A folder upload
 * (TV.uploads.scan) reads its layout <dataset>/<bug>/<agent>/run<n>/<files>, with an optional
 * CSV of outcomes (bug, agent, outcome; TV.uploads.readOutcomes). TV.uploads.summary(rec)
 * gives the overview's summary form of a record, so the corpus page and the statistics treat
 * it like a corpus trajectory.
 *
 * The example dataset (TV.uploads.seed): the first time this browser lists the uploads, the
 * runs of Dataset/demo/dataset1 (25 bugs, 3 agents, 3 runs; make_seed.py analysed them under
 * the default tables) are added as if that folder had been uploaded, before any upload of the
 * user's. They are ordinary records from then on (deleted like any upload, analysed again
 * under other tables), with .seed: their file under data/seed/, which holds the log and its
 * ATIF and is fetched only when needed. Once added they are not added again unless the user
 * asks (the empty Corpus Overview offers it). */
(function () {
  'use strict';
  var TV = window.TV;

  function mine(msg) { return Object.assign(new Error(msg), { answered: true }); }   // not the engine's fault
  /* the time of an upload, strictly after the one before (a folder's runs keep their order) */
  var lastAdded = 0;
  function addedNow() { lastAdded = Math.max(Date.now(), lastAdded + 1); return new Date(lastAdded).toISOString(); }
  function newId() { return 'u' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }
  function byAdded(a, b) { return String(b.added).localeCompare(String(a.added)); }
  function request(rec, text, rs, atif) {
    return TV.engine.analyze({ name: rec.name, text: text, rules: rs, bug: rec.bug || null, outcome: rec.outcome, atif: !!atif });
  }
  function atifKey(id) { return id + '|atif'; }
  /* a short fingerprint of a text (FNV-1a and the length): the same file uploaded twice */
  function hashText(text) {
    var h = 0x811c9dc5;
    for (var i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 0x01000193); }
    return (h >>> 0).toString(16) + '-' + text.length;
  }
  function cellKey(bug, agent) { return bug + '\u0001' + agent; }
  /* the example dataset: its runs before every upload (added from SEED_AT on), in its order */
  var SEED_DIR = 'data/seed/', SEED_NAME = 'dataset1', SEED_AT = Date.parse('2000-01-01T00:00:00Z'), seeding = null;
  function seedFlag() { return 'seeded|' + SEED_NAME; }
  /* a seed record's log and ATIF ({text, atif}), kept in this browser once fetched */
  function seedFile(rec) {
    return TV.fetchGz(SEED_DIR + rec.seed).then(function (x) {
      var keep = function () { return x; };
      return TV.idb.putAll('texts', [[rec.id, x.text], [atifKey(rec.id), x.atif || null]]).then(keep, keep);
    });
  }
  /* the file of a record: kept since its upload, else (an example run) fetched */
  function textOf(rec) {
    return TV.idb.get('texts', rec.id).then(function (text) {
      if (text == null && rec.seed) return seedFile(rec).then(function (x) { return x.text; });
      if (text == null) throw mine('the file of ' + rec.name + ' is no longer stored');
      return text;
    });
  }
  /* a CSV line into its fields ("a,""b"",c" quotes allowed) */
  function csvFields(line) {
    var out = [], cur = '', q = false;
    for (var i = 0; i < line.length; i++) {
      var c = line[i];
      if (q) { if (c === '"' && line[i + 1] === '"') { cur += '"'; i++; } else if (c === '"') q = false; else cur += c; }
      else if (c === '"') q = true;
      else if (c === ',' || c === ';' || c === '\t') { out.push(cur.trim()); cur = ''; }
      else cur += c;
    }
    out.push(cur.trim());
    return out;
  }
  function passOf(v) {
    v = String(v == null ? '' : v).trim().toLowerCase();
    if (/^(1|true|pass|passed|yes|y|success|resolved|ok)$/.test(v)) return true;
    if (/^(0|false|fail|failed|no|n|failure|unresolved|error)$/.test(v)) return false;
    return null;
  }
  /* which files of a run folder to try, in order: the log formats first, the largest first;
   * a .meta.json last (it describes a run, it is not one) */
  var TRY_EXT = { jsonl: 0, ndjson: 0, traj: 0, json: 1, log: 2, txt: 3, md: 3, markdown: 3 };
  function tryRank(f) {
    var ext = (/\.([a-z0-9]+)$/i.exec(f.name) || [])[1], r = TRY_EXT[(ext || '').toLowerCase()];
    return /\.meta\.json$/i.test(f.name) ? 9 : r == null ? -1 : r;
  }

  TV.uploads = {
    /* every record, newest first; [] where the browser keeps nothing */
    list: function () {
      return TV.uploads.seed().catch(function () { /* no example here (file://, offline): the uploads only */ }).then(function () {
        return TV.idb.all('uploads');
      }).then(function (xs) { return xs.sort(byAdded); }, function () { return []; });
    },
    /* add the example dataset's runs (see the top): once per browser, or again when `again`
     * (only the runs whose file and place in the table no upload holds). Resolves the number
     * of runs added */
    seed: function (again) {
      if (seeding && !again) return seeding;
      var p = (again ? Promise.resolve(null) : TV.idb.get('cache', seedFlag())).then(function (done) {
        if (done) return 0;
        return Promise.all([TV.fetchGz(SEED_DIR + SEED_NAME + '.json.gz'), TV.idb.all('uploads')]).then(function (x) {
          var pack = x[0], recs = x[1] || [], L = TV.uploads.layout(null, recs), hashes = {}, pairs = [];
          var rk = TV.ruleset.key(TV.ruleset.clean(null));
          recs.forEach(function (r) { hashes[r.hash] = 1; });
          (pack.runs || []).forEach(function (s, k) {
            var bug = TV.bugKey(s.bug), agent = TV.normAgent(s.agent), c = L.cells[cellKey(bug, agent)];
            if (hashes[s.hash] || (c && c.runs[s.run])) return;
            var rec = { id: 's-' + SEED_NAME + '-' + bug + '-' + agent + '-' + s.run, name: s.name, size: s.size,
              added: new Date(SEED_AT + k).toISOString(), hash: s.hash, bug: bug, outcome: s.outcome == null ? null : s.outcome,
              agentName: s.agent, slot: s.run, dataset: pack.dataset || SEED_NAME, path: s.path, seed: s.file,
              result: s.result, rulesKey: rk };
            pairs.push([rec.id, rec]);
          });
          return (pairs.length ? TV.idb.putAll('uploads', pairs) : Promise.resolve()).then(function () {
            return TV.idb.put('cache', seedFlag(), { runs: pairs.length, at: new Date().toISOString() });
          }).then(function () { return pairs.length; });
        });
      });
      if (!again) seeding = p;
      return p;
    },
    get: function (id) { return TV.idb.get('uploads', id); },
    /* analyse a File under the rule set and keep it; opts: bug (the bug id to read its paths
     * against), agent, slot, outcome, dataset, path (a folder upload's). Rejects with the
     * engine's message */
    add: function (file, rs, opts) {
      rs = rs || TV.ruleset.get();
      opts = opts || {};
      var info = TV.engine.info;
      if (info && file.size > info.max_bytes) return Promise.reject(mine('larger than ' + Math.round(info.max_bytes / 1048576) + ' MB'));
      return file.text().then(function (text) {
        var rec = { id: newId(), name: file.name, size: file.size, added: addedNow(), hash: hashText(text),
          bug: opts.bug || null, outcome: opts.outcome == null ? null : opts.outcome };
        if (opts.agent) rec.agentName = opts.agent;
        if (opts.slot) rec.slot = opts.slot;
        if (opts.dataset) rec.dataset = opts.dataset;
        if (opts.path) rec.path = opts.path;
        return request(rec, text, rs, true).then(function (res) {
          var atif = res.atif;
          delete res.atif;
          rec.result = res;
          rec.rulesKey = TV.ruleset.key(rs);
          return TV.idb.put('texts', rec.id, text).then(function () { return TV.idb.put('texts', atifKey(rec.id), atif || null); })
            .then(function () { return TV.idb.put('uploads', rec.id, rec); })
            .then(function () { return rec; }, function () {
              throw mine('this browser keeps no data for this page (a private window?), so the upload cannot be kept');
            });
        });
      });
    },
    /* analyse a record again (new rules or a new bug id) and keep the result */
    reanalyze: function (rec, rs) {
      rs = rs || TV.ruleset.get();
      return textOf(rec).then(function (text) {
        return request(rec, text, rs);
      }).then(function (res) {
        rec.result = res;
        rec.rulesKey = TV.ruleset.key(rs);
        return TV.idb.put('uploads', rec.id, rec).then(function () { return rec; });
      });
    },
    /* the records analysed under another rule set, analysed again; onProgress(done, total) */
    refresh: function (recs, rs, onProgress) {
      rs = rs || TV.ruleset.get();
      var key = TV.ruleset.key(rs), stale = recs.filter(function (r) { return r.rulesKey !== key; }), done = 0, failed = [];
      if (!stale.length) return Promise.resolve({ done: 0, failed: [] });
      if (onProgress) onProgress(0, stale.length);
      return stale.reduce(function (p, rec) {
        return p.then(function () {
          return TV.uploads.reanalyze(rec, rs).catch(function (err) {
            if (!err.answered) throw err;                 // the engine cannot run: stop
            failed.push({ rec: rec, error: err.message });
          }).then(function () { done++; if (onProgress) onProgress(done, stale.length); });
        });
      }, Promise.resolve()).then(function () { return { done: done, failed: failed }; });
    },
    /* the external validation the user knows; no re-analysis needed (only the outcome changes) */
    setOutcome: function (rec, pass) {
      rec.outcome = pass;
      var t = rec.result && rec.result.trajectory;
      if (t) t.outcome = { pass: pass, by_run: { 1: pass } };
      return TV.idb.put('uploads', rec.id, rec).then(function () { return rec; });
    },
    hash: hashText,
    save: function (rec) { return TV.idb.put('uploads', rec.id, rec).then(function () { return rec; }); },
    /* the comparison groups among records: [{id, kind, name, members}] (members: runs by run
     * number, agents in the corpus order), newest first */
    groups: function (recs) {
      var by = {}, out = [];
      recs.forEach(function (r) {
        if (!r.group || !r.group.id) return;
        var g = by[r.group.id];
        if (!g) { g = by[r.group.id] = { id: r.group.id, kind: r.group.kind, name: r.group.name, members: [] }; out.push(g); }
        g.members.push(r);
      });
      out.forEach(function (g) {
        g.members.sort(g.kind === 'runs' ? function (a, b) { return (a.run || 0) - (b.run || 0); } : function (a, b) {
          var x = TV.AGENT_ORDER.indexOf(TV.uploads.agent(a)), y = TV.AGENT_ORDER.indexOf(TV.uploads.agent(b));
          return (x < 0 ? 99 : x) - (y < 0 ? 99 : y) || String(a.name).localeCompare(b.name);
        });
      });
      return out;
    },
    /* a record's agent: the folder's name for it, else the log's, matched to the known agents */
    agent: function (rec) {
      var t = (rec.result || {}).trajectory || {};
      return TV.normAgent(rec.agentName || t.agent || ((rec.result || {}).source || {}).agent) || '?';
    },
    /* a record's bug key (TV.bugKey): the user's or the folder's, else the one found in the log; '' when none */
    bug: function (rec) {
      var res = rec.result || {};
      return TV.bugKey(rec.bug || (res.source || {}).bug || (res.trajectory || {}).bug);
    },
    model: function (rec) { var t = (rec.result || {}).trajectory || {}; return t.model || ((rec.result || {}).source || {}).model || ''; },
    /* a member's name in its group: "run 2", or its agent (with the model or the file name when
     * two members share the agent) */
    memberLabel: function (rec, members) {
      if (rec._bugRun) return TV.uploads.agent(rec) + ' · run ' + rec._bugRun;     // a bug's uploads (TV.uploads.bugGroup)
      if (rec.group && rec.group.kind === 'runs') return 'run ' + (rec.run || '?');
      var a = TV.uploads.agent(rec), twins = (members || []).filter(function (r) { return TV.uploads.agent(r) === a; });
      if (twins.length < 2) return a;
      var m = TV.uploads.model(rec), sameModel = twins.filter(function (r) { return TV.uploads.model(r) === m; }).length > 1;
      return a + ' · ' + (m && !sameModel ? m : rec.name);
    },
    KINDS: { agents: 'One bug, several agents', runs: 'One agent, several runs', bug: 'Every upload of this bug' },
    remove: function (ids) {
      return Promise.all(ids.map(function (id) {
        return TV.idb.del('uploads', id).then(function () { return TV.idb.del('texts', id); }).then(function () { return TV.idb.del('texts', atifKey(id)); });
      }));
    },
    /* the record's trajectory as ATIF: kept since its upload, else converted again (once) */
    atif: function (rec) {
      return TV.idb.get('texts', atifKey(rec.id)).then(function (x) {
        if (x) return x;
        if (rec.seed) return seedFile(rec).then(function (f) { return f.atif; });
        return textOf(rec).then(function (text) {
          return request(rec, text, TV.ruleset.get(), true);
        }).then(function (res) {
          return TV.idb.put('texts', atifKey(rec.id), res.atif).then(function () { return res.atif; }, function () { return res.atif; });
        });
      });
    },
    /* the overview's summary form (atif/view.py summary_view) of a record's trajectory */
    summary: function (rec) {
      var t = rec.result.trajectory, byPhase = {}, byOutcome = {};
      var strip = [], sub = [];
      (t.phases || []).forEach(function (p) {
        strip.push([p.phase, p.start, p.end]);
        (p.subphases || []).forEach(function (s) {
          sub.push([s.outcome, s.start, s.end, p.phase, s.evidence]);
          var row = byPhase[p.phase] || (byPhase[p.phase] = {});
          row[s.outcome] = (row[s.outcome] || 0) + 1;
          byOutcome[s.outcome] = (byOutcome[s.outcome] || 0) + 1;
        });
      });
      return { id: rec.id, upload: rec, agent: TV.uploads.agent(rec), bug: TV.uploads.bug(rec) || null, model: t.model, pass: rec.outcome,
        project: TV.uploads.project(rec),
        n_actions: t.n_actions, n_steps: t.n_steps, strip: strip, sub_strip: sub, stats: t.stats || {},
        badges: t.badges || {}, metrics: t.metrics || {}, subphases: { by_outcome: byOutcome, by_phase: byPhase } };
    },
    /* the kind of project a record works on, as the engine read it: 'swebench' (a Python
     * repository: paths and tests are read by Python's conventions) or 'android' */
    project: function (rec) {
      var res = rec.result || {};
      return (res.trajectory || {}).project || (res.source || {}).project || 'android';
    },
    /* a bug in words: bug-<n>, or the name as it is */
    bugLabel: function (bug) { return TV.bugName(TV.bugKey(bug)); },

    /* ------------------------------------------------------------ the corpus table */
    /* every (bug, agent) cell of the corpus table with its runs: the corpus's (D:
     * data/overview.js), then the uploads, oldest first. An upload with a slot sits at that
     * run (over the corpus's run there: the user chose to replace it); one without, after the
     * cell's last run. A record with no bug gets a row of its own ('~<id>').
     *   {cells: {key: {bug, agent, runs: {run: {pass, rec (null: the corpus)}}}},
     *    at: {record id: {bug, agent, run}}, agents: [the uploads' agents the corpus lacks]} */
    layout: function (D, recs) {
      var L = { cells: {}, at: {}, agents: [] }, AG = (D && D.agents) || TV.AGENT_ORDER, RUNS = (D && D.runs) || [1, 2, 3], RUN = (D && D.run) || 1;
      ((D && D.bugs) || []).forEach(function (b) {
        AG.forEach(function (a) {
          var t = (b.agents || {})[a], br = (b.by_run || b.byRun || {})[a] || (t && t.by_run);
          if (!t && !br) return;
          var c = TV.uploads.cell(L, String(b.bug), a);
          RUNS.forEach(function (r) {
            var pass = (br || {})[r];
            if (pass == null && r === RUN && t) pass = t.pass;
            c.runs[r] = { pass: pass == null ? null : pass, rec: null };
          });
        });
      });
      var sorted = (recs || []).slice().sort(function (a, b) { return String(a.added).localeCompare(String(b.added)); });
      function put(rec, run) {
        var bug = TV.uploads.bug(rec) || '~' + rec.id, a = TV.uploads.agent(rec), c = TV.uploads.cell(L, bug, a);
        if (run == null) run = TV.uploads.nextRun(L, bug, a);
        c.runs[run] = { pass: rec.outcome == null ? null : rec.outcome, rec: rec };
        L.at[rec.id] = { bug: bug, agent: a, run: run };
        if (AG.indexOf(a) < 0 && L.agents.indexOf(a) < 0) L.agents.push(a);
      }
      sorted.forEach(function (r) { if (r.slot) put(r, r.slot); });
      sorted.forEach(function (r) { if (!r.slot) put(r, null); });
      return L;
    },
    cell: function (L, bug, agent) {
      var k = cellKey(bug, agent);
      return L.cells[k] || (L.cells[k] = { bug: bug, agent: agent, runs: {} });
    },
    /* the run after a cell's last one */
    nextRun: function (L, bug, agent) {
      var c = L.cells[cellKey(bug, agent)], n = 0;
      if (c) Object.keys(c.runs).forEach(function (r) { n = Math.max(n, +r); });
      return n + 1;
    },
    /* what an upload to come would meet: the same file already uploaded ({rec, same: true}),
     * or a run already at (bug, agent, run) ({rec, run}; rec null: the corpus's); null if none.
     * item: {bug, agent, run (or null: after the last), hash, id (its own record, if any)} */
    clash: function (L, recs, item) {
      var same = item.hash && (recs || []).filter(function (r) { return r.hash === item.hash && r.id !== item.id; })[0];
      if (same) { var at = L.at[same.id] || {}; return { rec: same, same: true, bug: at.bug, agent: at.agent, run: at.run }; }
      if (item.run == null || !item.bug) return null;
      var c = L.cells[cellKey(item.bug, item.agent)], x = c && c.runs[item.run];
      if (!x || (x.rec && x.rec.id === item.id)) return null;
      return { rec: x.rec, same: false, bug: item.bug, agent: item.agent, run: item.run };
    },
    /* the uploads of one bug as a comparison (analyze.html#b=<bug>): every agent's runs */
    bugGroup: function (D, recs, bug) {
      var L = TV.uploads.layout(D, recs), order = TV.AGENT_ORDER.concat(TV.OTHER_AGENTS);
      var members = recs.filter(function (r) { var at = L.at[r.id]; return at && at.bug === bug; });
      members.forEach(function (r) { r._bugRun = L.at[r.id].run; });
      members.sort(function (a, b) {
        var x = order.indexOf(TV.uploads.agent(a)), y = order.indexOf(TV.uploads.agent(b));
        return (x < 0 ? 99 : x) - (y < 0 ? 99 : y) || TV.uploads.agent(a).localeCompare(TV.uploads.agent(b)) || a._bugRun - b._bugRun;
      });
      return { id: 'b:' + bug, kind: 'bug', name: TV.bugName(bug), bug: bug, members: members };
    },

    /* ------------------------------------------------------------ folder uploads */
    /* the runs in a folder's files (each with .relPath: "<dataset>/<bug>/<agent>/run<n>/…"):
     *   {dataset, runs: [{bug, agent, run, files (the ones to try, in order), path}],
     *    csvs: [File], ignored: [paths]}
     * The run folder is the first folder named run<n>; the folder above it names the agent and
     * the one above that the bug (missing levels: read from the log). Files out of a run folder
     * are ignored, but CSV files anywhere: they may hold the outcomes. */
    scan: function (files) {
      var out = { dataset: '', runs: [], csvs: [], ignored: [] }, by = {};
      Array.prototype.forEach.call(files || [], function (f) {
        var path = String(f.relPath || f.webkitRelativePath || f.name).replace(/^\/+/, ''), seg = path.split('/'), name = seg[seg.length - 1];
        if (/^\./.test(name)) return;                                         // .DS_Store and the like
        if (/\.csv$/i.test(name)) { out.csvs.push(f); return; }
        var j = -1, m;
        for (var i = 0; i < seg.length - 1; i++) if ((m = /^run[-_ ]?(\d+)$/i.exec(seg[i]))) { j = i; break; }
        if (j < 0 || tryRank(f) < 0) { out.ignored.push(path); return; }
        if (j >= 3 && !out.dataset) out.dataset = seg[j - 3];
        var bug = j >= 2 ? TV.bugKey(seg[j - 2]) : '', agent = j >= 1 ? TV.normAgent(seg[j - 1]) : '', run = +m[1];
        var k = bug + '\u0001' + agent + '\u0001' + run;
        if (!by[k]) { by[k] = { bug: bug, agent: agent, run: run, files: [], path: seg.slice(0, j + 1).join('/') }; out.runs.push(by[k]); }
        by[k].files.push(f);
      });
      out.runs.forEach(function (x) { x.files.sort(function (a, b) { return tryRank(a) - tryRank(b) || b.size - a.size; }); });
      out.runs.sort(function (x, y) { return TV.bugSort(x.bug, y.bug) || x.agent.localeCompare(y.agent) || x.run - y.run; });
      return out;
    },
    /* the outcomes in a CSV: a header with a bug column, an agent column and either one
     * outcome column (with a run column, or for every run) or one column per run (run1, run2…);
     * values pass / fail, 1 / 0, true / false. [{bug, agent, run (null: every run), pass}],
     * or null when the header names no bug or no outcome. */
    readOutcomes: function (text) {
      var lines = String(text || '').replace(/^\uFEFF/, '').split(/\r?\n/).filter(function (l) { return l.trim(); });
      if (lines.length < 2) return null;
      var head = csvFields(lines[0]).map(function (h) { return h.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, ''); });
      function col(re) { for (var i = 0; i < head.length; i++) if (re.test(head[i])) return i; return -1; }
      var cb = col(/^(bug|bug_id|bug_name|bugid|instance|instance_id|issue)$/), ca = col(/^(agent|agent_name)$/), cr = col(/^run$/);
      var co = col(/^(outcome|outcomes|test_outcome|test_result|result|pass|passed|status|resolved)$/), runCols = [];
      head.forEach(function (h, i) { var m = /^run_?(\d+)$/.exec(h); if (m) runCols.push({ i: i, run: +m[1] }); });
      if (cb < 0 || (co < 0 && !runCols.length)) return null;
      var rows = [];
      lines.slice(1).forEach(function (l) {
        var f = csvFields(l), bug = TV.bugKey(f[cb]), agent = ca >= 0 ? TV.normAgent(f[ca]) : '';
        if (!bug) return;
        if (co >= 0) rows.push({ bug: bug, agent: agent, run: cr >= 0 && +f[cr] ? +f[cr] : null, pass: passOf(f[co]) });
        else runCols.forEach(function (c) { rows.push({ bug: bug, agent: agent, run: c.run, pass: passOf(f[c.i]) }); });
      });
      return rows;
    },
    /* a run's outcome among the CSV rows (a row of that run wins over one for every run); an
     * agent column left empty matches every agent */
    outcomeOf: function (rows, bug, agent, run) {
      var hit = null;
      (rows || []).forEach(function (r) {
        if (r.bug !== bug || (r.agent && agent && TV.agentKey(r.agent) !== TV.agentKey(agent)) || r.pass == null) return;
        if (r.run === run) hit = { pass: r.pass, exact: true };
        else if (r.run == null && !(hit && hit.exact)) hit = { pass: r.pass, exact: false };
      });
      return hit ? hit.pass : null;
    },
    /* add a run of a folder: its files tried in order until the engine reads one (the others
     * are not trajectories: metadata, sandbox logs). Resolves {rec, tried: [{name, error}]};
     * rejects (answered) when none is a trajectory. */
    addRun: function (run, rs, opts) {
      var tried = [];
      return run.files.reduce(function (p, f) {
        return p.then(function (rec) {
          if (rec) return rec;
          return TV.uploads.add(f, rs, Object.assign({}, opts, { path: run.path + '/' + f.name })).catch(function (err) {
            if (!err || !err.answered) throw err;
            tried.push({ name: f.name, error: err.message });
            return null;
          });
        });
      }, Promise.resolve(null)).then(function (rec) {
        if (!rec) throw mine(run.files.length ? 'no file here is a trajectory the engine reads (' + tried.map(function (x) { return x.name; }).join(', ') + ')' : 'the folder holds no log file');
        return { rec: rec, tried: tried };
      });
    },
    /* what a record is, in words: format and size */
    formatLabel: function (fmt) {
      return { atif: 'ATIF', claude_agent_sdk_repr: 'Claude Agent SDK dump', claude_code_stream_json: 'Claude Code JSON',
        codex_rollout_jsonl: 'Codex rollout', qwen_stream_json: 'Qwen Code stream-json',
        sweagent_traj: 'SWE-agent .traj', sweagent_chat: 'SWE-agent chat export', openhands_messages: 'OpenHands messages',
        openhands_events: 'OpenHands events', mini_swe_agent: 'mini-swe-agent .traj.json',
        specstory_markdown: 'SpecStory Markdown', claude_code_export: 'Claude Code /export' }[fmt] || fmt || '';
    },
    sizeLabel: function (n) {
      return n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : n >= 1024 ? Math.round(n / 1024) + ' KB' : n + ' B';
    }
  };

  /* Add files from a picker or a drop; status(text) reports progress, done(added, failed)
   * at the end (failed: [{name, error}]). The engine starts on the first file. */
  TV.addUploads = function (files, status, done, opts) {
    files = Array.prototype.slice.call(files || []);
    if (!files.length) return;
    var added = [], failed = [], rs = TV.ruleset.get();
    status('Loading the analysis engine…');
    TV.engine.start().then(function () {
      return files.reduce(function (p, f, k) {
        return p.then(function () {
          status('Analysing ' + (files.length > 1 ? (k + 1) + ' of ' + files.length + ': ' : '') + f.name + '…');
          return TV.uploads.add(f, rs, opts).then(function (rec) { added.push(rec); if (opts && opts.each) opts.each(rec); }, function (err) {
            if (!err || !err.answered) throw err;           // the engine stopped: give up
            failed.push({ name: f.name, error: (err && err.message) || String(err) });
          });
        });
      }, Promise.resolve());
    }).then(function () { status(''); done(added, failed); }, function (err) {
      status('');
      failed.push({ name: files.map(function (f) { return f.name; }).join(', '), error: 'the analysis engine could not start: ' + ((err && err.message) || err) });
      done(added, failed);
    });
  };
})();
