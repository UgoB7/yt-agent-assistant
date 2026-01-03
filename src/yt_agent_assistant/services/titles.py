from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

from openai import OpenAI

from ..config import Settings
from ..utils import img_to_data_url, normalize_title, split_examples


class TitleService:
    """
    Wraps OpenAI calls for title ideation and scripture selection.
    """

    def __init__(self, settings: Settings, client: Optional[OpenAI] = None):
        self.settings = settings
        self.client = client or OpenAI()
        self.examples = split_examples(settings.openai.title_examples_input)
        self.devotional_examples = split_examples(settings.openai.devotional_examples_input)

    # ----- Title ideation --------------------------------------------
    def style_titles(self, img_path: Path) -> List[str]:
        examples_text = "\n".join(f"- {e}" for e in self.examples)
        data_url = img_to_data_url(img_path)
        resp = self.client.responses.create(
            model=self.settings.openai.model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You are a YouTube titling assistant. "
                                "Look at the image and return EXACTLY 20 original titles as a STRICT JSON object.\n"
                                "Constraints:\n"
                                "- Style: inspired by EXAMPLES (cadence/soft punctuation), no copy/paste.\n"
                                "- Relevance: reflect the image (gestures/symbols/ambience/location).\n"
                                "- Length: naturally aim ~55-65 chars when possible.\n\n"
                                f"EXAMPLES (style guide):\n{examples_text}\n\n"
                                'Return ONLY:\n{"titles": ["t1","t2",...,"t20"]}\n'
                                "Do not add any explanation before or after the JSON."
                            ),
                        },
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
        )
        return self._extract_titles(resp.output_text)

    def devotional_titles(self, img_path: Path) -> List[str]:
        examples_text = "\n".join(f"- {e}" for e in self.devotional_examples)
        data_url = img_to_data_url(img_path)
        resp = self.client.responses.create(
            model=self.settings.openai.model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You craft devotional YouTube titles (prayerful, surrender, comfort).\n"
                                "Look at the image and return EXACTLY 20 titles as a STRICT JSON object.\n"
                                "Constraints:\n"
                                "- Tone: heartfelt prayers or God speaking ('My child'), humble surrender, encouragement.\n"
                                "- Style: follow the cadence of the EXAMPLES (gentle pauses, en dashes, occasional pipes or [1 Hour]/1Hour tags).\n"
                                "- Relevance: echo the emotion or symbolism of the image (struggle, refuge, peace).\n"
                                "- Length: aim 45-80 characters; no emojis, no hashtags, no ALL CAPS.\n"
                                "- Keep reverent and truthful; avoid clickbait hooks.\n\n"
                                f"EXAMPLES (style guide):\n{examples_text}\n\n"
                                'Return ONLY:\n{"titles": ["t1","t2",...,"t20"]}\n'
                                "Do not add any explanation before or after the JSON."
                            ),
                        },
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
        )
        return self._extract_titles(resp.output_text)

    def click_titles(self, img_path: Path) -> List[str]:
        lang_hint = "\n".join(f"- {e}" for e in self.examples)
        data_url = img_to_data_url(img_path)
        resp = self.client.responses.create(
            model=self.settings.openai.model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You are a viral YouTube headline copywriter for a Christian channel about Jesus.\n"
                                "Look at the image and return EXACTLY 20 click-through-optimized titles as STRICT JSON.\n"
                                "Constraints:\n"
                                "- Hooks: urgency/curiosity/emotion-but respectful and truthful (no sensational lies).\n"
                                "- Include 'Jesus' or 'Christ' when natural.\n"
                                "- Length: aim 48-70 characters.\n"
                                "- Style: NO emojis, NO ALL CAPS, NO hashtags.\n"
                                "- Language: match the language of the EXAMPLES below (language hint only; do NOT copy their style).\n\n"
                                f"EXAMPLES (language hint only):\n{lang_hint}\n\n"
                                'Return ONLY:\n{"titles": ["t1","t2",...,"t20"]}\n'
                                "No explanation, JSON only."
                            ),
                        },
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
        )
        return self._extract_titles(resp.output_text)

    def guided_titles(self, img_path: Path, instruction: str) -> List[str]:
        lang_hint = "\n".join(f"- {e}" for e in self.examples)
        instruction = (instruction or "").strip()
        if not instruction:
            return []

        data_url = img_to_data_url(img_path)
        resp = self.client.responses.create(
            model=self.settings.openai.model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You write YouTube titles for a Christian channel about Jesus.\n"
                                "Look at the image and generate EXACTLY 20 titles as STRICT JSON, "
                                "following the USER INSTRUCTION below as the main theme or angle.\n"
                                "Constraints:\n"
                                "- Respect the instruction faithfully, but stay truthful and reverent.\n"
                                "- Reflect the image context when possible.\n"
                                "- Include 'Jesus' or 'Christ' if natural.\n"
                                "- Length: aim 48-70 characters.\n"
                                "- Language: match the language of the EXAMPLES (hint only; do not copy their style).\n\n"
                                f"EXAMPLES (language hint only):\n{lang_hint}\n\n"
                                f"USER INSTRUCTION:\n{instruction}\n\n"
                                'Return ONLY:\n{"titles": ["t1","t2",...,"t20"]}\n'
                                "No explanation, JSON only."
                            ),
                        },
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
        )
        return self._extract_titles(resp.output_text)

    # ----- Scripture references -------------------------------------
    def best_references(
        self, img_path: Path, chosen_title: str
    ) -> Tuple[List[str], List[int], List[Union[str, int]]]:
        data_url = img_to_data_url(img_path)
        prompt = (
            "You are a liturgical curator for YouTube videos about Jesus.\n"
            "Task: Given the VIDEO TITLE and the THUMBNAIL IMAGE, return three lists ranked from best to less relevant:\n"
            "1) gospels: exactly the BEST passages among the Four Gospels referencing as 'Book Chapter' (e.g., 'Marc 8', 'Luc 2' OR 'Mark 8', 'Luke 2'),\n"
            "2) psalms: a list of Psalm chapter NUMBERS only (integers),\n"
            "3) combined: an interleaved list mixing the best gospel entries (strings) and the best psalm numbers (ints).\n\n"
            "Diversify and rotate references: do NOT always repeat the same canonical passages; pick varied chapters that fit the title and image.\n"
            "STRICT OUTPUT FORMAT (JSON only, no prose):\n"
            '{"gospels": ["Marc 8","Luke 2","Matthew 5","John 14","Luke 4","Matthew 1","John 17"], '
            '"psalms": [3,59,120,67], '
            '"combined": ["Marc 8",3,"Luke 2","Matthew 5","John 14","Luke 4",59,120,"Matthew 1","John 17",67]}\n\n'
            "Rules:\n"
            "- The RANKING must depend on the title semantics AND the visual cues in the image you receive.\n"
            "- Prefer variety across calls: avoid overusing the same few chapters; explore different psalms/gospels that still fit.\n"
            "- Use the language that matches the TITLE: if the title is French, prefer 'Marc, Luc, Matthieu, Jean'; if English, use 'Mark, Luke, Matthew, John'.\n"
            "- 'psalms' MUST be integers only. No verse numbers, no ranges.\n"
            "- 'gospels' MUST be strings with 'Book Chapter' (no verse numbers).\n"
            "- Return JSON ONLY. No comments, no extra keys.\n"
        )

        resp = self.client.responses.create(
            model=self.settings.openai.model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_text", "text": f"VIDEO TITLE: {chosen_title}"},
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
        )

        raw = resp.output_text.strip()
        data = self._extract_json(raw)

        gospels = [s for s in data.get("gospels", []) if isinstance(s, str) and s.strip()]
        psalms = self._coerce_psalms(data.get("psalms", []))
        combined: List[Union[int, str]] = []
        for value in data.get("combined", []):
            if isinstance(value, int):
                combined.append(value)
            elif isinstance(value, str) and value.strip():
                combined.append(value.strip())
        return gospels, psalms, combined

    # ----- internal helpers ------------------------------------------
    def _extract_titles(self, raw: str) -> List[str]:
        payload = self._extract_json(raw)
        titles = [
            t.strip()
            for t in payload.get("titles", [])
            if isinstance(t, str) and t.strip()
        ]
        seen, deduped = set(), []
        for title in titles:
            norm = normalize_title(title)
            if norm not in seen:
                seen.add(norm)
                deduped.append(title)
        return deduped

    @staticmethod
    def _extract_json(raw: str) -> dict:
        text = raw.strip()
        if not text.startswith("{"):
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                text = text[start : end + 1]
        return json.loads(text)

    @staticmethod
    def _coerce_psalms(items: Sequence[Union[int, str]]) -> List[int]:
        out: List[int] = []
        for item in items:
            if isinstance(item, int):
                out.append(item)
            elif isinstance(item, str) and item.strip().isdigit():
                out.append(int(item.strip()))
        seen, deduped = set(), []
        for ps in out:
            if ps not in seen:
                seen.add(ps)
                deduped.append(ps)
        return deduped


def write_refs_lists(destination: Path, gospels: List[str], psalms: List[int], combined: List[Union[str, int]]) -> None:
    """
    Persist the scripture selection in a format that Resolve or other scripts can read.
    """

    def _to_json(lst):
        return json.dumps(lst, ensure_ascii=False)

    destination.mkdir(parents=True, exist_ok=True)
    (destination / "gospels_list.txt").write_text(_to_json(gospels) + "\n", encoding="utf-8")
    (destination / "psalms_list.txt").write_text(_to_json(psalms) + "\n", encoding="utf-8")
    (destination / "combined_list.txt").write_text(_to_json(combined) + "\n", encoding="utf-8")

    refs = [
        f"GOSPELS  = {_to_json(gospels)}",
        f"PSALMS   = {_to_json(psalms)}",
        f"BEST_REFS= {_to_json(combined)}",
    ]
    (destination / "refs_for_python.txt").write_text("\n".join(refs) + "\n", encoding="utf-8")
