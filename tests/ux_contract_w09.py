from pathlib import Path
root=Path(__file__).resolve().parents[1]
admin=(root/'web/admin.mjs').read_text()
public=(root/'web/public.mjs').read_text()
questions=(root/'web/questions.mjs').read_text()
css=(root/'web/design.css').read_text()
checks={
 'survey_templates':'قوالب استبيانات جاهزة' in admin,
 'bulk_questions':'إضافة عدة أسئلة' in admin,
 'grouped_question_types':'optgroup' in admin,
 'dropdown_real_select':"q.qtype==='dropdown'" in questions,
 'currency_number':"currency:'number'" in questions,
 'stepper':"presentation==='stepper'" in public and "survey-'+(meta.presentation" in public,
 'theme_gallery':'template-grid' in admin and 'theme-preview' in admin,
 'theme_controls':'button_style' in admin and 'content_width' in admin and 'heading_scale' in admin,
 'professional_css':'.theme-studio-grid' in css and 'body[data-width=full]' in css,
 'rating_studio':'RATING STUDIO' in admin and 'حفظ معايير التقييم' in admin,
 'time_field':'time:\'time\'' in questions,
}
failed=[k for k,v in checks.items() if not v]
print(checks)
if failed: raise SystemExit('failed: '+','.join(failed))
