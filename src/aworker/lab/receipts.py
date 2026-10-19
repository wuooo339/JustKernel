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
