/* The Psychonaut Bookworm — progressive enhancement.
 *
 * This file constructs nothing. The 454 published objects are in index.html
 * when it leaves the server; everything here filters, remembers, or reveals
 * DOM that is already on the page. If this file fails to load, the library is
 * still complete and readable — which is why every control it drives ships
 * with the `hidden` attribute and is revealed below.
 */
(function () {
  'use strict';

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  function store(key, fallback) {
    try { return JSON.parse(localStorage.getItem(key)) || fallback; }
    catch (err) { return fallback; }
  }
  function save(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (err) { /* private mode */ }
  }

  // ---------------------------------------------------------------- reveal
  // Nothing renders as a dead affordance: a control that needs this script is
  // hidden in the HTML and only this script can show it.
  $$('[data-js-only]').forEach(function (el) { el.hidden = false; });
  ['#research-noscript-note', '#rl-noscript'].forEach(function (sel) {
    var el = $(sel);
    if (el) el.hidden = true;
  });

  // ------------------------------------------------------------- filtering
  // One pass decides every item's visibility from two independent filters:
  // the section's own bar, and the Research Desk search that spans all
  // sections. Whichever the reader touched last, both still hold.
  var groups = {};   // container id -> {el, items, state}
  var research = { q: '', type: 'all', book: 'all' };

  function tokens(el, name) {
    var v = el.getAttribute(name) || '';
    return v.split(/\s+/).filter(Boolean);
  }

  $$('[data-filterable]').forEach(function (container) {
    var items = Array.prototype.filter.call(container.children, function (child) {
      return child.hasAttribute('data-book') || child.hasAttribute('data-bookslug') ||
             child.hasAttribute('data-obj') || child.hasAttribute('data-format');
    });
    groups[container.id] = {
      el: container,
      state: { book: 'all', topic: 'all', format: 'all', search: '' },
      items: items.map(function (el) {
        return {
          el: el,
          book: el.getAttribute('data-book') || '',
          slugs: tokens(el, 'data-bookslug'),
          topics: tokens(el, 'data-topic'),
          format: el.getAttribute('data-format') || '',
          obj: el.getAttribute('data-obj') || '',
          text: null
        };
      })
    };
  });

  function haystack(item) {
    if (item.text === null) item.text = (item.el.textContent || '').toLowerCase();
    return item.text;
  }

  function matchesLocal(item, st) {
    if (st.book !== 'all' && item.slugs.indexOf(st.book) < 0) return false;
    if (st.topic !== 'all' && item.topics.indexOf(st.topic) < 0) return false;
    if (st.format !== 'all' && item.format !== st.format) return false;
    if (st.search && haystack(item).indexOf(st.search) < 0) return false;
    return true;
  }

  function matchesResearch(item) {
    if (research.type !== 'all' && item.obj !== research.type) return false;
    if (research.book !== 'all' && item.book !== research.book) return false;
    if (research.q && haystack(item).indexOf(research.q) < 0) return false;
    return true;
  }

  var researchActive = function () {
    return research.q !== '' || research.type !== 'all' || research.book !== 'all';
  };

  function apply() {
    var shownIndexed = 0;
    Object.keys(groups).forEach(function (id) {
      var g = groups[id], shown = 0;
      g.items.forEach(function (item) {
        var vis = matchesLocal(item, g.state) && matchesResearch(item);
        item.el.hidden = !vis;
        if (vis) {
          shown++;
          if (item.obj === 'Editorial draft' || item.obj === 'Then vs. Now' ||
              item.obj === 'Flashcard' || item.obj === 'Science annotation') shownIndexed++;
        }
      });
      var empty = g.el.parentNode ? g.el.parentNode.querySelector('[data-empty]') : null;
      if (!empty) empty = document.querySelector('#' + id + ' [data-empty]');
      if (empty) empty.hidden = shown !== 0;
    });
    var summary = $('#research-summary');
    if (summary) {
      summary.textContent = researchActive()
        ? shownIndexed + ' of ' + INDEXED + ' indexed objects match · ' +
          queue().length + ' saved to this browser'
        : INDEXED + ' indexed objects · ' + queue().length + ' saved to this browser';
    }
  }

  var INDEXED = 0;
  Object.keys(groups).forEach(function (id) {
    groups[id].items.forEach(function (i) {
      if (i.obj === 'Editorial draft' || i.obj === 'Then vs. Now' ||
          i.obj === 'Flashcard' || i.obj === 'Science annotation') INDEXED++;
    });
  });

  $$('[data-target]').forEach(function (bar) {
    var g = groups[bar.getAttribute('data-target')];
    if (!g) return;
    bar.addEventListener('click', function (ev) {
      var btn = ev.target.closest('button[data-group]');
      if (!btn) return;
      var group = btn.getAttribute('data-group');
      g.state[group] = btn.getAttribute('data-val');
      $$('button[data-group="' + group + '"]', bar).forEach(function (b) {
        var on = b === btn;
        b.classList.toggle('active', on);
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
      apply();
    });
    var input = bar.querySelector('input[type="search"]');
    if (input) input.addEventListener('input', function () {
      g.state.search = input.value.toLowerCase().trim();
      apply();
    });
  });

  // ---------------------------------------------------------- research desk
  var rq = $('#research-q'), rt = $('#research-type'), rb = $('#research-book');
  if (rq) rq.addEventListener('input', function () { research.q = rq.value.toLowerCase().trim(); apply(); });
  if (rt) rt.addEventListener('change', function () { research.type = rt.value; apply(); });
  if (rb) rb.addEventListener('change', function () { research.book = rb.value; apply(); });

  // -------------------------------------------------------- reading queue
  var QUEUE_KEY = 'pbw-research-queue';
  function queue() { var q = store(QUEUE_KEY, []); return Array.isArray(q) ? q : []; }

  function labelFor(btn) {
    var host = btn.closest('[data-key]') || btn.closest('article') || btn.closest('tr');
    var h = host ? host.querySelector('h3, .fc-q, .ann-claim, summary') : null;
    return (h ? h.textContent : 'Saved item').replace(/\s+/g, ' ').trim();
  }

  function paintQueue() {
    var q = queue();
    $$('[data-queue]').forEach(function (btn) {
      var on = q.indexOf(btn.getAttribute('data-queue')) >= 0;
      btn.classList.toggle('saved', on);
      btn.textContent = on ? 'Saved' : 'Save';
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  $$('[data-queue]').forEach(function (btn) {
    btn.addEventListener('click', function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      var key = btn.getAttribute('data-queue'), q = queue(), i = q.indexOf(key);
      if (i >= 0) q.splice(i, 1); else q.push(key);
      save(QUEUE_KEY, q);
      paintQueue();
      apply();
    });
  });
  paintQueue();

  var exportBtn = $('#research-export');
  if (exportBtn) exportBtn.addEventListener('click', function () {
    var q = queue();
    if (!q.length) { window.alert('Nothing saved yet. Use Save on any draft, comparison, flashcard or annotation.'); return; }
    var lines = ['# Psychonaut Bookworm research queue', ''];
    q.forEach(function (key) {
      var btn = document.querySelector('[data-queue="' + key + '"]');
      if (!btn) { lines.push('- ' + key); return; }
      var host = btn.closest('[data-key]');
      var section = host ? host.closest('section') : null;
      var anchor = section ? location.origin + location.pathname + '#' + section.id : location.href;
      lines.push('- [' + labelFor(btn) + '](' + anchor + ') — ' +
                 (host ? host.getAttribute('data-obj') || '' : '') +
                 (host && host.getAttribute('data-book') ? '; ' + host.getAttribute('data-book') : ''));
    });
    var blob = new Blob([lines.join('\n') + '\n'], { type: 'text/markdown' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'psychonaut-bookworm-queue.md';
    a.click();
    URL.revokeObjectURL(a.href);
  });

  var clearBtn = $('#research-clear');
  if (clearBtn) clearBtn.addEventListener('click', function () {
    if (!queue().length) return;
    if (!window.confirm('Clear the reading queue saved in this browser?')) return;
    save(QUEUE_KEY, []);
    paintQueue();
    apply();
  });

  // ------------------------------------------------- course: notes & progress
  $$('textarea[data-artifact]').forEach(function (ta) {
    var key = 'pbw-artifact-' + ta.getAttribute('data-artifact');
    var saved = store(key, null);
    if (typeof saved === 'string') ta.value = saved;
    var counter = document.querySelector('[data-wordcount-for="' + ta.getAttribute('data-artifact') + '"]');
    function tick() {
      var n = ta.value.split(/\s+/).filter(Boolean).length;
      if (counter) counter.textContent = n + (n === 1 ? ' word' : ' words') + ' · saved in this browser';
      save(key, ta.value);
    }
    ta.addEventListener('input', tick);
    tick();
  });

  var PROGRESS_KEY = 'pbw_progress_v1';
  $$('input[data-module-complete]').forEach(function (box) {
    var id = box.getAttribute('data-module-complete');
    var prog = store(PROGRESS_KEY, {});
    box.checked = !!prog[id];
    box.addEventListener('change', function () {
      var p = store(PROGRESS_KEY, {});
      p[id] = box.checked;
      save(PROGRESS_KEY, p);
      paintProgress();
    });
  });
  function paintProgress() {
    var out = $('#course-progress');
    if (!out) return;
    var prog = store(PROGRESS_KEY, {});
    var boxes = $$('input[data-module-complete]');
    var done = boxes.filter(function (b) { return prog[b.getAttribute('data-module-complete')]; }).length;
    out.textContent = '✓ ' + done + ' of ' + boxes.length + ' modules marked complete in this browser';
    boxes.forEach(function (b) {
      var card = b.closest('details.mod');
      if (card) card.classList.toggle('done', !!prog[b.getAttribute('data-module-complete')]);
    });
  }
  paintProgress();

  // -------------------------------------------------------------- drills
  // Both drills read the cards and claims already printed on the page. They
  // introduce no content of their own.
  function shuffle(a) {
    for (var i = a.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1)); var t = a[i]; a[i] = a[j]; a[j] = t;
    }
    return a;
  }

  var drill = $('#drill-stage');

  function drillFlashcards() {
    var cards = $$('#fc-list tr').map(function (tr) {
      return {
        q: (tr.querySelector('.fc-q') || {}).textContent || '',
        a: (tr.querySelector('.fc-a') || {}).textContent || '',
        cite: (tr.querySelectorAll('.fc-cite')[1] || {}).textContent || ''
      };
    });
    if (!cards.length) { drill.textContent = 'No flashcards are published in this edition.'; return; }
    shuffle(cards);
    var i = 0, seen = 0;
    function render(showAnswer) {
      var c = cards[i];
      drill.innerHTML = '';
      var box = document.createElement('div');
      box.className = 'card';
      box.style.borderLeftColor = 'var(--forest)';
      var prog = document.createElement('p');
      prog.className = 'mono';
      prog.textContent = 'Card ' + (i + 1) + ' of ' + cards.length + ' · ' + seen + ' seen';
      var q = document.createElement('p');
      q.className = 'fc-q';
      q.style.margin = '.6rem 0';
      q.textContent = c.q;
      box.appendChild(prog); box.appendChild(q);
      if (showAnswer) {
        var a = document.createElement('p');
        a.className = 'fc-a';
        a.textContent = c.a;
        box.appendChild(a);
        if (c.cite) {
          var cite = document.createElement('p');
          cite.className = 'fc-cite';
          cite.textContent = c.cite;
          box.appendChild(cite);
        }
      }
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'queue-btn';
      btn.style.marginTop = '.75rem';
      btn.textContent = showAnswer ? 'Next card' : 'Show answer';
      btn.addEventListener('click', function () {
        if (showAnswer) { seen++; i = (i + 1) % cards.length; render(false); }
        else render(true);
      });
      box.appendChild(btn);
      drill.appendChild(box);
      btn.focus();
    }
    render(false);
  }

  function drillClaims() {
    // The canonical verdict lives in data-verdict. The freeform label printed on
    // some cards ("Confirmed (Phase 2)") is the author's nuance, not a sortable
    // category — quizzing on it produced 38 buttons for five real answers.
    var claims = $$('#cs-list details[data-verdict]').map(function (d) {
      return {
        claim: (d.querySelector('summary') || {}).textContent || '',
        verdict: d.getAttribute('data-verdict'),
        why: (d.querySelector('p[style]') || {}).textContent || '',
        node: d
      };
    }).filter(function (c) { return c.verdict; });
    if (!claims.length) { drill.textContent = 'No claims are published in this edition.'; return; }
    var options = [];
    claims.forEach(function (c) { if (options.indexOf(c.verdict) < 0) options.push(c.verdict); });
    options.sort();
    shuffle(claims);
    var i = 0, right = 0, asked = 0;
    function render() {
      var c = claims[i];
      drill.innerHTML = '';
      var box = document.createElement('div');
      box.className = 'card';
      box.style.borderLeftColor = 'var(--sienna)';
      var prog = document.createElement('p');
      prog.className = 'mono';
      prog.textContent = 'Claim ' + (i + 1) + ' of ' + claims.length + ' · ' + right + ' of ' + asked + ' right';
      var q = document.createElement('p');
      q.style.cssText = 'font-size:.95rem;line-height:1.7;margin:.6rem 0';
      q.textContent = c.claim;
      box.appendChild(prog); box.appendChild(q);
      var row = document.createElement('div');
      row.style.cssText = 'display:flex;gap:.4rem;flex-wrap:wrap';
      options.forEach(function (opt) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'queue-btn';
        b.textContent = opt;
        b.addEventListener('click', function () {
          asked++;
          if (opt === c.verdict) right++;
          var res = document.createElement('div');
          res.style.marginTop = '.75rem';
          var v = document.createElement('p');
          v.className = 'mono';
          v.textContent = (opt === c.verdict ? '✓ ' : '✗ ') + 'Recorded verdict: ' + c.verdict;
          var why = document.createElement('p');
          why.style.cssText = 'font-size:.85rem;line-height:1.7;color:var(--muted)';
          why.textContent = c.why;
          var next = document.createElement('button');
          next.type = 'button';
          next.className = 'queue-btn';
          next.textContent = 'Next claim';
          next.addEventListener('click', function () { i = (i + 1) % claims.length; render(); });
          res.appendChild(v); res.appendChild(why); res.appendChild(next);
          row.replaceWith(res);
          next.focus();
        });
        row.appendChild(b);
      });
      box.appendChild(row);
      drill.appendChild(box);
    }
    render();
  }

  var fcDrill = $('#drill-flashcards'), csDrill = $('#drill-claims');
  if (fcDrill && drill) fcDrill.addEventListener('click', drillFlashcards);
  if (csDrill && drill) csDrill.addEventListener('click', drillClaims);

  // --------------------------------------------------------- section marker
  var links = {};
  $$('#tabBar a[href^="#"]').forEach(function (a) { links[a.getAttribute('href').slice(1)] = a; });
  var sections = $$('main > section[id]').filter(function (s) { return links[s.id]; });
  if (sections.length) {
    var current = null;
    var pending = false;
    var markCurrent = function () {
      pending = false;
      var y = window.pageYOffset + 140, found = sections[0].id;
      for (var i = 0; i < sections.length; i++) {
        if (sections[i].offsetTop <= y) found = sections[i].id; else break;
      }
      if (found === current) return;
      if (current && links[current]) links[current].removeAttribute('aria-current');
      links[found].setAttribute('aria-current', 'true');
      current = found;
    };
    window.addEventListener('scroll', function () {
      if (pending) return;
      pending = true;
      window.requestAnimationFrame(markCurrent);
    }, { passive: true });
    markCurrent();
  }

  apply();
})();
