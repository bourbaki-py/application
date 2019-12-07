# coding:utf-8
import json
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
from .defaults import DEFAULT_LOG_MSG_FMT, DEFAULT_LOG_DATE_FMT, METALOG, METALOG_LEVEL
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
    validate=False,
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

    if validate:
        _validate_dataframe_parse(df, raise_)

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


def _validate_dataframe_parse(df, raise_):
    import pandas

    levelfield = None
    metalevel = None
    if "levelname" in df.columns:
        levelfield = "levelname"
        metalevel = METALOG_LEVEL
    elif "levelno" in df.columns:
        levelfield = "levelno"
        metalevel = METALOG

    def _tryparse(msg):
        try:
            return json.loads(msg)
        except Exception:
            return None

    stats = None
    if levelfield and metalevel:
        stats = df.loc[df[levelfield] == metalevel, ["name", "message"]]
        stats["stats"] = stats["message"].map(_tryparse)

        nonnull_stats_ix = stats["stats"].notnull()
        if len(stats.index.unique()) > nonnull_stats_ix.sum():
            _warn_or_raise(
                "Not all loggers that issued {}/{}-level messages "
                "had parseable statistics reports".format(METALOG_LEVEL, METALOG),
                IOError,
                raise_,
            )
        if len(stats) == 0:
            errmsg = (
                "validation is requested but this is only possible if "
                "messages are logged at the {}/{} level".format(METALOG_LEVEL, METALOG)
            )
            _warn_or_raise(errmsg, ValueError, raise_)
        stats = (
            stats[nonnull_stats_ix]
            .drop_duplicates(subset="name", keep="last")
            .set_index("name")
        )
        stats = pandas.DataFrame.from_records(stats["stats"], index=stats.index)
    else:
        errmsg = (
            "validation is requested but this is only possible if "
            "'levelname' or 'levelno' are fields in the log message format"
        )
        _warn_or_raise(errmsg, ValueError, raise_)

    levelcounts = pandas.DataFrame.from_records(stats["levelcounts"], index=stats.index)

    msg_template = (
        "logger '{name}' reports differing %s from what was parsed;\nreported in log:\n"
        "{reported}\nparsed:\n{parsed}"
    )
    levelcount_msg = msg_template % "level counts"
    multiline_msg = msg_template % "multiline message count"
    stacktrace_msg = msg_template % "stacktrace count"

    for name in stats.index:
        subset = df.loc[df["name"] == name, ["levelname", "message", "stackTrace"]]

        parsed = subset["levelname"].value_counts(dropna=True).sort_index()
        reported = levelcounts.loc[name].dropna().sort_index().astype(int)

        if not (parsed == reported).all():
            _warn_or_raise(
                levelcount_msg.format(name=name, reported=reported, parsed=parsed),
                IOError,
                raise_,
            )

        parsed = subset["message"].str.contains("\n").sum()
        reported = stats.loc[name, "multiline"]

        if parsed != reported:
            _warn_or_raise(
                multiline_msg.format(name=name, reported=reported, parsed=parsed),
                IOError,
                raise_,
            )

        parsed = subset["stackTrace"].notnull().sum()
        reported = stats.loc[name, "stacktraces"]

        if parsed != reported:
            _warn_or_raise(
                multiline_msg.format(name=name, reported=reported, parsed=parsed),
                IOError,
                raise_,
            )
