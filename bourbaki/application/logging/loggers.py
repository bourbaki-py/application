# coding:utf-8
from typing import Optional as Opt
import json
from logging import Logger, Manager, addLevelName, getLevelName, root
from collections import Counter
from .defaults import PROGRESS, ERROR, PROGRESS_LEVEL, METALOG, METALOG_LEVEL
from .timing import TimedTaskContext
from .helpers import *

logger_method_names = ("debug", "info", "warning", "error", "critical")


class CountingLogger(Logger):
    """
    This logger subclass allows validation of log file parses by counting the number of
    times that it has logged at each level, how many stack traces it has logged, and how
    many multiline messages it has logged (which are potentially ambiguous to parse)
    """

    addLevelName(METALOG, METALOG_LEVEL)
    manager = Manager(root)

    def __init__(self, *args, **kwargs):
        self.multiline = 0
        self.stacktraces = 0
        self.total = 0
        self.levelcounts = Counter()
        super().__init__(*args, **kwargs)

    def _log(
        self, level, msg, args, exc_info=None, extra=None, stack_info=False, stats=False
    ):
        levelname = getLevelName(level)

        if not stats:
            super()._log(
                level, msg, args, exc_info=exc_info, extra=extra, stack_info=stack_info
            )
            if exc_info:
                self.stacktraces += 1
            if "\n" in msg:
                self.multiline += 1

        if level >= self.level:
            self.levelcounts.update([levelname])

        if stats:
            msg = json.dumps(self.stats, indent=None)
            if "\n" in msg:
                self.multiline += 1
                stats_ = json.loads(msg)
                stats_["multiline"] += 1
                msg = json.dumps(self.stats, indent=None)
            super()._log(
                level, msg, args, exc_info=exc_info, extra=extra, stack_info=stack_info
            )

        self.total += 1

    @property
    def stats(self):
        return dict(
            stacktraces=self.stacktraces,
            multiline=self.multiline,
            levelcounts=self.levelcounts,
        )

    def _report_stats(self):
        self._log(METALOG, None, None, stats=True)

    def __del__(self):
        # log the final message count stats on program exit
        self._report_stats()


class ProgressLogger(CountingLogger):
    """
    This logger subclass allows for simple and consistent logging of progress on user-defined
    jobs:
    >>> logger = ProgressLogger("fooLog", job_level="INFO")
    >>> with logger.task("count_to_10", time_units='s') as task:
    >>>     for i in range(10):
    >>>         task.report_progress(1)
    >>>         # verbose output happens here
    """

    addLevelName(PROGRESS, PROGRESS_LEVEL)
    manager = Manager(root)

    def __init__(self, *args, job_level=PROGRESS_LEVEL, **kwargs):
        self.job_level = validate_log_level(job_level)
        super().__init__(*args, **kwargs)

    def task(
        self,
        job_name: str,
        total_tasks: Opt[int] = None,
        task_units: Opt[str] = None,
        level=PROGRESS,
        error_level=ERROR,
        time_units: str = "s",
    ):
        level = level or self.job_level
        return TimedTaskContext(
            job_name,
            total_tasks=total_tasks,
            task_units=task_units,
            time_units=time_units,
            logger_or_print_func=self,
            level=level,
            error_level=error_level,
        )


for cls in (CountingLogger, ProgressLogger):
    cls.manager.loggerClass = cls
