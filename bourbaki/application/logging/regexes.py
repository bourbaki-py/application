# coding:utf-8
import re
from ..reutils import (
    pathname_re,
    filename_re,
    any_name_re,
    upper_name_re,
    py_name_dynamic_re,
    py_dot_name_re,
    int_re,
    float_re,
)


stacktrace_start_re = re.compile(r"^\s*Traceback \(most recent call last\):")

# logging module standard field name -> (printf format type, regex, postprocessor)
log_fields = dict(
    asctime="s",
    created="f",
    filename="s",
    funcName="s",
    levelname="s",
    levelno="d",
    lineno="d",
    module="s",
    msecs="d",
    message="s",
    name="s",
    pathname="s",
    process="d",
    processName="s",
    relativeCreated="d",
    thread="d",
    threadName="s",
)

log_fmt_field_pat = r"(?<!\\)%\(({})\)({})".format(
    "|".join(log_fields), "|".join(set(log_fields.values()))
)

string_field_regexes = dict(
    filename=filename_re,
    funcName=py_name_dynamic_re,
    levelname=upper_name_re,
    module=py_dot_name_re,
    message=r".*",
    name=any_name_re,
    pathname=pathname_re,
    processName=any_name_re,
    threadName=any_name_re,
)

field_regexes = dict(f=float_re, d=int_re)

field_converters = dict(s=str, d=int, f=float)
