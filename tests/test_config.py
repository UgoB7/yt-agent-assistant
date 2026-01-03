from yt_agent_assistant.config import EXAMPLE_CONFIG_PATH, Settings, load_settings


def test_load_settings_from_example():
    settings = load_settings(EXAMPLE_CONFIG_PATH)
    assert settings.core.fps == 30
    assert settings.paths.image_dir.name == "images"
    assert settings.paths.track_root.name == "runtime"


def test_target_seconds_computed():
    settings = Settings()
    assert settings.core.target_seconds > 0
