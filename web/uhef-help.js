'use strict';
// UHEF — contextual help on every screen of the Eventna web app (public pages, guest pass and gate,
// invitations, certificates, accounts and every Studio tab). One knowledge source
// (/assets/uhef-knowledge.json, uhef.knowledge/1.0). The «؟ المساعدة» button sits in each page's own
// header (re-attached when the app re-renders it) and F1 opens the panel of the current screen.
// Nothing here calls an API or changes data; the support tab copies a report that carries the
// screen id, the route pattern (never tokens or ids from the address) and the time only.
(function (root) {
  const KNOWLEDGE = '/assets/uhef-knowledge.json';
  const TABS = [['screen', 'الشاشة'], ['map', 'الخريطة'], ['steps', 'الخطوات'], ['fields', 'الحقول'], ['flow', 'الترابط والرحلة'], ['faq', 'أسئلة'], ['bot', 'المساعد'], ['support', 'الدعم']];
  const STOP = new Set(['من', 'في', 'على', 'الي', 'عن', 'ما', 'ماذا', 'كيف', 'هل', 'او', 'و', 'ان', 'هذا', 'هذه', 'ذلك', 'التي', 'الذي', 'اريد', 'لماذا', 'متي', 'اين', 'كم', 'لا', 'مع', 'بعد', 'قبل', 'عند', 'هو', 'هي', 'انا', 'لي', 'كل', 'اي', 'يتم', 'ثم', 'قد', 'لم', 'لن']);
  // Headers the app renders, most specific first. The admin heading is rebuilt on every tab.
  const HOSTS = ['.admin-heading .actions', '.admin-heading', 'header.site-topbar .topbar-inner', 'header.access-header', 'header.inv-public-header', '.livewall-actions', 'header.selfcert-heading'];
  const text = v => v == null ? '' : typeof v === 'string' ? v : (v.ar ?? v.en ?? Object.values(v)[0] ?? '');
  const list = v => Array.isArray(v) ? v.map(text).filter(Boolean) : [];

  function normalize(s) { return String(s || '').toLowerCase().replace(/[ً-ْٰـ]/g, '').replace(/[أإآٱ]/g, 'ا').replace(/ة/g, 'ه').replace(/ى/g, 'ي').replace(/ؤ/g, 'و').replace(/ئ/g, 'ي').replace(/[^\p{L}\p{N}]+/gu, ' ').trim(); }
  function stem(w) { let s = w; for (const p of ['وال', 'بال', 'فال', 'كال', 'لل', 'ال']) if (s.startsWith(p) && s.length - p.length >= 3) { s = s.slice(p.length); break; } if (s.length > 4 && s.startsWith('و')) s = s.slice(1); for (const x of ['ات', 'ون', 'ين', 'ها', 'ه', 'ي']) if (s.endsWith(x) && s.length - x.length >= 3) { s = s.slice(0, -x.length); break; } return s; }
  function terms(s) { return new Set(normalize(s).split(' ').filter(w => w.length > 1 && !STOP.has(w)).map(stem)); }

  /** The screen of a Location-like [loc], mirroring the router in web/app.mjs.
   *  [hint]: {error: true} on the error page; {admin: 'login'|'password'|tabKey} inside /admin. */
  function screenOf(loc, hint) {
    hint = hint || {}; if (hint.error) return 'app.error';
    const path = loc.pathname || '/', parts = path.split('/').filter(Boolean);
    if (path === '/certificates') return 'selfcert.admin';
    if (path.startsWith('/certificates/')) return ['request', 'receive', 'verify'].includes(parts[1]) && parts.length === 3 ? 'selfcert.' + parts[1] : 'app.error';
    if (path === '/account' || path.startsWith('/account/')) return ({ '/account/invite': 'account.invite', '/account/request': 'account.request', '/account/signup': 'account.signup', '/account/login': 'admin.login' })[path] || 'account.profile';
    if (path === '/start') return 'access.start';
    if (path === '/admin' || path.startsWith('/admin/')) return 'admin.' + (hint.admin || 'login');
    if (parts[0] === 'certificate' && parts.length === 2) return 'cert.access';
    if (parts[0] === 'verify' && parts[1] === 'certificate' && parts.length === 3) return 'cert.verify';
    if (parts[0] === 'invite' && parts.length === 2) return 'invite.rsvp';
    if (parts[0] === 'e' && parts[2] === 'register') return 'invite.register';
    if (parts[0] === 'live' && parts.length === 2) return 'live.wall';
    if (parts[0] === 'e' && parts[2] === 'guest') return parts[3] ? 'guest.pass' : 'guest.register';
    if (parts[0] === 'e' && parts[2] === 'scan') return 'gate.scan';
    if (parts.includes('p')) return 'public.agency';
    if (parts[0] === 'e') return 'public.event';
    return 'public.platform';
  }

  function model(K, key) {
    const s = K && K.screens && K.screens[key]; if (!s) return null;
    return { id: key, route: s.route || '', name: text(s.name), module: text(s.module), purpose: text(s.purpose), why: text(s.why), whenToUse: text(s.whenToUse),
      prerequisites: list(s.prerequisites), afterwards: list(s.afterwards), impact: text(s.impact),
      parts: (s.parts || []).map(p => ({ name: text(p.name), desc: text(p.desc), use: list(p.use), to: p.to || [] })),
      steps: (s.steps || []).map(x => typeof x === 'string' ? { text: x } : { text: text(x.text) }),
      elements: s.elements || {}, faq: (s.faq || []).map(f => ({ q: text(f.q), a: text(f.a) })),
      prev: (s.related || {}).prev || [], next: (s.related || {}).next || [], journey: (s.related || {}).journey || null };
  }

  function journeysOf(K, key) {
    return Object.entries((K && K.journeys) || {}).filter(([id, j]) => (j.steps || []).some(s => s.screen === key) || ((K.screens[key] || {}).related || {}).journey === id)
      .map(([id, j]) => ({ id, name: text(j.name), desc: text(j.desc), start: text(j.start), end: text(j.end), guide: list(j.guide), steps: (j.steps || []).map(s => ({ screen: s.screen, actor: text(s.actor), action: text(s.action) })) }));
  }

  function passages(models) {
    const out = [], add = (screen, section, title, body, w) => { if (body && String(body).trim()) out.push({ screen, section, title, text: String(body), weight: w || 1 }); };
    for (const m of models) {
      add(m.id, 'الشاشة', m.name, [m.purpose, m.why, m.whenToUse].join(' ')); add(m.id, 'قبل', m.name, m.prerequisites.join(' • ')); add(m.id, 'بعد', m.name, [m.impact, ...m.afterwards].join(' • '));
      add(m.id, 'الخطوات', m.name, m.steps.map((s, i) => (i + 1) + '. ' + s.text).join('\n'));
      for (const p of m.parts) add(m.id, 'الخريطة', m.name + ' › ' + p.name, p.name + ': ' + p.desc + ' ' + p.use.join(' '));
      for (const e of Object.values(m.elements)) add(m.id, 'الحقول', m.name + ' › ' + text(e.name), [text(e.name), text(e.definition), text(e.howTo)].join(' '), 1.1);
      for (const f of m.faq) add(m.id, 'أسئلة', f.q, f.q + '\n' + f.a, 1.4);
    }
    return out;
  }

  /** Passages that answer [question]; empty when nothing documented matches (the bot never guesses). */
  function ask(question, items, current, limit = 3) {
    const asked = terms(question); if (!asked.size) return []; const scored = [];
    for (const p of items) { const have = p._t || (p._t = terms(p.title + ' ' + p.text)); let hits = 0; for (const t of asked) if (have.has(t)) hits++; if (!hits) continue; const cov = hits / asked.size; if (cov < 0.5 && hits < 2) continue; let s = cov * p.weight; if (current && p.screen === current) s *= 1.5; scored.push([p, s]); }
    return scored.sort((a, b) => b[1] - a[1]).slice(0, limit).map(x => x[0]);
  }

  /** Gaps of the knowledge for [keys]: the CI gate (tests/test_uhef_help.py runs the same rules). */
  function problems(K, keys) {
    const out = []; if (!K || K.schema !== 'uhef.knowledge/1.0') out.push('schema must be uhef.knowledge/1.0');
    const known = k => !!(K && K.screens && K.screens[k]);
    for (const key of keys) {
      const s = model(K, key); if (!s) { out.push(key + ': not documented'); continue; }
      for (const [f, v] of [['name', s.name], ['purpose', s.purpose], ['why', s.why], ['whenToUse', s.whenToUse]]) if (!v) out.push(key + ': ' + f + ' is missing');
      if (!s.prerequisites.length) out.push(key + ': no "before"'); if (!s.afterwards.length) out.push(key + ': no "after"'); if (!s.steps.length) out.push(key + ': no steps'); if (!s.faq.length) out.push(key + ': no FAQ');
      if (!s.parts.length) out.push(key + ': no parts (roadmap)');
      for (const p of s.parts) { if (!p.use.length) out.push(key + ': part "' + p.name + '" has no roadmap'); for (const t of p.to) if (!known(t)) out.push(key + ': part "' + p.name + '" leads to unknown ' + t); }
      for (const t of [...s.prev, ...s.next]) if (!known(t)) out.push(key + ': related screen ' + t + ' is unknown');
      if (s.journey && !(K.journeys || {})[s.journey]) out.push(key + ': unknown journey ' + s.journey);
      for (const [id, e] of Object.entries(s.elements)) if (['input', 'select', 'textarea', 'file'].includes(e.kind || 'input') && !text(e.howTo)) out.push(key + ': field ' + id + ' lacks howTo');
    }
    for (const [id, j] of Object.entries((K && K.journeys) || {})) { if (!list(j.guide).length) out.push('journey ' + id + ': no operations guide'); for (const st of j.steps || []) { if (!st.screen || !known(st.screen)) out.push('journey ' + id + ': unknown screen ' + st.screen); if (!text(st.actor)) out.push('journey ' + id + ': step without actor'); } }
    return out;
  }

  /** Free text typed into a report: phone numbers, codes and e-mail addresses are masked. */
  function mask(s) { return String(s || '').replace(/[\w.+-]+@[\w-]+(\.[\w-]+)+/g, '[email]').replace(/[+\d٠-٩][\d٠-٩ \-]{3,}[\d٠-٩]/g, '[رقم]'); }
  /** The support report: screen id, route pattern and time; never values, tokens or ids from the URL. */
  function report(ctx) { return { title: '[مساعدة/' + ctx.type + '] ' + ctx.name + ' (' + ctx.screen + ')', description: mask(ctx.description) + '\n---\nscreen=' + ctx.screen + ' page=' + (ctx.page || '') + ' at=' + (ctx.at || new Date().toISOString()) }; }

  // ------------------------------------------------------------------ UI
  let K = null, loading = null, dialog = null;
  const load = () => loading || (loading = fetch(KNOWLEDGE, { cache: 'no-cache' }).then(r => r.ok ? r.json() : null).then(j => (K = j)).catch(() => null));
  function adminHint() {
    if (document.querySelector('.password-change-screen')) return 'password';
    const active = document.querySelector('#admin-nav .nav-item.active');
    if (active && K) { const label = active.textContent.trim(); const hit = Object.entries(K.screens).find(([, s]) => s.adminTab === label); if (hit) return hit[0].slice('admin.'.length); }
    return document.querySelector('.admin-layout') ? 'overview' : 'login';
  }
  function current() { return screenOf(location, { error: !!document.querySelector('#app > .error-page'), admin: adminHint() }); }
  function h(tag, txt, cls) { const e = document.createElement(tag); if (txt != null) e.textContent = txt; if (cls) e.className = cls; return e; }
  function btn(label, fn, cls) { const b = h('button', label, cls || 'uhef-secondary'); b.type = 'button'; b.addEventListener('click', fn); return b; }
  function bullets(items, cls) { const ul = h('ul', null, cls || 'uhef-list'); for (const i of items) ul.append(h('li', i)); return ul; }
  function section(title, ...kids) { const s = h('section', null, 'uhef-section'); s.append(h('h3', title), ...kids.filter(Boolean)); return s; }
  const nameOf = k => (model(K, k) || {}).name || k;
  function links(keys, go) { const box = h('div', null, 'uhef-links'); for (const k of keys) box.append(btn(nameOf(k), () => go(k))); return box; }

  async function open(key, tab) {
    await load(); key = key || current();
    if (!dialog) {
      dialog = h('dialog', null, 'uhef-panel'); dialog.id = 'uhef-dialog'; dialog.dir = 'rtl'; dialog.lang = 'ar'; dialog.setAttribute('aria-labelledby', 'uhef-title'); document.body.append(dialog);
      dialog.addEventListener('click', e => { if (e.target === dialog) dialog.close(); });
      // Keys typed in the panel never reach the app's own shortcuts (kiosk idle reset, storyboard keys).
      for (const t of ['keydown', 'keyup', 'keypress']) dialog.addEventListener(t, e => { if (e.key !== 'Escape') e.stopPropagation(); });
    }
    const d = dialog, m = model(K, key), go = k => open(k, 'screen');
    d.replaceChildren(); d.dataset.screen = key;
    const head = h('div', null, 'uhef-head'), title = h('h2', 'المساعدة: ' + (m ? m.name : key)); title.id = 'uhef-title'; head.append(title, btn('إغلاق', () => d.close())); d.append(head);
    const bar = h('div', null, 'uhef-tabs'), body = h('div', null, 'uhef-body'); bar.setAttribute('role', 'tablist'); d.append(bar, body);
    const render = {
      screen() { if (!m) return body.append(h('p', K ? 'لا يوجد توثيق لهذه الشاشة بعد. استخدم تبويب «الدعم».' : 'تعذر تحميل المساعدة الآن.'));
        body.append(m.module && h('p', m.module, 'uhef-muted'), section('ما هذه الشاشة؟', h('p', m.purpose)), m.why && section('لماذا تستخدمها؟', h('p', m.why)), m.whenToUse && section('متى تستخدمها؟', h('p', m.whenToUse)),
          m.prerequisites.length && section('قبل أن تبدأ', bullets(m.prerequisites, 'uhef-list uhef-check')), m.impact && section('أثر الإجراء', h('p', m.impact)),
          m.afterwards.length && section('بعد الانتهاء', bullets(m.afterwards)), m.prev.length && section('يأتي قبلها', links(m.prev, go)), m.next.length && section('يأتي بعدها', links(m.next, go))); },
      map() { if (!m) return; const stage = (t, ...k) => { const s = h('div', null, 'uhef-stage'); s.append(h('h3', t), ...k.filter(Boolean)); return s; };
        const from = [...new Set([...m.prev, ...Object.keys(K.screens).filter(k => k !== key && (model(K, k).next.includes(key) || model(K, k).parts.some(p => p.to.includes(key))))])];
        body.append(stage('قبل هذه الشاشة', bullets(m.prerequisites, 'uhef-list uhef-check'), from.length && h('strong', 'تصل إليها من'), from.length && links(from, go)));
        const here = stage('في هذه الشاشة: ' + m.name); m.parts.forEach((p, i) => { const c = h('div', null, 'uhef-part'); c.append(h('h4', (i + 1) + '. ' + p.name), h('p', p.desc)); const ol = h('ol', null, 'uhef-use'); for (const u of p.use) ol.append(h('li', u)); c.append(ol); if (p.to.length) c.append(h('strong', 'تقودك إلى'), links(p.to, go)); here.append(c); }); body.append(here);
        body.append(stage('بعد هذه الشاشة', m.impact && h('p', m.impact), bullets(m.afterwards), m.next.length && h('strong', 'تقودك إلى'), m.next.length && links(m.next, go))); },
      steps() { if (!m) return; body.append(section('قبل أن تبدأ', bullets(m.prerequisites, 'uhef-list uhef-check'))); const ol = h('ol', null, 'uhef-steps'); for (const s of m.steps) ol.append(h('li', s.text)); body.append(ol, section('بعد الانتهاء', bullets(m.afterwards))); },
      fields() { const els = Object.entries((m && m.elements) || {}); if (!els.length) return body.append(h('p', 'لا حقول إدخال في هذه الشاشة؛ راجع أجزاءها في «الخريطة».'));
        for (const [id, e] of els) { const det = h('details', null, 'uhef-field'); det.dataset.field = id; det.append(h('summary', text(e.name) + (e.required ? ' *' : ''))); for (const [l, v] of [['ما هو', text(e.definition)], ['كيف تملؤه', text(e.howTo)], ['مثال', text(e.example)], ['الإلزام', e.required ? 'إلزامي' : 'اختياري']]) if (v) det.append(h('p', l + ': ' + v)); body.append(det); } },
      flow() { const js = journeysOf(K, key); if (!js.length) return body.append(h('p', 'شاشة مستقلة لا تنتمي إلى رحلة متعددة المراحل.'), m && (m.prev.length || m.next.length) ? section('الشاشات المرتبطة', links([...m.prev, ...m.next], go)) : null);
        for (const j of js) { const ol = h('ol', null, 'uhef-journey'); for (const s of j.steps) { const li = h('li', null, s.screen === key ? 'uhef-here' : ''); li.append(h('strong', s.actor + ': '), document.createTextNode(s.action + ' — ' + nameOf(s.screen))); if (s.screen === key) li.append(h('span', ' أنت هنا', 'uhef-badge')); else li.append(btn('مساعدة', () => go(s.screen))); ol.append(li); }
          body.append(section('رحلة: ' + j.name, h('p', j.desc), h('p', 'البداية: ' + j.start + ' · النتيجة: ' + j.end, 'uhef-muted'), ol, section('دليل التشغيل', bullets(j.guide)))); } },
      faq() { for (const f of [...((m && m.faq) || []), ...((K && K.faq) || []).map(f => ({ q: text(f.q), a: text(f.a) }))]) { const det = h('details', null, 'uhef-faq'); det.append(h('summary', f.q), h('p', f.a)); body.append(det); } },
      bot() { body.append(h('p', 'اسأل عن هذه الشاشة أو أي شاشة. أجيب فقط مما وُثّق في دليل المساعدة وأذكر المصدر، ولا أخمّن.', 'uhef-muted'));
        const log = h('div', null, 'uhef-log'), q = h('input'); q.type = 'search'; q.placeholder = 'اكتب سؤالك…'; q.setAttribute('aria-label', 'سؤالك للمساعد'); log.setAttribute('aria-live', 'polite');
        const send = () => { const question = q.value.trim(); if (!question) return; q.value = ''; log.prepend(h('p', question, 'uhef-q'));
          const found = ask(question, passages(Object.keys((K && K.screens) || {}).map(k => model(K, k))), key), box = h('div', null, 'uhef-answer');
          if (!found.length) box.append(h('p', 'لم أجد إجابة موثقة لهذا السؤال، ولن أخمّن. أرسله إلى الدعم مع سياق الشاشة.'), btn('أرسل السؤال للدعم', () => open(key, 'support:' + question)));
          for (const p of found) box.append(h('p', p.text), h('small', 'المصدر: ' + nameOf(p.screen) + ' › ' + p.section, 'uhef-muted uhef-source'));
          log.prepend(box); };
        q.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); send(); } };
        const sug = h('div', null, 'uhef-links'); for (const f of ((m && m.faq) || []).slice(0, 3)) sug.append(btn(f.q, () => { q.value = f.q; send(); }));
        body.append(sug, q, btn('اسأل', send, 'uhef-primary'), log); q.focus(); },
      support(prefill) { const type = h('select'); for (const [v, l] of [['question', 'سؤال'], ['unclear', 'غير واضح'], ['bug', 'مشكلة'], ['suggestion', 'اقتراح']]) { const o = h('option', l); o.value = v; type.append(o); } type.setAttribute('aria-label', 'نوع البلاغ');
        const desc = h('textarea'); desc.rows = 4; desc.maxLength = 2000; desc.setAttribute('aria-label', 'وصف البلاغ'); desc.placeholder = 'اشرح ما حدث أو ما تحتاجه. لا تكتب أرقام هواتف أو كلمات مرور أو روابط دعوات.'; if (prefill) desc.value = prefill;
        const status = h('p', '', 'uhef-muted'); status.setAttribute('role', 'status');
        const page = (m && m.route) || '';
        body.append(section('بلاغ أو طلب مساعدة', type, desc, h('p', 'يُرفق تلقائيًا: الشاشة (' + key + ') ونمط الصفحة (' + page + ') والوقت فقط؛ لا قيم حقول ولا بيانات زوار ولا رموز من الرابط. تُخفى الأرقام والبريد من الوصف.', 'uhef-muted'), status),
          btn('نسخ البلاغ', async () => { if (desc.value.trim().length < 10) { status.textContent = 'اكتب وصفًا أوضح (10 أحرف على الأقل).'; return; } const r = report({ type: type.value, name: m ? m.name : key, screen: key, page, description: desc.value.trim() }); const all = r.title + '\n' + r.description; d.dataset.report = all; try { await navigator.clipboard.writeText(all); status.textContent = 'نُسخ البلاغ؛ أرسله إلى مسؤول جهتك أو منظم الفعالية.'; } catch (e) { status.textContent = all; } }, 'uhef-primary'));
        const ch = ((K && K.support) || {}).channels || []; if (ch.length) body.append(section('قنوات الدعم', bullets(ch.map(x => text(x.label) + ': ' + text(x.value))))); },
    };
    let pre = null; if (tab && tab.startsWith('support:')) { pre = tab.slice(8); tab = 'support'; }
    const show = k => { body.replaceChildren(); for (const b of bar.children) { const on = b.dataset.tab === k; b.setAttribute('aria-selected', String(on)); b.classList.toggle('active', on); } render[k](k === 'support' ? pre : undefined); pre = null; };
    for (const [k, l] of TABS) { const b = btn(l, () => show(k)); b.dataset.tab = k; b.setAttribute('role', 'tab'); bar.append(b); }
    show(tab && render[tab] ? tab : 'screen'); if (!d.open) d.showModal(); return d;
  }

  /** The button lives in the page's own header; it floats only on screens that render none. */
  function place(b) {
    const host = HOSTS.map(s => document.querySelector(s)).find(Boolean);
    if (host) { if (b.parentElement !== host) { b.className = 'uhef-inline'; host.append(b); } }
    else if (!b.isConnected || b.parentElement !== document.body) { b.className = 'uhef-fab'; document.body.append(b); }
  }
  function boot() {
    if (document.getElementById('uhef-help')) return;
    const b = h('button', '؟ المساعدة'); b.id = 'uhef-help'; b.type = 'button'; b.title = 'المساعدة (F1)'; b.setAttribute('aria-label', 'المساعدة لهذه الشاشة'); b.setAttribute('aria-haspopup', 'dialog'); b.addEventListener('click', () => open());
    place(b); let queued = false; new MutationObserver(() => { if (queued) return; queued = true; requestAnimationFrame(() => { queued = false; place(b); }); }).observe(document.body, { childList: true, subtree: true });
    document.addEventListener('keydown', e => { if (e.key === 'F1') { e.preventDefault(); open(); } });
  }

  const api = { normalize, terms, screenOf, model, journeysOf, passages, ask, problems, mask, report, open, current, TABS, HOSTS };
  root.EventnaHelp = api;
  if (typeof document !== 'undefined') { if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot(); }
  if (typeof module !== 'undefined') module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
