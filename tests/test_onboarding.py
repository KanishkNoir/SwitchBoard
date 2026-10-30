import pytest

from switchboard.persistence import Store
from switchboard.service import SwitchboardError, SwitchboardService


def make():
    return SwitchboardService(Store(":memory:"))


def test_state_defaults_incomplete_with_locked_list():
    svc = make()
    svc.category("infra")
    st = svc.onboarding_state()
    assert st["completed"] is False
    assert "payments" in st["locked_categories"] and "deletion" in st["locked_categories"]
    assert st["categories"][0]["stage"] == "shadow"


def test_complete_marks_and_applies_risk_choice():
    svc = make()
    svc.category("infra")
    st = svc.complete_onboarding(model_calls=False, risk_choice="careful")
    assert st["completed"] is True
    assert svc.category("infra")["risk_target"] == 0.01
    assert svc.onboarding_state()["completed"] is True


def test_bad_risk_choice_rejected():
    svc = make()
    with pytest.raises(SwitchboardError):
        svc.complete_onboarding(risk_choice="yolo")


def test_categories_start_shadow_and_locked_stays_locked():
    svc = make()
    pay = svc.category("payments")
    assert pay["locked"] == 1
    infra = svc.category("infra")
    assert infra["locked"] == 0 and infra["stage"] == "shadow"
