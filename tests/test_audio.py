from pathlib import Path

from yt_agent_assistant.config import Settings
from yt_agent_assistant.services.audio import AudioEngine


def test_preferred_head_placed_first():
    settings = Settings()
    engine = AudioEngine(settings)
    pool = [
        {
            "path": Path("ps23.mp3"),
            "type": "psalm",
            "psalm_num": 23,
            "gospel_name": None,
            "gospel_chapter": None,
            "has_num": True,
            "label": "psalm 23",
            "dur": 10.0,
        },
        {
            "path": Path("ps91.mp3"),
            "type": "psalm",
            "psalm_num": 91,
            "gospel_name": None,
            "gospel_chapter": None,
            "has_num": True,
            "label": "psalm 91",
            "dur": 12.0,
        },
        {
            "path": Path("mark4.mp3"),
            "type": "gospel",
            "psalm_num": None,
            "gospel_name": "marc",
            "gospel_chapter": 4,
            "has_num": True,
            "label": "Marc 4",
            "dur": 15.0,
        },
    ]

    selection, total = engine.build_selection(
        pool_items=pool,
        target_seconds=20.0,
        preferred_head=[23],
        preferred_candidates=pool,
        seed=123,
    )

    assert selection[0]["psalm_num"] == 23
    assert total >= 20.0
