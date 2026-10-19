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
    if name == "run_python" and isinstance(result.get("arguments"), str):
        try:
            parsed = json.loads(result["arguments"])
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
            result["arguments"] = parsed
    return result
