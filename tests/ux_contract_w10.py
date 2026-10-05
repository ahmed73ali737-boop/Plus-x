from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
admin=(ROOT/'web/admin.mjs').read_text(encoding='utf-8')
public=(ROOT/'web/public.mjs').read_text(encoding='utf-8')
domain=(ROOT/'app/domain.py').read_text(encoding='utf-8')
checks={
 'rts_template':"rts_tech:'RTS Tech'" in admin and "'rts_tech'" in domain,
 'easy_template':"easy_finance:'Easy Finance & Payments'" in admin and "'easy_finance'" in domain,
 'public_role_signup':"requested_role" in public and 'جهة منظمة لفعالية' in public and 'جهة مشاركة في فعالية' in public,
 'optional_control_account':'أحتاج حساب تحكم للجهة' in public,
 'admin_signup_review':'طلبات الانضمام من الموقع العام' in admin,
 'display_only_org':'جهة للعرض فقط بلا حساب' in admin,
 'temporary_password':'كلمة المرور المؤقتة' in admin,
 'agency_org_visibility':'هذه المؤسسة دائمة عبر الفعاليات' in admin,
 'rts_layout_profile':"key==='rts_tech'" in admin,
 'easy_layout_profile':"key==='easy_finance'" in admin,
}
assert all(checks.values()), checks
print(checks)
