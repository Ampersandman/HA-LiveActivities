"""Verify installation artifacts that are not imported by Python tests."""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_installation_metadata_and_action_descriptions():
    component = ROOT / "custom_components" / "home_island"
    manifest = json.loads((component / "manifest.json").read_text())
    assert manifest["domain"] == "home_island"
    assert manifest["config_flow"] is True
    assert manifest["requirements"] == []
    assert manifest["version"]
    assert json.loads((ROOT / "hacs.json").read_text())["homeassistant"] == "2026.7.0"
    services = yaml.safe_load((component / "services.yaml").read_text())
    assert set(services) == {"start", "update", "end", "test"}
    for service in services.values():
        assert service["name"] and service["description"]
        for field in service["fields"].values():
            assert field["description"] and field["selector"]
    assert services["start"]["fields"]["activity_id"]["required"] is True
    assert "activity_id" in services["end"]["fields"]


def test_examples_and_translations_parse():
    automations = yaml.safe_load((ROOT / "examples" / "automations.yaml").read_text())
    assert len(automations) >= 3
    assert all(automation["triggers"] and automation["actions"] for automation in automations)
    component = ROOT / "custom_components" / "home_island"
    english = json.loads((component / "translations" / "en.json").read_text())
    assert english == json.loads((component / "strings.json").read_text())
