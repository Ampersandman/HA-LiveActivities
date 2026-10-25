"""Analysis-only migration tests; no Home Assistant or YAML dependency."""

import json
from copy import deepcopy

import pytest

from tools.migrate_pushward import convert_automations, main


def action(action_name, **data):
    return {"action": f"pushward.{action_name}", "data": data}


def test_registration_is_folded_into_first_visible_start():
    original = {
        "alias": "Washer",
        "actions": [
            action("create_activity", slug="washer", name="Laundry"),
            action(
                "update_activity_generic",
                slug="washer",
                state="ongoing",
                state_text="Rinsing",
                progress=0.42,
                icon="mdi:washing-machine",
            ),
            action(
                "update_activity_generic", slug="washer", state="ongoing", state_text="Spinning", progress=0.9
            ),
            action("end_activity", slug="washer"),
        ],
    }
    saved = deepcopy(original)
    proposal, warnings = convert_automations(original)
    actions = proposal["actions"]
    assert [item["action"] for item in actions] == [
        "home_island.start",
        "home_island.update",
        "home_island.end",
    ]
    assert actions[0]["data"] == {
        "activity_id": "washer",
        "title": "Laundry",
        "preset": "generic",
        "message": "Rinsing",
        "progress": 420,
        "progress_max": 1000,
        "icon": "mdi:washing-machine",
    }
    assert actions[-1]["data"] == {"activity_id": "washer", "immediate": True}
    assert original == saved
    assert any("layout differs" in warning for warning in warnings)


def test_create_alone_is_not_changed_into_a_visible_start():
    original = [action("create_activity", slug="reserved", name="Future activity")]
    proposal, warnings = convert_automations(original)
    assert proposal == original
    assert "registration" in warnings[0]


@pytest.mark.parametrize("template", ["board", "timeline", "log", "media", "approval"])
def test_advanced_layouts_are_preserved_for_manual_review(template):
    original = action(f"update_activity_{template}", slug="advanced", state="ongoing")
    proposal, warnings = convert_automations(original)
    assert proposal == original
    assert any("no native layout equivalent" in warning for warning in warnings)


@pytest.mark.parametrize(
    "fields",
    [
        {"image_url": "https://example.invalid/private-image"},
        {"tap_action": {"url": "https://example.invalid", "headers": {"Authorization": "SECRET"}}},
        {"completion_message": "Finished"},
        {"icon": "washer"},
        {"progress": "{{ states('sensor.progress') }}"},
        {"progress": 1.5},
    ],
)
def test_lossy_or_invalid_content_is_not_silently_migrated(fields):
    original = [action("update_activity_generic", slug="private", state="ongoing", **fields)]
    proposal, warnings = convert_automations(original)
    assert proposal == original
    assert warnings
    assert "SECRET" not in " ".join(warnings)
    assert "private-image" not in " ".join(warnings)


def test_failed_update_does_not_remove_earlier_registration():
    original = [
        action("create_activity", slug="x", name="X"),
        action("update_activity_generic", slug="x", image_url="unsupported"),
    ]
    proposal, _ = convert_automations(original)
    assert proposal == original


def test_different_ttl_priority_semantics_require_manual_review():
    original = [
        action("create_activity", slug="x", name="X", priority=5),
        action("update_activity_generic", slug="x", state="ongoing"),
    ]
    proposal, warnings = convert_automations(original)
    assert proposal == original
    assert any("different native semantics" in warning for warning in warnings)


def test_nested_actions_legacy_service_and_template_specific_mapping():
    document = [
        {
            "alias": "Printer",
            "action": [
                {
                    "choose": [
                        {
                            "conditions": [],
                            "sequence": [
                                {
                                    "service": "pushward.update_activity",
                                    "data": {
                                        "slug": "printer",
                                        "template": "steps",
                                        "state": "ONGOING",
                                        "current_step": 2,
                                        "total_steps": 5,
                                        "state_text": "Heating",
                                        "subtitle": "Bed",
                                    },
                                },
                            ],
                        }
                    ]
                }
            ],
        }
    ]
    proposal, warnings = convert_automations(document)
    native = proposal[0]["action"][0]["choose"][0]["sequence"][0]
    assert native == {
        "action": "home_island.update",
        "data": {
            "activity_id": "printer",
            "preset": "steps",
            "message": "Heating · Bed",
            "progress": 2,
            "step_total": 5,
            "progress_max": 5,
        },
    }
    assert "requires" in warnings[0]


def test_gauge_and_countdown_field_mapping():
    original = [
        action(
            "update_activity_gauge",
            slug="temp",
            state="ongoing",
            value=21.5,
            min_value=-10,
            max_value=40,
            unit="°C",
        ),
        action("update_activity_countdown", slug="timer", state="ongoing", remaining_time=120),
    ]
    proposal, _ = convert_automations(original)
    assert proposal[0]["data"]["progress_min"] == -10
    assert proposal[0]["data"]["critical_text"] == "21.5 °C"
    assert proposal[1]["data"]["remaining_seconds"] == 120


def test_non_pushward_actions_and_metadata_survive():
    original = [
        {"action": "light.turn_on", "target": {"entity_id": "light.hall"}},
        {"alias": "Remove", "enabled": True, "service": "pushward.delete_activity", "data": {"slug": "x"}},
    ]
    proposal, _ = convert_automations(original)
    assert proposal[0] == original[0]
    assert proposal[1]["alias"] == "Remove"
    assert proposal[1]["enabled"] is True


def test_completion_message_needs_review():
    original = action("end_activity", slug="x", completion_message="Complete")
    proposal, warnings = convert_automations(original)
    assert proposal == original
    assert "final update" in warnings[0]


def test_invalid_progress_does_not_leak_value_in_warnings():
    original = action("update_activity_generic", slug="x", state="ongoing", progress="SECRET")
    proposal, warnings = convert_automations(original)
    assert proposal == original
    assert warnings
    assert "SECRET" not in " ".join(warnings)


def test_cli_never_overwrites_source_or_output(tmp_path, capsys):
    source = tmp_path / "automation.json"
    raw = json.dumps([action("delete_activity", slug="x")])
    source.write_text(raw, encoding="utf-8")
    assert main([str(source), "--output", str(source)]) == 2
    assert source.read_text(encoding="utf-8") == raw
    target = tmp_path / "proposal.json"
    assert main([str(source), "--output", str(target)]) == 0
    assert json.loads(target.read_text(encoding="utf-8"))[0]["action"] == "home_island.end"
    assert main([str(source), "--output", str(target)]) == 2
    assert "Proposal only" in capsys.readouterr().err
