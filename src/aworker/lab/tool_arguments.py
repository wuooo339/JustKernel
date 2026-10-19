"""Narrow compatibility normalization before the existing tool schemas/permissions."""

import json


# ---- normalize_arguments ----------------------------------------------------
def normalize_arguments(name: str, arguments: dict) -> dict:
    result = dict(arguments)
    if (
        name in {"read_file", "write_file", "edit_file"}
        and "file_path" not in result
        and "path" in result
    ):
        result["file_path"] = result.pop("path")
    fields = {
        "run_python": {"arguments": str},
        "simulate_kernel": {"case_ids": str, "learned_from": str},
        "record_experiment_plan": {"case_ids": str},
        "write_todos": {"todos": dict},
    }
    for field, item_type in fields.get(name, {}).items():
        if not isinstance(result.get(field), str):
            continue
        try:
            parsed = json.loads(result[field])
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, list) and all(isinstance(item, item_type) for item in parsed):
            result[field] = parsed
    return result
