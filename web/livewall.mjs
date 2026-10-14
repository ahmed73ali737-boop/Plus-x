/**
 * PulseX Live Wall v1: read-only public wall of supervisor-published polls.
 * Never read private metrics, raw submissions, guest identities, or draft data.
 */
import {h, root, api, button} from './ui.mjs';

const REFRESH_MS = 10000;

function approvedPolls(page, result) {
  const published = page?.config?.records || [];
  const allowed = new Set(Object.keys(result?.polls || {}));
  return published.filter(r => r.kind === 'poll' && r.enabled !== false &&
    r.show_results === true && r.poll_style !== 'secret' && allowed.has(r.code));
}

function pollCard(record, result) {
  const votes = Math.max(0, Number(result.ballots) || 0);
  const choices = Object.entries(result.counts || {}).slice(0, 50);
  const titleFor = key => (record.options || []).find(o => o.key === key)?.label || key;
  const rows = choices.map(([key, raw]) => {
    const count = Math.max(0, Number(raw) || 0);
    const label = String(titleFor(key)).slice(0, 150);
    return h('div', {class: 'livewall-result-row'},
      h('div', {class: 'livewall-result-label'}, h('span', {}, label), h('strong', {}, String(count))),
      h('progress', {max: Math.max(votes, count, 1), value: count, 'aria-label': label}));
  });
  return h('article', {class: 'livewall-card', 'data-poll': record.code},
    h('div', {class: 'livewall-eyebrow'}, 'نتائج تصويت منشورة'),
    h('h2', {}, record.title),
    h('p', {class: 'livewall-muted'}, String(votes) + ' صوت مستلم · لا تظهر أصوات التصويت السري'),
    ...(rows.length ? rows : [h('p', {class: 'livewall-muted'}, 'لا توجد أصوات بعد.')]));
}

export async function liveWallPage(slug) {
  if (!/^[a-z0-9-]{1,80}$/.test(slug)) throw new Error('رابط شاشة العرض غير صالح.');
  document.title = 'شاشة النتائج الحية | PulseX';
  document.body.classList.add('livewall-mode');
  const headline = h('h1', {}, 'شاشة النتائج الحية');
  const summary = h('p', {class: 'livewall-muted', 'aria-live': 'polite'}, 'جاري التحقق من البيانات المنشورة…');
  const content = h('main', {class: 'livewall-grid', id: 'livewall-results', 'aria-live': 'polite'});
  const fullscreen = button('ملء الشاشة', async () => {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.documentElement.requestFullscreen();
  }, 'livewall-button');
  root.replaceChildren(h('div', {class: 'livewall-shell'},
    h('header', {class: 'livewall-header'},
      h('div', {}, h('p', {class: 'livewall-kicker'}, 'PULSEX · LIVE WALL'), headline, summary),
      h('div', {class: 'livewall-actions'}, fullscreen,
        h('a', {class: 'livewall-button', href: '/e/' + encodeURIComponent(slug)}, 'العودة للفعالية'))),
    content,
    h('footer', {class: 'livewall-footer'}, 'التحديث كل 10 ثوانٍ عند توفر الاتصال · النتائج للعرض العام وفق اعتماد المنظم')));

  let busy = false;
  async function refresh() {
    if (busy || document.hidden) return;
    busy = true;
    try {
      // Refresh both resources so moderator publication and withdrawal take effect.
      const [page, results] = await Promise.all([
        api('/api/public/site/' + encodeURIComponent(slug)),
        api('/api/public/site/' + encodeURIComponent(slug) + '/results')
      ]);
      if (page.version !== results.version) throw new Error('PUBLISHED_VERSION_CHANGED');
      document.documentElement.style.setProperty('--livewall-accent', page.config.primary || '#176B73');
      headline.textContent = page.config.title + ' · النتائج الحية';
      const polls = approvedPolls(page, results);
      content.replaceChildren(...(polls.length
        ? polls.map(p => pollCard(p, results.polls[p.code]))
        : [h('section', {class: 'livewall-empty'},
            h('h2', {}, 'لا توجد نتائج معتمدة للعرض حاليًا'),
            h('p', {}, 'يحدد المنظم نشر نتائج التصويت من لوحة الإدارة ثم ينشر التغييرات.'))]));
      summary.textContent = 'منشور رقم ' + page.version + ' · آخر تحديث ' + new Date(results.as_of).toLocaleTimeString('ar-YE');
    } catch {
      // Never retain stale numbers when the public API cannot be trusted.
      content.replaceChildren(h('section', {class: 'livewall-empty livewall-error'},
        h('h2', {}, 'النتائج غير متاحة الآن'),
        h('p', {}, 'تأكد من الاتصال أو من نشر الصفحة. لن نعرض بيانات مخزنة قديمة.')));
      summary.textContent = 'لا توجد بيانات حية موثوقة · ستتم إعادة المحاولة تلقائيًا';
    } finally {
      busy = false;
    }
  }
  await refresh();
  const timer = setInterval(refresh, REFRESH_MS);
  window.addEventListener('pagehide', () => clearInterval(timer), {once: true});
  document.addEventListener('visibilitychange', () => {if (!document.hidden) refresh();});
}
