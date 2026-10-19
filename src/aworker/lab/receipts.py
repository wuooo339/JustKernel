"""Lossless case-level performance/accuracy fields from CANN Judge's microsecond API."""

import math


# ---- official_case_results --------------------------------------------------
def official_case_results(official: dict, case_ids: list[str] | None = None) -> list[dict]:
    order = {key: i + 1 for i, key in enumerate(case_ids or [])}

    def numeric(value):
        return (
            value
            if isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            else None
        )

    rows = []
    for i, case in enumerate(official.get("result") or []):
        ratio = numeric(case.get("precision_ratio"))
        rows.append(
            {
                "number": order.get(case.get("testcase_id"), i + 1),
                "testcase_id": case.get("testcase_id"),
                "status": case.get("testcase_status"),
                "precision_ratio": ratio,
                "error_percent": (1 - ratio) * 100
                if ratio is not None and 0 <= ratio <= 1
                else None,
                "time_us": numeric(case.get("time")),
                "best_time_us": numeric(case.get("best_time")),
            }
        )
    return sorted(rows, key=lambda r: r["number"])


# ---- compare evidence, never infer an input shape or a hidden branch ---------
def official_comparison(current: dict, previous: dict | None) -> dict | None:
    if previous is None:
        return None
    before = {r["testcase_id"]: r for r in official_case_results(previous["official"])}
    changes = []
    for row in official_case_results(current["official"]):
        prior = before.get(row["testcase_id"]) if row["testcase_id"] else None
        if prior and (row["status"] != "Pass" or prior["status"] != "Pass"):
            changes.append(
                {
                    "testcase_id": row["testcase_id"],
                    "previous_status": prior["status"],
                    "current_status": row["status"],
                    "previous_error_percent": prior["error_percent"],
                    "current_error_percent": row["error_percent"],
                    "same_accuracy_feedback": (prior["status"], prior["precision_ratio"])
                    == (row["status"], row["precision_ratio"])
                    if prior["precision_ratio"] is not None and row["precision_ratio"] is not None
                    else None,
                }
            )
    return {
        "previous_submission_id": previous["official_submission_id"],
        "previous_source_sha256": previous["source_sha256"],
        "accuracy_changes": changes,
        "note": "Unchanged official error ratios are not evidence of improvement. "
        "They do not identify hidden shapes, dtypes, axes or which implementation branch ran.",
    }
