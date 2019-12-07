# coding:utf-8
import re
from itertools import cycle

datetime_fields = dict(
    Y=r"[0-9]{4}",
    y=r"[0-9]{2}",
    m=r"(?:0[0-9]|1[0-2])",
    b=r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)",
    B=r"(?:January|February|March|April|May|June|July|August|September|October|November|December)",
    d=r"(?:[0-2][0-9]|3[01])",
    w=r"[0-6]",
    a=r"(?:Sun?|Mon?|Tue?|Wed?|Thu?|Fri?|Sat?)",
    A=r"(?:Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday)",
    H=r"(?:[01][0-9]|2[0-4])",
    I=r"(?:0[0-9]|1[0-2])",
    p=r"(?:AM|PM|am|pm)",
    M=r"[0-5][0-9]",
    S=r"[0-5][0-9]",
    f=r"[0-9]{6}",
    z=r"(?:|[-+](?:0[0-9]|1[0-2])(?:[0-5][0-9]))",
    Z=r"(?:|[A-Z]{3})",
    j=r"(?:[0-2][0-9]{2}|3[0-5][0-9]|36[0-6])",
    U=r"(?:[0-4][0-9]|5[0-3])",
    W=r"(?:[0-4][0-9]|5[0-3])",
    X=r"(?:(?:[01][0-9]|2[0-4]):[0-5][0-9]:[0-5][0-9])",
)

date_fmt_field_pat = r"(?!<\\)%({})".format("|".join(datetime_fields))

int_re = r"[0-9]+"
float_re = r"-?[0-9]+\.[0-9]+([eE][+-]?[0-9]+)?"
py_name_re = r"[_a-zA-Z][_a-zA-Z0-9]*"
py_name_dynamic_re = (
    r"<?[_a-zA-Z][_a-zA-Z0-9]*>?"
)  # for objects generated dynamically with no name attribute
py_dot_name_re = r"{name}(?:\.{name})*".format(name=py_name_re)

# note: These are only 'reasonable' patterns for file/path and logger/process names;
# POSIX-compliant names can be much wilder. I keep them simple to allow for a loaders
# parse with little backtracking (as you would get with a lot of '[<big char set>]*'
# subpatterns in your regexes).
# Just be aware that these will break if you give your source files, loggers, and
# processes crazy names or names with whitespace
filename_re = r"[-_.~<>a-zA-Z0-9]+"
pathname_re = r"\/?(?:{name})(?:\/{name})*\/?".format(name=filename_re)
any_name_re = r"[-_.a-zA-Z0-9]*"
upper_name_re = r"[A-Z]+"


def alternating(patterns):
    return "|".join(patterns)


def re_escaped(raw_str):
    return re.sub(r"([(){}\[\].\\?+*])", r"\\\1", raw_str)


def named_group(pattern: str, name: str):
    return r"(?P<{}>{})".format(name, pattern)


def optional(pattern: str):
    return noncapturing_group(pattern) + "?"


def noncapturing_group(pattern: str):
    return r"(?:{})".format(pattern)


def extract_group(match):
    return match.group()


def extract_groups(match: re.match):
    return match.groups()


def with_any_whitespace(pattern, escape=True):
    pattern_ = re_escaped(pattern) if escape else pattern
    return re.sub(r"\s+", r"\s+", pattern_)


def as_word(pattern):
    return "\\b{}\\b".format(noncapturing_group(pattern))


def find_lambda(pattern, s, match_lambda):
    pattern = re.compile(pattern)
    for match in pattern.finditer(s):
        yield match_lambda(match)


def sub_lambda(pattern, s, match_lambda=None, hole_lambda=None):
    pattern = re.compile(pattern)

    def sub_lambda_iter(pattern, s):
        lo, hi = 0, 0
        for match in re.finditer(pattern, s):
            hi, _ = match.span()
            yield s[lo:hi]
            yield match
            lo = _
        yield s[lo:]

    if hole_lambda is None:
        hole_lambda = lambda x: x
    if match_lambda is None:
        match_lambda = extract_group

    holematches = sub_lambda_iter(pattern, s)
    holematches = list(holematches)
    funcs = cycle((hole_lambda, match_lambda))

    return "".join(f(x) for f, x in zip(funcs, holematches))


def datetime_regex(date_fmt: str):
    def get_field_re(match):
        char = match.group(1)
        pat = datetime_fields.get(char)
        if not pat:
            raise ValueError("Unrecognized datetime format char: '%s'" % char)
        return noncapturing_group(pat)

    return sub_lambda(date_fmt_field_pat, date_fmt, get_field_re, re_escaped)
