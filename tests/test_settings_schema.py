from shellac.config import Config
from shellac.settings_schema import (
    all_fields,
    changes_from_draft,
    default_value,
    is_enabled,
    validate_schema,
    values_from_config,
)


def test_schema_matches_the_config_definition():
    assert validate_schema() == []


def test_unchanged_values_produce_no_changes():
    saved = values_from_config(Config())
    assert changes_from_draft(saved, dict(saved)) == {}


def test_changed_value_is_written_and_default_value_removes_the_line():
    config = Config()
    config.appearance.font_size = 14.0
    saved = values_from_config(config)
    draft = {("appearance", "font_size"): 14.0, ("appearance", "padding"): 20.0}
    assert changes_from_draft(saved, draft) == {("appearance", "padding"): 20}
    draft = {("appearance", "font_size"): default_value_of("appearance", "font_size")}
    assert changes_from_draft(saved, draft) == {("appearance", "font_size"): None}


def default_value_of(section, key):
    return default_value(next(f for f in all_fields() if f.path == (section, key)))


def test_dependent_fields_follow_their_switch():
    item = next(f for f in all_fields() if f.key == "dark_theme")
    assert not is_enabled(item, {("appearance", "follow_system_scheme"): False})
    assert is_enabled(item, {("appearance", "follow_system_scheme"): True})
