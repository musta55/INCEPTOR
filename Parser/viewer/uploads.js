/* TrajecTiers dashboard - the user's uploaded trajectories (needs engine.js).
 *
 * An upload is one log (or ATIF file) the user added. It is kept in this browser only
 * (IndexedDB: 'uploads' holds the record and its analysis, 'texts' the file itself and, under
 * '<id>|atif', the trajectory as ATIF for the details panel's full texts and raw JSON) and is
 * analysed again whenever the rule set changes, so uploads and corpus always share one rule
 * set. Record: {id, name, size, added, bug (the user's bug id, or null: inferred), outcome
 * (true | false | null), rulesKey, result (atif.upload.request: trajectory, vocab, rules,
 * source, warnings, unrecognized), group ({id, kind, name} when it belongs to a comparison set
 * up on upload.html, else absent), run (its run number in a 'runs' group)}. A group is
 * 'agents' (one bug, several agents) or 'runs' (one agent's runs of one bug); it exists only
 * through its members' records. TV.uploads.summary(rec) gives the overview's summary form of
 * a record, so the corpus page and the statistics treat it like a corpus trajectory. */
(function () {
  'use strict';
  var TV = window.TV;

  function mine(msg) { return Object.assign(new Error(msg), { answered: true }); }   // not the engine's fault
  function newId() { return 'u' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }
  function byAdded(a, b) { return String(b.added).localeCompare(String(a.added)); }
  function request(rec, text, rs, atif) {
    return TV.engine.analyze({ name: rec.name, text: text, rules: rs, bug: rec.bug || null, outcome: rec.outcome, atif: !!atif });
  }
  function atifKey(id) { return id + '|atif'; }

  TV.uploads = {
    /* every record, newest first; [] where the browser keeps nothing */
    list: function () { return TV.idb.all('uploads').then(function (xs) { return xs.sort(byAdded); }, function () { return []; }); },
    get: function (id) { return TV.idb.get('uploads', id); },
    /* analyse a File under the rule set and keep it (opts.bug: the bug id to read its paths
     * against); rejects with the engine's message */
    add: function (file, rs, opts) {
      rs = rs || TV.ruleset.get();
      var info = TV.engine.info;
      if (info && file.size > info.max_bytes) return Promise.reject(mine('larger than ' + Math.round(info.max_bytes / 1048576) + ' MB'));
      return file.text().then(function (text) {
        var rec = { id: newId(), name: file.name, size: file.size, added: new Date().toISOString(), bug: (opts && opts.bug) || null, outcome: null };
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
      return TV.idb.get('texts', rec.id).then(function (text) {
        if (text == null) throw mine('the file of ' + rec.name + ' is no longer stored');
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
    /* the harness outcome the user knows; no re-analysis needed (only the outcome changes) */
    setOutcome: function (rec, pass) {
      rec.outcome = pass;
      var t = rec.result && rec.result.trajectory;
      if (t) t.outcome = { pass: pass, by_run: { 1: pass } };
      return TV.idb.put('uploads', rec.id, rec).then(function () { return rec; });
    },
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
    agent: function (rec) { var t = (rec.result || {}).trajectory || {}; return t.agent || ((rec.result || {}).source || {}).agent || '?'; },
    model: function (rec) { var t = (rec.result || {}).trajectory || {}; return t.model || ((rec.result || {}).source || {}).model || ''; },
    /* a member's name in its group: "run 2", or its agent (with the model or the file name when
     * two members share the agent) */
    memberLabel: function (rec, members) {
      if (rec.group && rec.group.kind === 'runs') return 'run ' + (rec.run || '?');
      var a = TV.uploads.agent(rec), twins = (members || []).filter(function (r) { return TV.uploads.agent(r) === a; });
      if (twins.length < 2) return a;
      var m = TV.uploads.model(rec), sameModel = twins.filter(function (r) { return TV.uploads.model(r) === m; }).length > 1;
      return a + ' · ' + (m && !sameModel ? m : rec.name);
    },
    KINDS: { agents: 'One bug, several agents', runs: 'One agent, several runs' },
    remove: function (ids) {
      return Promise.all(ids.map(function (id) {
        return TV.idb.del('uploads', id).then(function () { return TV.idb.del('texts', id); }).then(function () { return TV.idb.del('texts', atifKey(id)); });
      }));
    },
    /* the record's trajectory as ATIF: kept since its upload, else converted again (once) */
    atif: function (rec) {
      return TV.idb.get('texts', atifKey(rec.id)).then(function (x) {
        if (x) return x;
        return TV.idb.get('texts', rec.id).then(function (text) {
          if (text == null) throw new Error('the file of ' + rec.name + ' is no longer stored');
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
      return { id: rec.id, upload: rec, agent: t.agent, bug: t.bug || null, model: t.model, pass: rec.outcome,
        project: TV.uploads.project(rec),
        n_actions: t.n_actions, n_steps: t.n_steps, strip: strip, sub_strip: sub, stats: t.stats || {},
        badges: t.badges || {}, metrics: t.metrics || {}, subphases: { by_outcome: byOutcome, by_phase: byPhase } };
    },
    /* the kind of project a record works on: 'swebench' (SWE-agent, OpenHands, mini-swe-agent
     * runs on Python repositories, kept apart from the Android corpus) or 'android' */
    project: function (rec) {
      var res = rec.result || {};
      return (res.trajectory || {}).project || (res.source || {}).project || 'android';
    },
    /* a record's bug, in words: a corpus bug-<id>, or a SWE-bench instance id as it is */
    bugLabel: function (bug, project) {
      return project === 'swebench' ? String(bug) : 'bug-' + bug;
    },
    /* what a record is, in words: format and size */
    formatLabel: function (fmt) {
      return { atif: 'ATIF', claude_agent_sdk_repr: 'Claude Agent SDK dump', claude_code_stream_json: 'Claude Code JSON',
        codex_rollout_jsonl: 'Codex rollout', qwen_stream_json: 'Qwen Code stream-json',
        sweagent_traj: 'SWE-agent .traj', sweagent_chat: 'SWE-agent chat export', openhands_messages: 'OpenHands messages',
        openhands_events: 'OpenHands events', mini_swe_agent: 'mini-swe-agent .traj.json' }[fmt] || fmt || '';
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
