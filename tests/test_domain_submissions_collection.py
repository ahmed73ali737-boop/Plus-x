"""Domain unit tests: collection batch/idempotency/feedback-scope rules and metrics aggregation."""
import pytest

from app.domain import Conflict, Forbidden, InvalidInput, NotFound
from app.domain import metrics, submissions


def test_batch_must_be_a_list_of_one_to_fifty_items():
    submissions.require_batch([{}])
    submissions.require_batch([{}] * 50)
    for bad in ([], [{}] * 51, None, 'x', {'a': 1}):
        with pytest.raises(InvalidInput) as error:
            submissions.require_batch(bad)
        assert error.value.code == 'BATCH_1_TO_50_ITEMS'


def test_item_must_be_an_object():
    submissions.require_submission_object({})
    with pytest.raises(InvalidInput):
        submissions.require_submission_object('x')


def test_replay_is_idempotent_but_a_different_body_conflicts():
    assert submissions.is_replay(None, 'abc') is False
    assert submissions.is_replay({'fingerprint': 'abc'}, 'abc') is True
    with pytest.raises(Conflict) as error:
        submissions.is_replay({'fingerprint': 'abc'}, 'other')
    assert error.value.code == 'IDEMPOTENCY_BODY_CONFLICT'
    assert submissions.same_submission({'fingerprint': 'abc'}, 'abc')
    assert not submissions.same_submission({'fingerprint': 'abc'}, 'x')
    assert not submissions.same_submission(None, 'abc')


SITE = {'id': 'agency1', 'event_id': 'ev1'}


def test_feedback_scope_is_the_visited_page_its_event_or_a_published_agency_of_the_same_event():
    assert not submissions.feedback_targets_other_site(SITE, 'agency1')
    assert not submissions.feedback_targets_other_site(SITE, 'ev1')
    assert submissions.feedback_targets_other_site(SITE, 'agency2')
    ok = {'kind': 'agency', 'event_id': 'ev1', 'published_version': 2}
    submissions.require_feedback_scope(SITE, ok)
    for bad in ({**ok, 'kind': 'event'}, {**ok, 'event_id': 'ev2'}, {**ok, 'published_version': 0}):
        with pytest.raises(Forbidden) as error:
            submissions.require_feedback_scope(SITE, bad)
        assert error.value.code == 'FEEDBACK_SCOPE'


def test_feedback_target_must_be_a_rateable_record_unless_general():
    config = {'records': [{'code': 's1', 'kind': 'session'}, {'code': 'p1', 'kind': 'poll'}]}
    submissions.require_feedback_target(config, 'general')
    submissions.require_feedback_target(config, 's1')
    for code in ('p1', 'nope'):
        with pytest.raises(NotFound) as error:
            submissions.require_feedback_target(config, code)
        assert error.value.code == 'FEEDBACK_TARGET'


def entry(kind, **values):
    return {'kind': kind, 'site_id': 'a', 'version': 1, 'target': '', 'payload': {}, 'visitor_id': 'v1',
            'session_id': 's1', 'source': 'web', 'received_at': '2026-10-01T00:00:00Z', **values}


CONFIG = {'records': [
    {'code': 'q1', 'title': 'Q1', 'qtype': 'single', 'options': [{'key': 'y', 'label': 'Yes'}]},
    {'code': 'q2', 'title': 'Q2', 'qtype': 'short_text'},
]}


def test_metrics_count_sessions_answers_ratings_and_notes():
    entries = [
        entry('visit'), entry('visit', visitor_id='v2'), entry('visit', session_id='k1', source='kiosk'),
        entry('survey', payload={'answers': {'q1': 'y', 'q2': 'hello'}}),
        entry('poll', target='q1', payload={'answer': 'y'}),
        entry('feedback', target='a', payload={'rating': 4, 'note': 'good', 'criteria': {'x': 5}}),
        entry('feedback', target='a', payload={'rating': 2, 'note': '', 'criteria': {'x': 3}},
              received_at='2026-10-02T00:00:00Z'),
        entry('follow', payload={'name': 'N', 'marketing': 1}),
    ]
    result = metrics.build_metrics(entries, {('a', 1): CONFIG}, 'NOW')
    assert result['as_of'] == 'NOW' and result['verified_people'] is None
    assert result['counts'] == {'visit': 3, 'survey': 1, 'poll': 1, 'feedback': 2, 'follow': 1}
    assert result['page_sessions'] == 3
    assert result['browser_ids_estimate'] == 2      # kiosk visits are not browsers
    assert result['kiosk_sessions'] == 1
    assert result['site_visits'] == {'a': 3}
    assert result['questions'] == {'a / v1 / q1': {'y': 2}}
    assert result['text_answer_counts'] == {'a / v1 / q2': 1}
    assert result['question_labels']['a / v1 / q1']['options'] == {'y': 'Yes'}
    assert result['ratings'] == {'a': {'count': 2, 'average': 3.0}}
    assert result['rating_criteria'] == {'a': {'x': {'count': 2, 'average': 4.0}}}
    assert [n['note'] for n in result['feedback_notes']] == ['good']
    assert result['follow_requests'][0]['marketing'] is True
    assert result['follow_requests'][0]['preferred_channel'] == 'any'
    assert len(result['notes']) == 3


def test_metrics_keep_only_the_newest_hundred_notes_and_follow_requests():
    entries = [entry('feedback', target='a', payload={'note': f'n{i}'}, received_at=f'2026-10-01T00:{i // 60:02d}:{i % 60:02d}Z')
               for i in range(120)]
    result = metrics.build_metrics(entries, {('a', 1): CONFIG}, 'NOW')
    assert len(result['feedback_notes']) == 100
    assert result['feedback_notes'][0]['note'] == 'n119'
