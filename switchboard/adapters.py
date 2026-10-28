import json

import httpx

from .config import settings


class BasetenReasoningAdapter:
    """T3: Baseten OpenAI-compatible hosted models. Any failure returns None -> caller defers."""

    def __init__(self, cfg=None):
        self.cfg = cfg or settings

    @property
    def enabled(self):
        return bool(self.cfg.enable_t3 and self.cfg.baseten_api_key)

    def _client(self):
        return httpx.Client(base_url=self.cfg.baseten_base_url,
                            headers={"Authorization": f"Bearer {self.cfg.baseten_api_key}"}, timeout=30)

    def generate(self, prompt: str, system: str = "Return only JSON."):
        if not self.enabled:
            return None
        try:
            with self._client() as c:
                r = c.post("/chat/completions", json={
                    "model": self.cfg.baseten_model_id,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": prompt}]})
                r.raise_for_status()
                data = r.json()
            return {"text": data["choices"][0]["message"]["content"],
                    "model": data.get("model"), "usage": data.get("usage", {})}
        except Exception:
            return None

    def match(self, question_text, category, rule_versions):
        """Ask the model to pick a rule version id from candidates; validated upstream by scope checks."""
        if not self.enabled or not rule_versions:
            return None
        candidates = [{"id": rv["id"], "example": rv["_predicate"].get("example_question", "")}
                      for rv in rule_versions]
        out = self.generate(
            f"Question: {question_text}\nCandidates: {json.dumps(candidates)}\n"
            'Reply {"rule_version_id": "<id or null>", "confidence": 0..1}')
        if not out:
            return None
        try:
            parsed = json.loads(out["text"])
        except Exception:
            return None
        rid = parsed.get("rule_version_id")
        for rv in rule_versions:
            if rv["id"] == rid:
                return {"rule_version": rv, "score": float(parsed.get("confidence", 0)),
                        "score_kind": "calibrated_estimate", "match_type": "semantic"}
        return None


class ModalReasoningAdapter:
    """T3 via a Modal-deployed OpenAI-compatible chat endpoint (Muse Spark Open).

    Auth: Bearer <MODAL_PROXY_TOKEN_ID>.<MODAL_PROXY_TOKEN_SECRET>.
    Any failure returns None -> caller defers. Never guesses.
    """

    def __init__(self, cfg=None):
        self.cfg = cfg or settings

    @property
    def enabled(self):
        return bool(self.cfg.enable_t3 and self.cfg.modal_chat_url
                    and self.cfg.modal_proxy_token_id and self.cfg.modal_proxy_token_secret)

    def _headers(self):
        h = {"Content-Type": "application/json",
             "Authorization": f"Bearer {self.cfg.modal_proxy_token_id}.{self.cfg.modal_proxy_token_secret}"}
        if self.cfg.modal_routing_affinity_key:
            h["Modal-Routing-Affinity-Key"] = self.cfg.modal_routing_affinity_key
        return h

    def generate(self, prompt: str, system: str = "Return only JSON.", response_format=None,
                 tools=None, temperature: float = 0.3, max_tokens: int = 2048):
        if not self.enabled:
            return None
        body = {"model": self.cfg.modal_chat_model,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": prompt}],
                "temperature": temperature, "max_tokens": max_tokens,
                "top_p": 0.95, "stream": False, "reasoning_effort": "medium"}
        if response_format is not None:
            body["response_format"] = response_format
        if tools is not None:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        try:
            with httpx.Client(timeout=120) as c:
                r = c.post(self.cfg.modal_chat_url, headers=self._headers(), json=body)
                r.raise_for_status()
                data = r.json()
            choice = data["choices"][0]["message"]
            return {"text": choice.get("content") or "", "model": data.get("model"),
                    "usage": data.get("usage", {}), "tool_calls": choice.get("tool_calls")}
        except Exception:
            return None

    def match(self, question_text, category, rule_versions):
        if not self.enabled or not rule_versions:
            return None
        candidates = [{"id": rv["id"], "example": rv["_predicate"].get("example_question", "")}
                      for rv in rule_versions]
        out = self.generate(
            f"Question: {question_text}\nCandidates: {json.dumps(candidates)}\n"
            'Reply {"rule_version_id": "<id or null>", "confidence": 0..1}')
        if not out:
            return None
        try:
            parsed = json.loads(out["text"])
        except Exception:
            return None
        for rv in rule_versions:
            if rv["id"] == parsed.get("rule_version_id"):
                return {"rule_version": rv, "score": float(parsed.get("confidence", 0)),
                        "score_kind": "calibrated_estimate", "match_type": "semantic"}
        return None


class MetaReasoningAdapter:
    """T3 via Meta Model API (OpenAI-compatible, https://api.meta.ai/v1). Failure -> None."""

    def __init__(self, cfg=None):
        self.cfg = cfg or settings

    @property
    def enabled(self):
        return bool(self.cfg.enable_t3 and self.cfg.meta_api_key)

    def generate(self, prompt: str, system: str = "Return only JSON."):
        if not self.enabled:
            return None
        try:
            with httpx.Client(base_url=self.cfg.meta_base_url,
                              headers={"Authorization": f"Bearer {self.cfg.meta_api_key}"}, timeout=60) as c:
                r = c.post("/chat/completions", json={
                    "model": self.cfg.meta_model,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": prompt}]})
                r.raise_for_status()
                data = r.json()
            return {"text": data["choices"][0]["message"]["content"],
                    "model": data.get("model"), "usage": data.get("usage", {})}
        except Exception:
            return None

    def match(self, question_text, category, rule_versions):
        if not self.enabled or not rule_versions:
            return None
        candidates = [{"id": rv["id"], "example": rv["_predicate"].get("example_question", "")}
                      for rv in rule_versions]
        out = self.generate(
            f"Question: {question_text}\nCandidates: {json.dumps(candidates)}\n"
            'Reply {"rule_version_id": "<id or null>", "confidence": 0..1}')
        if not out:
            return None
        try:
            parsed = json.loads(out["text"])
        except Exception:
            return None
        for rv in rule_versions:
            if rv["id"] == parsed.get("rule_version_id"):
                return {"rule_version": rv, "score": float(parsed.get("confidence", 0)),
                        "score_kind": "calibrated_estimate", "match_type": "semantic"}
        return None


import re

_SAM_BOX = re.compile(
    r"<\|box;x1=(?P<x1>\d+);y1=(?P<y1>\d+);x2=(?P<x2>\d+);y2=(?P<y2>\d+);w=(?P<w>\d+);h=(?P<h>\d+)\|>")
_SAM_MASK = re.compile(r"<\|mask;x=(?P<x>\d+);y=(?P<y>\d+);data=(?P<data>[^|]+)\|>")


def parse_sam_output(text: str, label: str = "") -> list:
    """Parse SAM 3.1 Responses output_text: boxes + encoded masks, one record per object."""
    objects = []
    boxes = list(_SAM_BOX.finditer(text or ""))
    masks = list(_SAM_MASK.finditer(text or ""))
    for i, b in enumerate(boxes):
        obj = {"id": f"obj-{i}", "label": label,
               "bbox": {k: int(b.group(k)) for k in ("x1", "y1", "x2", "y2", "w", "h")},
               "mask_encoding": "lossless" if i < len(masks) and "~" in masks[i].group("data") else "unknown",
               "mask_data_len": len(masks[i].group("data")) if i < len(masks) else 0}
        objects.append(obj)
    return objects


class MetaSegmentationAdapter:
    """SAM 3.1 via Meta Responses API. Returns grounded objects or None on any failure."""

    def __init__(self, cfg=None):
        self.cfg = cfg or settings

    @property
    def enabled(self):
        return bool(self.cfg.meta_api_key)

    def segment(self, image_b64: str, phrase: str, mime: str = "image/webp"):
        if not self.enabled or not image_b64:
            return None
        try:
            with httpx.Client(base_url=self.cfg.meta_base_url,
                              headers={"Authorization": f"Bearer {self.cfg.meta_api_key}"}, timeout=180) as c:
                r = c.post("/responses", json={
                    "model": self.cfg.meta_segmentation_model,
                    "input": [{"role": "user", "content": [
                        {"type": "input_text", "text": phrase},
                        {"type": "input_image", "image_url": f"data:{mime};base64,{image_b64}"}]}]})
                r.raise_for_status()
                data = r.json()
            out = data.get("output", [])
            text = out[0]["content"][0]["text"] if out and out[0].get("content") else ""
            objects = parse_sam_output(text, label=phrase)
            # Rasterize masks to overlay PNGs when the text carried mask records.
            if objects and "<|mask;" in text:
                try:
                    from .masks import overlay_pngs_b64
                    overlays = overlay_pngs_b64(text, objects[0]["bbox"]["w"], objects[0]["bbox"]["h"])
                    for obj, overlay in zip(objects, overlays):
                        obj["overlay_png_b64"] = overlay
                except Exception:
                    pass  # boxes alone are still valid evidence
            return {"objects": objects, "raw_text_len": len(text),
                    "model": self.cfg.meta_segmentation_model}
        except Exception:
            return None


class MetaImageAdapter:
    """Muse Image via /v1/images/generations. Output is always labeled a generated concept."""

    def __init__(self, cfg=None):
        self.cfg = cfg or settings

    @property
    def enabled(self):
        return bool(self.cfg.meta_api_key)

    def generate_or_edit(self, prompt: str, reference_images=None):
        if not self.enabled:
            return None
        try:
            with httpx.Client(base_url=self.cfg.meta_base_url,
                              headers={"Authorization": f"Bearer {self.cfg.meta_api_key}"}, timeout=300) as c:
                r = c.post("/images/generations", json={
                    "model": self.cfg.meta_image_model, "prompt": prompt, "n": 1})
                r.raise_for_status()
                data = r.json()
            item = data["data"][0]
            return {"b64_json": item.get("b64_json"), "url": item.get("url"),
                    "generated_preview": True, "model": self.cfg.meta_image_model}
        except Exception:
            return None

    def edit(self, prompt: str, image_b64: str, mime: str = "image/webp"):
        """Muse Image edit via multipart /images/edits. Result is a concept preview, never evidence."""
        if not self.enabled or not image_b64:
            return None
        try:
            import base64 as _b64
            raw = _b64.b64decode(image_b64)
            ext = "png" if "png" in mime else "jpg" if "jpeg" in mime or "jpg" in mime else "webp"
            with httpx.Client(base_url=self.cfg.meta_base_url,
                              headers={"Authorization": f"Bearer {self.cfg.meta_api_key}"}, timeout=300) as c:
                r = c.post("/images/edits",
                           files={"image": (f"scene.{ext}", raw, mime)},
                           data={"model": self.cfg.meta_image_model, "prompt": prompt})
                r.raise_for_status()
                data = r.json()
            item = data["data"][0]
            return {"b64_json": item.get("b64_json"), "url": item.get("url"),
                    "generated_preview": True, "model": self.cfg.meta_image_model}
        except Exception:
            return None


def reasoning_adapter(cfg=None):
    """Pick the configured T3 provider, falling back through the others. All fail safe."""
    cfg = cfg or settings
    if not cfg.enable_t3:
        return None
    builders = {"modal": ModalReasoningAdapter, "baseten": BasetenReasoningAdapter,
                "meta": MetaReasoningAdapter}
    order = [cfg.reasoning_provider] + [p for p in builders if p != cfg.reasoning_provider]
    for name in order:
        adapter = builders[name](cfg)
        if adapter.enabled:
            return adapter
    return None


class ModalAdapter:
    """Generic Modal web-endpoint adapter for segmentation / image / T2. Disabled without a URL."""

    def __init__(self, url: str = ""):
        self.url = url

    @property
    def enabled(self):
        return bool(self.url)

    def call(self, payload: dict):
        if not self.enabled:
            return None
        try:
            with httpx.Client(timeout=60) as c:
                r = c.post(self.url, json=payload)
                r.raise_for_status()
                return r.json()
        except Exception:
            return None

    def segment(self, image_ref: str, text_prompt: str):
        out = self.call({"image_ref": image_ref, "text_prompt": text_prompt})
        return out  # {objects: [{id,label,bbox,mask_ref}]} or None

    def generate_or_edit(self, prompt: str, reference_images=None):
        out = self.call({"prompt": prompt, "reference_images": reference_images or []})
        if out is not None:
            out["generated_preview"] = True
        return out
