"""Stop an unproductive baseline turn using code/experiment evidence, not chat activity."""

import time
from collections.abc import Callable, Iterable


# ---- BaselineProgressGuard --------------------------------------------------
class BaselineProgressGuard:
    def __init__(
        self,
        source: str,
        jobs: Iterable[str] = (),
        seconds: float = 300,
        calls: int = 12,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.source = source
        self.jobs = set(jobs)
        self.seconds, self.calls, self.clock = seconds, calls, clock
        self.last_progress = clock()
        self.completed_calls: set[str] = set()

    # ---- reading, analysis-file writes and repeated polling are not progress --
    def observe(
        self,
        source: str | None = None,
        jobs: Iterable[str] = (),
        call: str | None = None,
        check_calls: bool = True,
    ):
        incoming = set(jobs)
        progressed = bool(source is not None and source != self.source) or bool(
            incoming - self.jobs
        )
        self.jobs.update(incoming)
        if source is not None:
            self.source = source
        if progressed:
            self.last_progress = self.clock()
            self.completed_calls.clear()
        if call:
            self.completed_calls.add(call)
        if self.clock() - self.last_progress >= self.seconds or (
            check_calls and len(self.completed_calls) >= self.calls
        ):
            raise RuntimeError(
                "BASELINE_NO_PROGRESS: 主队连续分析未产生算子源码变化或新仿真实验，"
                "已停止本轮模型调用。保留工作区，检查工具错误并缩小任务后再恢复。"
            )
