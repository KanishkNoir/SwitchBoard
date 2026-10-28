from switchboard.adapters import parse_sam_output
from switchboard.agents import run_visual_scout

SAMPLE = ("<0f>0<|box;x1=130;y1=132;x2=595;y2=934;w=1920;h=1280|>"
          "<|mask;x=0;y=0;data=803,466,~abc|>"
          "1<|box;x1=589;y1=407;x2=1394;y2=988;w=1920;h=1280|>"
          "<|mask;x=0;y=0;data=582,806,~xyz|>")


def test_parse_sam_output_boxes():
    objs = parse_sam_output(SAMPLE, label="lamp")
    assert len(objs) == 2
    assert objs[0]["bbox"] == {"x1": 130, "y1": 132, "x2": 595, "y2": 934, "w": 1920, "h": 1280}
    assert objs[0]["mask_encoding"] == "lossless" and objs[0]["mask_data_len"] > 0
    assert parse_sam_output("", label="x") == []


class FakeSeg:
    def segment(self, image_b64, phrase, mime="image/webp"):
        return {"objects": [{"id": "obj-0", "label": phrase, "bbox": {"x1": 1, "y1": 2, "x2": 3, "y2": 4, "w": 10, "h": 10}}]}


class BrokenSeg:
    def segment(self, image_b64, phrase, mime="image/webp"):
        return None


def test_visual_scout_grounds_objects():
    payload, evidence = run_visual_scout("t1", "calmer desk", image_b64="AAAA",
                                         phrases=["lamp"], seg_adapter=FakeSeg())
    assert evidence["objects"][0]["label"] == "lamp"
    assert "lamp" in payload["question"]
    assert {a["edge"] for a in payload["actions"]} == {"top", "left", "right", "bottom"}


def test_visual_scout_fails_safe_without_segmentation():
    payload, evidence = run_visual_scout("t1", "calmer desk", image_b64="AAAA",
                                         phrases=["lamp"], seg_adapter=BrokenSeg())
    assert evidence["objects"] == []  # no invented objects
    assert payload["question"]  # question still asked
