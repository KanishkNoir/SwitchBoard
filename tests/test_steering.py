"""Steering centrepiece: proposals, nudges, revisions, deliberate acceptance."""
import pytest

from switchboard.persistence import Store
from switchboard.service import SwitchboardError, SwitchboardService

DIRS = [
    {"edge": "left", "label": "Cheaper", "expected_effect": "Lower-cost options first"},
    {"edge": "right", "label": "More comfort", "expected_effect": "Comfort-first"},
    {"edge": "top", "label": "Explore", "expected_effect": "Less obvious options"},
    {"edge": "bottom", "label": "Simplify", "expected_effect": "Simplest option"},
]


@pytest.fixture()
def svc_agent():
    svc = SwitchboardService(Store(":memory:"))
    reg = svc.register_agent("steer-tester")
    agent = svc.authenticate(reg["api_key"])
    return svc, agent


def test_full_loop_steer_revise_accept(svc_agent):
    svc, agent = svc_agent
    s = svc.submit_proposal(agent, "Pick a laptop", "Framework 13 at $1599.", "purchase", DIRS)
    assert s["status"] == "open" and s["version"] == 1
    assert s["locked"] is False  # UI renders lock state from this flag, never a guess

    out = svc.steer(s["id"], "left", magnitude=5)  # clamped, recorded, NOT accepted
    assert out["instruction"]["label"] == "Cheaper"
    assert out["instruction"]["magnitude"] == 2.0
    assert out["session"]["status"] == "open"

    pending = svc.pending_steer(agent, s["id"])
    assert pending["instruction"]["edge"] == "left"

    v2 = svc.revise_proposal(agent, s["id"], "Eco Air 14 at $899.", note="went cheaper")
    assert v2["version"] == 2 and v2["proposal_text"].startswith("Eco Air")
    assert svc.pending_steer(agent, s["id"])["instruction"] is None  # consumed by revision

    done = svc.resolve_steering(s["id"], "accepted")
    assert done["status"] == "accepted"
    assert svc.pending_steer(agent, s["id"])["status"] == "accepted"
    events = [t["event"] for t in done["trajectory"]]
    assert events == ["steering.proposal_submitted", "steering.applied",
                      "steering.proposal_revised", "steering.accepted"]


def test_steering_never_authorizes_locked_or_undeclared(svc_agent):
    svc, agent = svc_agent
    with pytest.raises(SwitchboardError) as e:
        svc.submit_proposal(agent, "Pay?", "Send $500.", "payments", DIRS)
    assert e.value.code == "LOCKED_CATEGORY"
    s = svc.submit_proposal(agent, "Draft", "v1 text", "writing", DIRS[:2])
    with pytest.raises(SwitchboardError):
        svc.steer(s["id"], "top")  # edge never declared by the agent
    with pytest.raises(SwitchboardError):
        svc.steer(s["id"], "left", magnitude="hard")  # magnitude must be numeric
    # A steer alone can never close a session; only resolve can.
    svc.steer(s["id"], "left")
    assert svc.steering_session(s["id"])["status"] == "open"


def test_direction_validation_and_agent_ownership(svc_agent):
    svc, agent = svc_agent
    with pytest.raises(SwitchboardError):
        svc.submit_proposal(agent, "T", "P", "writing", DIRS[:1])  # need >= 2
    dup = [dict(DIRS[0]), dict(DIRS[0])]
    with pytest.raises(SwitchboardError):
        svc.submit_proposal(agent, "T", "P", "writing", dup)
    nolabel = [{"edge": "left", "label": "", "expected_effect": "x"}, DIRS[1]]
    with pytest.raises(SwitchboardError):
        svc.submit_proposal(agent, "T", "P", "writing", nolabel)
    s = svc.submit_proposal(agent, "T", "P", "writing", DIRS)
    other = svc.authenticate(svc.register_agent("intruder")["api_key"])
    with pytest.raises(SwitchboardError):
        svc.revise_proposal(other, s["id"], "hijacked")
    with pytest.raises(SwitchboardError):
        svc.pending_steer(other, s["id"])


def test_project_tag_roundtrips(svc_agent):
    svc, agent = svc_agent
    s = svc.submit_proposal(agent, "Pick a hotel", "City Inn $110.", "purchase", DIRS,
                            project="work-trip")
    assert s["project"] == "work-trip"
    assert svc.list_steering()[0]["project"] == "work-trip"


def test_taste_profile_counts_leans(svc_agent):
    svc, agent = svc_agent
    s = svc.submit_proposal(agent, "Pick", "v1", "purchase", DIRS)
    svc.steer(s["id"], "left")
    svc.revise_proposal(agent, s["id"], "v2")
    svc.steer(s["id"], "left")
    svc.steer(s["id"], "bottom")
    taste = svc.taste_profile("purchase")
    assert taste == [{"category": "purchase", "leans": [["Cheaper", 2], ["Simplify", 1]]}]
    assert svc.passport("purchase")["taste"] == [["Cheaper", 2], ["Simplify", 1]]
