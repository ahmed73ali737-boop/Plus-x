/** Accessible read/edit list for ordering existing published-content records.
 * Only saves the draft through the existing scoped admin endpoint.
 */
import {h, button, toast, msg, labels} from './ui.mjs';
import {orderedRecords, moveRecord, STORYBOARD_PAGE_SIZE} from './storyboard-core.mjs';

export function storyboard({host, current, saveDraft}) {
  const panel = h('section', {class:'storyboard-panel'});
  host.append(panel);
  let page = 0;
  let busy = false;
  let dragged = null;
  const info = h('p', {class:'muted', 'aria-live':'polite'}, 'رتّب العناصر الموجودة فقط. لا تُنشر التغييرات قبل اعتماد النشر.');
  const message = h('p', {class:'muted', role:'status', 'aria-live':'polite'});
  const list = h('ol', {class:'storyboard-list', 'aria-label':'ترتيب مواد التجربة'});
  const controls = h('div', {class:'storyboard-pagination'});
  panel.append(
    h('div', {class:'card form-card'},
      h('h2', {}, 'ترتيب مواد التجربة'),
      info,
      h('p', {class:'muted'}, 'اسحب البطاقة أو استخدم زري التقديم والتأخير. تعمل الأزرار على الهاتف ولوحة المفاتيح، ويمكن نقل العنصر بين الصفحات المتعددة.'),
      h('p', {class:'notice small'}, 'قواعد تفرع الأسئلة لا تسمح بتقديم سؤال مشروط على السؤال الذي يتحكم به. الحفظ في المسودة فقط وليس نشرًا تلقائيًا.')
    ),
    message, list, controls
  );

  async function move(from, to) {
    if (busy || from === to || !host.isConnected) return;
    const before = current.draft.records;
    let next;
    try {
      next = moveRecord(before, from, to);
    } catch(e) {
      message.textContent = e.message === 'BRANCH_MUST_REFERENCE_EARLIER_QUESTION_IN_FORM'
        ? 'هذا النقل غير مسموح: السؤال المشروط يجب أن يأتي بعد السؤال المرجعي في الاستبيان نفسه.' : msg(e);
      return;
    }
    busy = true;
    message.textContent = 'جاري حفظ ترتيب المسودة...';
    current.draft.records = next;
    render();
    try {
      await saveDraft();
      message.textContent = 'تم حفظ الترتيب في المسودة. اضغط نشر التغييرات عند الجاهزية.';
      const newIndex = Math.max(0, Math.min(to, next.length - 1));
      page = Math.floor(newIndex / STORYBOARD_PAGE_SIZE);
    } catch(e) {
      current.draft.records = before;
      message.textContent = 'لم يتغير الترتيب: ' + msg(e) + (e.status === 409 ? ' — أعد تحميل المسودة ثم حاول مجددًا.' : '');
      toast(msg(e), true);
    } finally {
      busy = false;
      dragged = null;
      render();
    }
  }

  function render() {
    const ordered = orderedRecords(current.draft.records || []);
    const totalPages = Math.max(1, Math.ceil(ordered.length / STORYBOARD_PAGE_SIZE));
    page = Math.max(0, Math.min(page, totalPages - 1));
    list.replaceChildren();
    if (!ordered.length) {
      list.append(h('li', {class:'card mini'}, 'لا توجد مواد بعد. أضف سؤالًا أو تصويتًا أو محتوى من التبويبات المخصصة أولًا.'));
    }
    const start = page * STORYBOARD_PAGE_SIZE;
    for (let index = start; index < Math.min(ordered.length, start + STORYBOARD_PAGE_SIZE); index++) {
      const record = ordered[index];
      const up = button('↑ تقديم', () => move(index, index - 1), 'btn secondary');
      const down = button('↓ تأخير', () => move(index, index + 1), 'btn secondary');
      up.disabled = busy || index === 0;
      down.disabled = busy || index === ordered.length - 1;
      const row = h('li', {class:'storyboard-card', draggable:!busy, 'data-code':record.code},
        h('span', {class:'storyboard-number', 'aria-label':'الترتيب'}, String(index + 1)),
        h('div', {class:'storyboard-text'},
          h('strong', {}, record.title || record.code),
          h('span', {class:'muted'}, (labels[record.kind] || record.kind) + ' · ' + record.code +
            (record.kind === 'question' ? ' · استبيان ' + (record.form_id || 'main') : '') +
            (record.enabled === false ? ' · معطّل' : ''))),
        h('div', {class:'storyboard-actions'}, up, down)
      );
      row.addEventListener('dragstart', event => {
        if (busy) {event.preventDefault();return;}
        dragged = index;
        event.dataTransfer?.setData('text/plain', String(index));
        if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
      });
      row.addEventListener('dragover', event => {
        if (dragged === null || busy) return;
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
      });
      row.addEventListener('drop', event => {
        event.preventDefault();
        const from = dragged;
        dragged = null;
        if (from !== null && Number.isInteger(from)) void move(from, index);
      });
      row.addEventListener('dragend', () => {dragged = null;});
      list.append(row);
    }
    controls.replaceChildren();
    const previous = button('الصفحة السابقة', () => {page--;render();}, 'btn secondary');
    const next = button('الصفحة التالية', () => {page++;render();}, 'btn secondary');
    previous.disabled = busy || page === 0;
    next.disabled = busy || page >= totalPages - 1;
    controls.append(previous, h('span', {class:'muted'}, 'صفحة ' + (page + 1) + ' من ' + totalPages + ' · ' + ordered.length + ' مادة'), next);
  }
  render();
}
