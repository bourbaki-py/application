# coding:utf-8
from typing import Callable, Union, Optional as Opt
from time import time
from datetime import datetime, timedelta
from functools import partial
from logging import Logger, getLogger
from .defaults import PROGRESS, ERROR, DEFAULT_LOG_DATE_FMT
from .helpers import validate_log_level_int

unit_names = dict(
    s="s",
    seconds="s",
    ms="ms",
    milliseconds="ms",
    mus="μs",
    us="μs",
    μs="μs",
    microseconds="μs",
    ns="ns",
    nanoseconds="ns",
    m="m",
    mins="m",
    minutes="m",
    h="h",
    hrs="h",
    hours="h",
    days="d",
    d="d",
)

timedelta_units_kw = dict(
    s="seconds", ms="milliseconds", μs="microseconds", m="minutes", h="hours", d="days"
)

from_seconds_multipliers = dict(
    s=1.0, ms=1e3, μs=1e6, ns=1e9, m=1.0 / 6e1, h=1.0 / 36e2, d=1.0 / 864e2
)


class TimedTaskContext:
    def __init__(
        self,
        job_name: str,
        total_tasks: Opt[int] = None,
        task_units: Opt[str] = None,
        logger_or_print_func: Opt[Union[Logger, Callable[[str], type(None)]]] = print,
        level=PROGRESS,
        error_level=ERROR,
        time_units: str = "s",
        date_fmt=DEFAULT_LOG_DATE_FMT,
    ):
        try:
            self.time_units = unit_names[time_units]
            # timedelta won't take nanoseconds on some systems; we multiply microseconds by 1000
            if time_units == "ns":
                self.timedelta_kw = "microseconds"
                self.timedelta_multiplier = 1000.0
            else:
                self.timedelta_kw = timedelta_units_kw[time_units]
                self.timedelta_multiplier = 1.0
            self.multiplier = from_seconds_multipliers[self.time_units]
        except KeyError:
            raise ValueError(
                "{} is not a valid time units identifer; choose one of {}".format(
                    time_units, set(unit_names)
                )
            )

        if isinstance(logger_or_print_func, Logger) or logger_or_print_func is None:
            level = validate_log_level_int(level)
            error_level = validate_log_level_int(error_level)
            if logger_or_print_func is None:
                logger = getLogger(job_name)
            else:
                logger = logger_or_print_func
            self.logger = logger
            self.print = partial(logger.log, level)
            self.error = partial(logger.log, error_level)
        else:
            assert callable(
                logger_or_print_func
            ), "print_func must be callable or a name for a logger"
            self.logger = None
            self.print = logger_or_print_func
            self.error = self.print

        self.total = int(total_tasks) if total_tasks is not None else None
        self.completed = 0
        self.task_units = str(task_units) if task_units is not None else ""

        self.date_fmt = date_fmt

        self.job_name = str(job_name)
        self.start = None

        self.n_digits = 4

    def elapsed_since(self, start):
        end = time()
        elapsed = self.multiplier * (end - start)
        return elapsed

    def total_elapsed(self):
        return self.elapsed_since(self.start)

    def report_elapsed(self):
        self.print(self._elapsed_time_message())

    def report_progress(self, n_tasks: int, timing_info=True):
        self.completed += n_tasks
        msg = self._progress_message()
        if timing_info:
            msg = "{}; {}".format(msg, self._timing_info_message(prefix=False))

        self.print(msg)

    @property
    def is_finished(self):
        if self.total is None:
            return False
        return self.completed >= self.total

    def _elapsed_time_message(self, start=None, prefix=True):
        if start is None:
            start = self.start
        elapsed = self.elapsed_since(start)
        return "{}elapsed time {}{}".format(
            "{}{}: ".format(
                self.job_name, " " + self.task_units if self.task_units else ""
            )
            if prefix
            else "",
            round(elapsed, self.n_digits),
            self.time_units,
        )

    def _progress_message(self):
        if self.total:
            return "{}: completed {} of {}".format(
                self.job_name, self.completed, self.total
            )
        else:
            return "{}: completed {}".format(self.job_name, self.completed)

    def _timing_info_message(self, prefix=True, estimate=True, completed=None):
        if completed is None:
            completed = self.completed
        rate = completed / self.total_elapsed()
        if estimate and self.total:
            remaining = self.total - self.completed
            expected_end = datetime.now() + timedelta(
                **{self.timedelta_kw: remaining * rate / self.timedelta_multiplier}
            )

            msg = "average rate {} {}/{}; expected completion {}".format(
                round(rate, self.n_digits),
                self.task_units or "tasks",
                self.time_units,
                expected_end.strftime(self.date_fmt),
            )
        else:
            msg = "average rate {} {}/{}".format(
                round(rate, self.n_digits), self.task_units or "tasks", self.time_units
            )

        if prefix:
            msg = "{}: {}".format(self.job_name, msg)

        return msg

    def _error_message(self):
        if self.total is not None:
            return "FAILED {}; completed {} {}of {}".format(
                self.job_name,
                self.completed,
                self.task_units + " " if self.task_units else "",
                self.total,
            )
        return "FAILED {}".format(self.job_name)

    def _reset_time(self):
        self.start = time()

    def __enter__(self):
        if self.total is None:
            self.print(
                "STARTED {} at {}".format(
                    self.job_name, datetime.now().strftime(self.date_fmt)
                )
            )
        else:
            self.print(
                "STARTED {} {} {}at {}".format(
                    self.job_name,
                    self.total,
                    self.task_units + " " if self.task_units else "",
                    datetime.now().strftime(self.date_fmt),
                )
            )
        self._reset_time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is SystemExit and exc_val.args[0] == 0:
            if not self.is_finished:
                exc_val = SystemExit(1)

        if exc_type is not None or exc_val is not None:
            msg = self._error_message()
            self.error(msg + " Exception is {}".format(exc_val or exc_type))
            raise (exc_val or exc_type)
        else:
            if self.total is not None:
                self.print(
                    "FINISHED {}; {}".format(
                        self._elapsed_time_message(),
                        self._timing_info_message(
                            prefix=False,
                            estimate=False,
                            completed=self.total or self.completed,
                        ),
                    )
                )
            else:
                self.print("FINISHED {}".format(self._elapsed_time_message()))


timed_context = TimedTaskContext
