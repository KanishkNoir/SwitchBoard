"""Home-screen contract: the real inbox is the home panel.

The steering stage is a demo sandbox. It must stay demoted behind the
collapsed Demo playground, never rendered as the primary home panel.
"""
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "frontend" / "src" / "App.tsx"


def _src() -> str:
    return APP.read_text(encoding="utf-8")


def test_inbox_is_home_and_demo_is_collapsed_by_default():
    src = _src()
    # Demo starts hidden; the toggle is the only way in.
    assert "useState(false)" in src and "showDemo" in src
    assert "Demo playground" in src
    # The inbox renders in the main home grid, before the demo zone.
    assert src.index("<InboxPanel") < src.index("Demo playground")
    # DecisionStage (steering) is only reachable inside the demo zone.
    assert src.index("Demo playground") < src.index("<DecisionStage")
    # The demo must be honestly labelled as not part of the real flow.
    assert "Not part of the real flow" in src
