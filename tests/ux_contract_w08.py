from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
checks=[]
def ok(name, cond):
    if not cond: raise AssertionError(name)
    checks.append(name)
ui=(ROOT/'web/ui.mjs').read_text(encoding='utf-8')
q=(ROOT/'web/questions.mjs').read_text(encoding='utf-8')
a=(ROOT/'web/admin.mjs').read_text(encoding='utf-8')
p=(ROOT/'web/public.mjs').read_text(encoding='utf-8')
css=(ROOT/'web/design.css').read_text(encoding='utf-8')
ok('time_type_catalog',"time:'وقت'" in ui)
ok('datetime_type_catalog',"datetime:'تاريخ ووقت'" in ui)
ok('time_native_input',"time:'time'" in q)
ok('datetime_native_input',"datetime:'datetime-local'" in q)
ok('survey_manager','function questionsManager()' in a and 'استبيان جديد' in a)
ok('question_type_dynamic','question-type-config' in a and 'نوع الإجابة وإعداداته' in a)
ok('poll_manager','function pollsManager()' in a and "موعد الفتح — اختياري" in a)
ok('schedule_native_datetime',a.count("'datetime-local'")>=4)
ok('contact_email_message','البريد الإلكتروني' in p and 'كيف يمكننا مساعدتك؟' in p and 'preferred_channel' in p)
ok('rating_star_ui','star-picker' in p and '.star-choice' in css)
ok('survey_metadata_public','page.config.surveys' in p and 'إرسال الاستبيان' in p)
ok('poll_requires_answer','اختر إجابة قبل إرسال التصويت' in p)
report={'status':'passed','passed':len(checks),'checks':checks}
(ROOT/'qa/ux-contract-w08.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
