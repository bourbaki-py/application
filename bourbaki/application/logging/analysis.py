# coding:utf-8
from warnings import warn
from datetime import datetime
from ..reutils import (
    find_lambda,
    sub_lambda,
    extract_groups,
    datetime_regex,
    named_group,
    re_escaped,
)
from .defaults import DEFAULT_LOG_MSG_FMT, DEFAULT_LOG_DATE_FMT
from .regexes import *


def log_fmt_fields(log_fmt: str):
    fields = list(find_lambda(log_fmt_field_pat, log_fmt, extract_groups))
    return fields


def log_line_regex(log_fmt: str, date_fmt: str = None):
    def get_field_re(match):
        name, typ = match.groups()
        if typ != log_fields[name]:
            warn(
                "default printf formatting style for '%s' is '%s' but '%s' is "
                "specified instead" % (name, log_fields[name], typ)
            )
        pat = field_regexes.get(typ, string_field_regexes.get(name))
        if pat is None:
            if name == "asctime":
                pat = datetime_regex(date_fmt)
            else:
                raise ValueError("No pattern available for field name '%s'" % name)

        return named_group(pat, name)

    pat = sub_lambda(log_fmt_field_pat, log_fmt, get_field_re, re_escaped)
    return pat


def lambda_mutate(d, converters):
    for k, f in converters.items():
        if k in d:
            d[k] = f(d[k])
    return d


def join_stacktrace(trace):
    if len(trace) > 0:
        return "".join(trace)
    else:
        return None


def begins_stacktrace(line):
    return stacktrace_start_re.match(line)


def check_message_last(fields):
    not_last = any(t[0] == "message" for t in fields) and fields[-1][0] != "message"
    if not_last:
        warn(
            "The 'message' field of the log format is not placed last; regex parsing "
            "of log files may be slow or impossible"
        )
    return not not_last


def log_file_record_iter(filepath, log_fmt, date_fmt, raise_=False):
    if isinstance(filepath, str):
        file = open(filepath, "r")
        close = True
    else:
        file = filepath
        close = False

    def strptime(s):
        return datetime.strptime(s, date_fmt)

    line_re = re.compile(log_line_regex(log_fmt, date_fmt))

    fields = log_fmt_fields(log_fmt)
    message_last = check_message_last(fields)

    converters = {name: field_converters[typ] for name, typ in fields}
    if "asctime" in converters:
        converters["asctime"] = strptime
    if "message" in converters:
        converters["message"] = join_stacktrace
    converters["stackTrace"] = join_stacktrace

    lines = iter(file)
    last_record = dict(stackTrace=[], message="")
    append_trace = False
    counter = 0

    for line in lines:
        record = line_re.match(line)
        if not record:
            append_trace = append_trace or begins_stacktrace(line)
            if append_trace:
                last_record["stackTrace"].append(line)
            elif message_last:
                last_record["message"] += "\n%s" % line.rstrip("\n")
            else:
                _warn_or_raise(
                    "could not parse line: '{}'".format(line.rstrip("\n")),
                    IOError,
                    raise_,
                )
        else:
            # we have a new record; yield the last one
            if counter > 0:
                yield lambda_mutate(last_record, converters)

            last_record = record.groupdict()
            last_record["stackTrace"] = []
            append_trace = False
        counter += 1

    if counter > 0:
        # there were at least some lines in the file; yield the last parsed
        yield lambda_mutate(last_record, converters)

    if close:
        file.close()


def log_file_to_df(
    filepath,
    log_fmt=DEFAULT_LOG_MSG_FMT,
    date_fmt=DEFAULT_LOG_DATE_FMT,
    datetime_index=False,
    raise_=False,
):
    import pandas

    fields = [t[0] for t in log_fmt_fields(log_fmt)]

    fields.append("stackTrace")

    if datetime_index:
        if "asctime" not in fields:
            raise ValueError(
                "datetime_index is specified but 'asctime' is not one of "
                "the log format fields"
            )

    df = pandas.DataFrame.from_records(
        log_file_record_iter(filepath, log_fmt, date_fmt, raise_), columns=fields
    )

    if datetime_index:
        df.set_index("asctime", inplace=True)
    if not df.index.is_monotonic:
        df.sort_index(inplace=True)

    return df


def _warn_or_raise(errmsg, exception, raise_):
    if raise_:
        raise exception(errmsg)
    else:
        warn(errmsg)
    return
