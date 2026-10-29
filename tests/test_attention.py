from switchboard.domain import QuestionRequest
from switchboard.persistence import Store
from switchboard.service import SwitchboardService


def make():
    svc = SwitchboardService(Store(":memory:"))
    reg = svc.register_agent("tester", "cli")
    return svc, svc.authenticate(reg["api_key"])


def queue_and_answer(svc, agent, n, answer="yes", dwell_ms=None):
    for i in range(n):
        svc.ask(agent, QuestionRequest(request_id=f"r{i}-{answer}-{dwell_ms}",
                                       question=f"May I do thing {i}?", category="purchase"))
        item = svc.inbox()[-1]
        svc.answer_inbox(item["id"], {"value": answer}, dwell_ms=dwell_ms)


def test_health_unknown_with_no_answers():
    svc, _ = make()
    h = svc.attention_health()
    assert h["risk"] == "unknown" and h["total_answers"] == 0


def test_mixed_answers_stay_ok():
    svc, agent = make()
    queue_and_answer(svc, agent, 3, answer="yes")
    queue_and_answer(svc, agent, 3, answer="no")
    h = svc.attention_health()
    assert h["total_answers"] == 6 and h["approval_share"] == 0.5 and h["risk"] == "ok"


def test_rubber_stamp_pattern_flagged_elevated():
    svc, agent = make()
    queue_and_answer(svc, agent, 12, answer="yes", dwell_ms=400)
    h = svc.attention_health()
    assert h["approval_share"] == 1.0 and h["approval_streak"] >= 8
    assert h["median_dwell_ms"] == 400
    assert h["risk"] == "elevated" and len(h["signals"]) >= 2


def test_fast_answers_still_recorded_not_blocked():
    svc, agent = make()
    queue_and_answer(svc, agent, 2, answer="allow", dwell_ms=10)
    assert svc.attention_health()["total_answers"] == 2
    assert svc.inbox() == []
