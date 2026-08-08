/* =====================================================================
   ASSAY — display layer.

   THIS FILE CONTAINS NO LOGIC. Every value arrives display-ready and is
   copied verbatim. This file may only: fetch, loop, copy strings onto
   nodes, append nodes, and drive animation.

   It never: computes a percentage, formats a number or date, truncates
   a hash, derives a label, sorts, filters, decides a verdict, or picks
   a colour from a threshold. Colours come from *_kind fields copied
   into data-k; CSS does the rest.

   Conditional inventory — none inspects the MEANING of a payload value:
     str()   null-guard, one place
     list()  Array.isArray, one place
     map()   v || {}, one place
     ensure()  if (!store[key])  — DOM cache, required because nodes
               must survive polls so a typewriter never replays
     apply()/walk()  hasAttribute — structural DOM, not payload
   Transport has zero conditionals: one fetch, no fallback.
   ===================================================================== */
(function () {
  'use strict';

  var STATE_URL = 'state.json';   /* Flask serves this live at the same path */
  var BET_URL   = '/api/bet';
  var RUN_URL   = '/api/run';
  var POLL_MS   = 500;

  /* ---- the only three value guards in this file --------------------- */
  function str(v)  { return (v === null || v === undefined) ? '' : v; }
  function list(v) { return Array.isArray(v) ? v : []; }
  function map(v)  { return v || {}; }

  function byId(x) { return document.getElementById(x); }
  function tpl(n)  { return byId(n).content.firstElementChild.cloneNode(true); }
  function noop()  {}

  /* ---- declarative binder ------------------------------------------
     Seven copy rules. The HTML declares which payload field goes where;
     this function only moves bytes.                                    */
  function apply(n, d) {
    if (n.hasAttribute('data-f'))        n.textContent = str(d[n.getAttribute('data-f')]);
    if (n.hasAttribute('data-href'))     n.setAttribute('href',    str(d[n.getAttribute('data-href')]));
    if (n.hasAttribute('data-title'))    n.setAttribute('title',   str(d[n.getAttribute('data-title')]));
    if (n.hasAttribute('data-kind'))     n.setAttribute('data-k',  str(d[n.getAttribute('data-kind')]));
    if (n.hasAttribute('data-flag'))     n.setAttribute('data-v',  str(d[n.getAttribute('data-flag')]));
    if (n.hasAttribute('data-id'))       n.setAttribute('data-idv', str(d[n.getAttribute('data-id')]));
    if (n.hasAttribute('data-pct'))      n.style.width = str(d[n.getAttribute('data-pct')]) + '%';
    /* disabled must be the PROPERTY: setAttribute('disabled','false')
       still disables a button. Straight copy, never inverted.          */
    if (n.hasAttribute('data-disabled')) n.disabled = d[n.getAttribute('data-disabled')];
  }

  /* Bounded walk. data-stream / data-slot mark a binding boundary: the
     walk stops there so binding a parent can never overwrite the child
     list rendered from a different object.                             */
  function walk(n, d) {
    var kids = n.children, i, c;
    for (i = 0; i < kids.length; i++) {
      c = kids[i];
      if (c.hasAttribute('data-stream') || c.hasAttribute('data-slot')) continue;
      apply(c, d);
      walk(c, d);
    }
  }

  function bind(root, d) { apply(root, d); walk(root, d); return root; }

  /* ---- DOM cache ----------------------------------------------------
     Nodes are created once and re-bound in place. Required so that a
     log line is never recreated (and so its reveal cannot replay), and
     so clicking a bet button cannot race a repaint.                    */
  var store = {};
  var run   = '';

  function ensure(host, key, tplName, onCreate) {
    var n = store[key];
    if (!n) {
      n = tpl(tplName);
      n.setAttribute('data-run', run);
      store[key] = n;
      host.appendChild(n);
      onCreate(n);
    }
    return n;
  }

  function keyed(host, items, tplName, prefix, onCreate) {
    items.forEach(function (d, i) {
      bind(ensure(host, prefix + '#' + i, tplName, onCreate), d);
    });
  }

  /* Append-only logs. The DOM's own child count is the already-shown
     marker, so there is no counter state and no diffing.               */
  function appendNew(host, items, tplName) {
    items.slice(host.childElementCount).forEach(function (d) {
      var n = bind(tpl(tplName), d);
      n.setAttribute('data-run', run);
      n.classList.add('is-new');
      host.appendChild(n);
    });
    host.scrollTop = host.scrollHeight;
  }

  /* Re-run safety: drop every node stamped with a previous run_id.
     Selector-driven, so there is no comparison logic.                  */
  function evictStaleRun() {
    var stale = document.querySelectorAll('[data-run]:not([data-run="' + run + '"])');
    for (var i = 0; i < stale.length; i++) stale[i].remove();
  }

  /* ---- the one place the page writes rather than reads --------------
     Posts the button's own id and nothing else. No body built from
     state, no optimistic update, no disabling. The next poll repaints. */
  function wireBet(node) {
    node.addEventListener('click', function () {
      fetch(BET_URL, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ id: node.getAttribute('data-idv') })
      }).catch(noop);
    });
  }

  /* Same shape as wireBet: POST and nothing else. The static node lives
     in index.html, so this is wired once at start-up.                   */
  function wireRun(node) {
    node.addEventListener('click', function () {
      fetch(RUN_URL, { method: 'POST' }).catch(noop);
    });
  }

  /* ---- render -------------------------------------------------------
     Loops and copies. Any section may be absent: list()/map() turn that
     into an empty loop, and CSS :empty renders the calm placeholder.   */
  function render(p) {
    p = map(p);

    var meta = map(p.meta);
    run = str(meta.run_id);
    evictStaleRun();
    bind(byId('hdr'), meta);

    list(p.claims).slice(0, 1).forEach(function (c) {
      bind(ensure(byId('claim-host'), run + '|claim', 'tpl-claim', noop), c);
      var v = bind(ensure(byId('verdict-host'), run + '|verdict', 'tpl-verdict', noop), c);
      keyed(v.querySelector('[data-slot="slashed"]'),
            list(c.slashed), 'tpl-slash', run + '|slash', noop);
    });

    var agentHost = byId('agents');
    list(p.agents).forEach(function (a) {
      var el = bind(ensure(agentHost, run + '|ag|' + a.key, 'tpl-agent', noop), a);
      appendNew(el.querySelector('[data-stream]'), list(a.lines), 'tpl-line');
      keyed(el.querySelector('[data-slot="citations"]'),
            list(a.citations), 'tpl-cit', run + '|cit|' + a.key, noop);
    });

    var mk = map(p.market);
    bind(byId('positions'), mk);
    keyed(byId('positions-rows'), list(mk.positions), 'tpl-pos', run + '|pos', noop);

    var bc = map(p.bet_controls);
    bind(byId('bet'), bc);
    keyed(byId('bet-btns'), list(bc.buttons), 'tpl-betbtn', run + '|bet', wireBet);

    bind(byId('run'), map(p.run_controls));

    appendNew(byId('feed'),  list(p.feed),  'tpl-feed');
    appendNew(byId('chain'), list(p.chain), 'tpl-chain');
    keyed(byId('balances'), list(p.balances), 'tpl-bal', run + '|bal', noop);

    bind(byId('sec'), map(p.sec));
  }

  /* ---- transport: one fetch, zero conditionals ----------------------
     .then(up, down): a transport or parse failure lands calmly on
     LINK DOWN, while a render bug stays an unhandled rejection so it
     is loud in devtools instead of being silently swallowed.           */
  function up(p)  { document.body.setAttribute('data-link', 'up'); render(p); }
  function down() { document.body.setAttribute('data-link', 'down'); }

  function poll() {
    fetch(STATE_URL, { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(up, down);
  }

  wireRun(byId('run-btn'));
  poll();
  setInterval(poll, POLL_MS);
})();
