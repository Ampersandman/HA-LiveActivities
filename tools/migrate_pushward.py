"""Propose a conservative migration of user-supplied automations; never call HA.

The conversion engine uses only the standard library. YAML CLI input/output needs
PyYAML (a development tool dependency, not an integration requirement).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

NATIVE_PRESETS = {"generic", "countdown", "steps", "alert", "gauge"}
COMMON_FIELDS = {
    "slug",
    "state",
    "state_text",
    "subtitle",
    "icon",
    "progress",
    "accent_color",
    "background_color",
    "text_color",
    "remaining_time",
    "url",
    "template",
}
PRESET_FIELDS = {
    "generic": set(),
    "countdown": set(),
    "steps": {"current_step", "total_steps"},
    "alert": {"severity"},
    "gauge": {"value", "min_value", "max_value", "unit"},
}


def _action_name(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    value = item.get("action", item.get("service", ""))
    return value if isinstance(value, str) else ""


def _number(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as err:
        raise ValueError("expected a finite numeric value") from err
    if not math.isfinite(number):
        raise ValueError("number must be finite")
    return number


def _content(data: dict[str, Any], preset: str) -> dict[str, Any]:
    unsupported = set(data) - COMMON_FIELDS - PRESET_FIELDS[preset]
    if unsupported:
        raise ValueError("unsupported fields: " + ", ".join(sorted(unsupported)))
    if not isinstance(data.get("slug"), str) or not data["slug"].strip():
        raise ValueError("a string slug is required")
    result: dict[str, Any] = {"activity_id": data["slug"], "preset": preset}
    text = [data[key] for key in ("state_text", "subtitle") if data.get(key)]
    if any(not isinstance(value, str) for value in text):
        raise ValueError("state_text/subtitle must be strings")
    if text:
        result["message"] = " · ".join(text)
    for old, new in {
        "accent_color": "accent_color",
        "text_color": "text_color",
        "background_color": "background_color",
        "remaining_time": "remaining_seconds",
        "url": "url",
        "severity": "severity",
    }.items():
        if old in data:
            result[new] = data[old]
    if data.get("icon"):
        if not isinstance(data["icon"], str) or not data["icon"].startswith("mdi:"):
            raise ValueError("SF Symbols require choosing an equivalent mdi: icon")
        result["icon"] = data["icon"]
    if "progress" in data:
        value = data["progress"]
        if isinstance(value, str) and ("{{" in value or "{%" in value):
            # Arbitrary Jinja statements cannot safely be wrapped or rescaled.
            raise ValueError("templated fractional progress requires manual rescaling to 0–100")
        number = _number(value)
        if not 0 <= number <= 1:
            raise ValueError("Pushward fractional progress must be between 0 and 1")
        result.update(progress=round(number * 1000), progress_max=1000)
    if preset == "steps":
        if "current_step" in data:
            result["progress"] = data["current_step"]
        if "total_steps" in data:
            result["step_total"] = data["total_steps"]
            result["progress_max"] = data["total_steps"]
    if preset == "gauge":
        for old, new in {
            "value": "progress",
            "min_value": "progress_min",
            "max_value": "progress_max",
        }.items():
            if old in data:
                result[new] = data[old]
        if "unit" in data:
            # Preserve the value/unit as supplementary text; the native gauge is a bar.
            if "value" not in data or not isinstance(data["unit"], str):
                raise ValueError("gauge unit needs a value and a string unit")
            result["critical_text"] = f"{data['value']} {data['unit']}".strip()
    return result


def convert_automations(document: Any) -> tuple[Any, list[str]]:
    """Return a new proposal and redacted structural warnings.

    Unsupported Pushward actions are left intact, making incomplete migration
    explicit. Input is never mutated. Service arguments are never executed.
    """
    warnings: list[str] = []

    def warn(path: str, reason: str) -> None:
        warnings.append(f"{path}: {reason}")

    def convert_list(items: list[Any], path: str) -> list[Any]:
        output: list[Any] = []
        # A create registers an initially ended Pushward object; it must not become
        # a visible native start until a later ongoing update in the same sequence.
        creates: dict[str, tuple[int, dict[str, Any]]] = {}
        ambiguous_creates: set[str] = set()
        folded: set[int] = set()
        for index, item in enumerate(items):
            if _action_name(item) == "pushward.create_activity":
                data = item.get("data", {})
                if isinstance(data, dict) and isinstance(data.get("slug"), str):
                    if data["slug"] in creates:
                        ambiguous_creates.add(data["slug"])
                    creates[data["slug"]] = (index, data)
        for index, item in enumerate(items):
            item_path = f"{path}[{index}]"
            name = _action_name(item)
            if not name.startswith("pushward."):
                output.append(walk(item, item_path))
                continue
            if name == "pushward.create_activity":
                output.append(deepcopy(item))  # removed only after a successful fold
                continue
            data = item.get("data", {})
            if not isinstance(data, dict):
                warn(item_path, "unchanged: non-mapping service data")
                output.append(deepcopy(item))
                continue
            replacement: dict[str, Any] | None = None
            try:
                if set(item) - {"action", "service", "data", "alias", "enabled"}:
                    raise ValueError("action metadata requires manual review")
                if name in {"pushward.end_activity", "pushward.delete_activity"}:
                    if set(data) - {"slug", "completion_message"}:
                        raise ValueError("unsupported end/delete fields")
                    if not isinstance(data.get("slug"), str):
                        raise ValueError("a string slug is required")
                    if data.get("completion_message"):
                        raise ValueError(
                            "completion text needs an explicit Home Island final update before end"
                        )
                    replacement = {
                        "action": "home_island.end",
                        "data": {"activity_id": data["slug"], "immediate": True},
                    }
                elif name == "pushward.update_activity" or name.startswith("pushward.update_activity_"):
                    preset = (
                        data.get("template", "generic")
                        if name == "pushward.update_activity"
                        else name.removeprefix("pushward.update_activity_")
                    )
                    if preset not in NATIVE_PRESETS:
                        raise ValueError(
                            "template needs the optional native iOS app; no native layout equivalent"
                        )
                    if "template" in data and data["template"] != preset:
                        raise ValueError("conflicting template and action name")
                    state = data.get("state")
                    if not isinstance(state, str) or state.lower() != "ongoing":
                        raise ValueError(
                            "ended/templated state needs an explicit final update and end sequence"
                        )
                    new_data = _content(data, preset)
                    action = "home_island.update"
                    previous = creates.get(data["slug"])
                    if data["slug"] in ambiguous_creates:
                        raise ValueError("multiple registrations for this slug need manual review")
                    if previous and previous[0] < index and previous[0] not in folded:
                        create_index, create_data = previous
                        if set(create_data) - {"slug", "name"}:
                            raise ValueError("create priority/TTL settings have different native semantics")
                        create_action = items[create_index]
                        if set(create_action) - {"action", "service", "data", "alias"}:
                            raise ValueError("conditional create cannot safely be folded")
                        if create_data.get("name"):
                            if not isinstance(create_data["name"], str):
                                raise ValueError("create name must be a string")
                            new_data["title"] = create_data["name"]
                        folded.add(create_index)
                        action = "home_island.start"
                        warn(
                            item_path,
                            "folded prior object registration into first visible start; native layout differs",
                        )
                    else:
                        warn(
                            item_path,
                            "converted update requires the same activity_id to have been started by Home Island",
                        )
                    replacement = {"action": action, "data": new_data}
                else:
                    raise ValueError("unsupported Pushward action")
            except (TypeError, ValueError) as err:
                warn(item_path, f"unchanged: {err}")
            if replacement is None:
                output.append(deepcopy(item))
            else:
                for key in ("alias", "enabled"):
                    if key in item:
                        replacement[key] = deepcopy(item[key])
                output.append(replacement)
        for create_index, _ in creates.values():
            if create_index not in folded:
                warn(
                    f"{path}[{create_index}]",
                    "unchanged object registration; no safely convertible later start in this sequence",
                )
        return [item for index, item in enumerate(output) if index not in folded]

    def walk(value: Any, path: str) -> Any:
        if isinstance(value, list):
            return convert_list(value, path)
        if isinstance(value, dict):
            if _action_name(value).startswith("pushward."):
                converted = convert_list([value], path)
                return converted[0]
            return {key: walk(item, f"{path}.{key}") for key, item in value.items()}
        return deepcopy(value)

    return walk(document, "$"), warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="user-supplied YAML or JSON; never overwritten")
    parser.add_argument("--output", type=Path, help="new proposal file; must not already exist")
    args = parser.parse_args(argv)
    try:
        raw = args.input.read_text(encoding="utf-8-sig")
        is_json = args.input.suffix.lower() == ".json"
        if is_json:
            document = json.loads(raw)
        else:
            try:
                import yaml
            except ImportError:
                parser.error("YAML input needs PyYAML; install the development requirements or use JSON")
            try:
                document = yaml.safe_load(raw)
            except yaml.YAMLError:
                print("Migration failed: invalid YAML (input content omitted)", file=sys.stderr)
                return 2
        proposal, warnings = convert_automations(document)
        if is_json:
            rendered = json.dumps(proposal, indent=2, ensure_ascii=False) + "\n"
        else:
            rendered = yaml.safe_dump(proposal, sort_keys=False, allow_unicode=True)
        if args.output:
            with args.output.open("x", encoding="utf-8") as target:
                target.write(rendered)
        else:
            sys.stdout.write(rendered)
        for warning in warnings:
            print(warning, file=sys.stderr)
        print("Proposal only. Review all remaining Pushward actions before installation.", file=sys.stderr)
        return 0
    except (OSError, ValueError) as err:
        print(f"Migration failed: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
