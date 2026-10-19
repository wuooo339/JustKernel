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
        grace_calls: int = 0,
        grace_seconds: float = 0,
    ):
        self.source = source
        self.jobs = set(jobs)
        self.seconds, self.calls, self.clock = seconds, calls, clock
        self.last_progress = clock()
        self.completed_calls: set[str] = set()
        self.grace_calls = grace_calls
        self.grace_seconds = grace_seconds
        self.warned = False

    # ---- reading, analysis-file writes and repeated polling are not progress --
    def observe(
        self,
        source: str | None = None,
        jobs: Iterable[str] = (),
        call: str | None = None,
        check_calls: bool = True,
        check_time: bool = True,
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
            self.warned = False
        if call:
            self.completed_calls.add(call)
        elapsed = self.clock() - self.last_progress
        if (check_time and elapsed >= self.seconds + self.grace_seconds) or (
            check_calls and len(self.completed_calls) >= self.calls + self.grace_calls
        ):
            raise RuntimeError(
                "BASELINE_NO_PROGRESS: 主队连续分析未产生算子源码变化或新仿真实验，"
                "已停止本轮模型调用。保留工作区，检查工具错误并缩小任务后再恢复。"
            )
        if not self.warned and (
            check_calls
            and len(self.completed_calls) >= self.calls
            or check_time
            and elapsed >= self.seconds
        ):
            self.warned = True
            return (
                "BASELINE_PROGRESS_CHECK: 已完成首轮阅读，尚无源码变化或新实验。"
                "这是纠偏提醒，尚未暂停。read_simulation_results(job_id) 默认返回结构化结果，"
                "无需编写日志解析脚本；详细诊断用 section=log/profile 分段读取。"
                "run_python 使用团队目录下的相对路径。接下来聚焦一个具体假设、读取必要实现，"
                "修改算子并做针对性实验。不要重复整理日志或分析文件。"
                "若没有可实施的修正，应如实结束本轮说明未知项。"
            )
