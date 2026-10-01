from fastapi import HTTPException
import pytest
from app.domain import default_config, normalize_config, normalize_record, answer_value


def test_theme_professional_settings_roundtrip():
    c=default_config('Theme 09')
    c.update(font='geometric',button_style='pill',nav_style='floating',density='spacious',content_width='full',heading_scale='display')
    n=normalize_config(c)
    assert (n['font'],n['button_style'],n['nav_style'],n['density'],n['content_width'],n['heading_scale'])==('geometric','pill','floating','spacious','full','display')


def test_survey_metadata_roundtrip():
    c=default_config('Survey 09')
    c['surveys']=[{'id':'visit','title':'تقييم الزيارة','description':'قصير','completion':'تم','presentation':'stepper','show_progress':True,'submit_label':'أرسل رأيك'}]
    n=normalize_config(c)
    s=n['surveys'][0]
    assert s['presentation']=='stepper' and s['show_progress'] is True and s['submit_label']=='أرسل رأيك'


def test_dropdown_question_and_answer():
    q=normalize_record({'kind':'question','code':'REGION','title':'المنطقة','qtype':'dropdown','options':['صنعاء','تعز']})
    assert answer_value(q,'o2')=='o2'
    with pytest.raises(HTTPException): answer_value(q,'bad')


def test_currency_is_numeric():
    q=normalize_record({'kind':'question','code':'BUDGET','title':'الميزانية','qtype':'currency','min':0,'max':1000})
    assert answer_value(q,'125.5')==125.5
    with pytest.raises(HTTPException): answer_value(q,'abc')


def test_multiple_choice_min_max():
    q=normalize_record({'kind':'question','code':'USES','title':'اختر','qtype':'multiple_choice','options':['A','B','C'],'selection_min':1,'selection_max':2,'required':True})
    assert answer_value(q,['o1','o2'])==['o1','o2']
    with pytest.raises(HTTPException): answer_value(q,[])
    with pytest.raises(HTTPException): answer_value(q,['o1','o2','o3'])


def test_scale_labels_preserved():
    q=normalize_record({'kind':'question','code':'RATE','title':'قيّم','qtype':'rating','min_label':'ضعيف','max_label':'ممتاز'})
    assert q['min_label']=='ضعيف' and q['max_label']=='ممتاز'
