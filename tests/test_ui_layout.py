"""Home-screen contract: the real inbox is the home panel.

The demo stage stays behind the optional guided-sandbox dialog, never
rendered as the primary home panel.
"""
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "frontend" / "src" / "App.tsx"


def _src() -> str:
    return APP.read_text(encoding="utf-8")


def test_inbox_is_home_and_demo_is_collapsed_by_default():
    src = _src()
    assert "const [showDemo, setShowDemo] = useState(false)" in src
    assert 'aria-haspopup="dialog"' in src
    demo = src.index("{showDemo && (")
    dialog = src.index("<dialog", demo)
    end_dialog = src.index("</dialog>", dialog)
    assert src.index("<InboxPanel") < demo
    assert dialog < src.index("<DecisionStage") < end_dialog
    assert 'aria-labelledby="demo-title"' in src[dialog:end_dialog]
    assert "This won’t change a real agent’s work." in src[dialog:end_dialog]
