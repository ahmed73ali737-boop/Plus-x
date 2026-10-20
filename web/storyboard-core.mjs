/** Stable, immutable ordering of existing Eventna إيفنتنا records.
 * This is a draft organizer, not the future conditional experience builder.
 */
export const STORYBOARD_PAGE_SIZE = 25;

export function orderedRecords(records) {
  if (!Array.isArray(records) || records.length > 2000 || records.some(r => !r || typeof r !== 'object' || Array.isArray(r))) {
    throw new Error('INVALID_STORYBOARD_RECORDS');
  }
  return records.map((value, index) => ({value, index}))
    .sort((a, b) => {
      const left = Number.isFinite(a.value.order) ? a.value.order : 0;
      const right = Number.isFinite(b.value.order) ? b.value.order : 0;
      return left - right || a.index - b.index;
    }).map(entry => entry.value);
}

export function validateQuestionOrder(records) {
  const previous = new Map();
  for (const record of orderedRecords(records)) {
    if (record.kind !== 'question') continue;
    const form = record.form_id || 'main';
    if (!previous.has(form)) previous.set(form, new Set());
    const seen = previous.get(form);
    if (record.show_if?.code && !seen.has(record.show_if.code)) {
      throw new Error('BRANCH_MUST_REFERENCE_EARLIER_QUESTION_IN_FORM');
    }
    seen.add(record.code);
  }
  return true;
}

export function moveRecord(records, from, to) {
  const ordered = orderedRecords(records);
  if (!Number.isInteger(from) || !Number.isInteger(to) ||
      from < 0 || to < 0 || from >= ordered.length || to >= ordered.length) {
    throw new RangeError('STORYBOARD_POSITION_INVALID');
  }
  const result = ordered.slice();
  const [record] = result.splice(from, 1);
  result.splice(to, 0, record);
  const updated = result.map((item, i) => ({...item, order: i + 1}));
  validateQuestionOrder(updated);
  return updated;
}
