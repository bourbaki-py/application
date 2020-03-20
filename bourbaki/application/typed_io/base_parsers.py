# coding:utf-8
from typing import Collection, Union
import typing
import ast
import datetime
import enum
import operator
import re
import sys
from functools import reduce, lru_cache
from inspect import Parameter
from argparse import ZERO_OR_MORE, ONE_OR_MORE, OPTIONAL

Empty = Parameter.empty

NARGS_OPTIONS = (None, ZERO_OR_MORE, ONE_OR_MORE, OPTIONAL)

bool_constants = {"true": True, "false": False}


def parse_bool(s):
    try:
        return bool_constants[s.lower()]
    except KeyError:
        raise ValueError("Legal boolean string constants are %r; got %r" % (tuple(bool_constants), s))


def parse_bytes(s, type_=bytes):
    """Parse a bytes object from a string. This requires the explicit python literal "b''" format to avoid ambiguities
    with escape sequences in case a user specified a string e.g. in a config file without knowing it would be
    parsed to bytes"""
    raise_ = False
    try:
        b = ast.literal_eval(s)
    except SyntaxError:
        raise_ = True
        b = None
    else:
        if not isinstance(b, bytes):
            raise_ = True

        if type_ is not bytes:
            b = type_(b)

    if raise_:
        ValueError(
            "{} is not a legal bytes string expression; use format \"b'ascii-string'\" "
            "with '\\x<hex-code>' escapes for non-ascii chars".format(repr(s))
        )

    return b


def parse_regex(s: str):
    return re.compile(s)


def parse_regex_bytes(s: str):
    return re.compile(s.encode())


if sys.version_info >= (3, 7):
    def parse_iso_date(s, type_=datetime.date):
        return type_.fromisoformat(s)

    def parse_iso_datetime(s, type_=datetime.datetime):
        return type_.fromisoformat(s)
else:
    def parse_iso_date(s, type_=datetime.date):
        dt = datetime.datetime.strptime(s, "%Y-%m-%d")
        return type_(dt.year, dt.month, dt.day)

    def parse_iso_datetime(s, type_=datetime.datetime):
        dt = None
        strptime = type_.strptime
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%f+%z",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%dT%H",
            "%Y-%m-%d",
        ):
            try:
                dt = strptime(s, fmt)
            except ValueError:
                continue
            else:
                break
        if dt is None:
            raise ValueError("could not parse datetime from {}".format(s))
        return dt


range_pat = re.compile(r"(-?[0-9]+)([-:,])(-?[0-9]+)(?:\2(-?[0-9]+))?")


def parse_range(s):
    match = range_pat.fullmatch(s)
    if not match:
        raise ValueError("could not parse range from {}".format(s))
    args = match.groups()
    if args[-1] is None:
        args = args[:-1]
    args = (int(args[0]), *map(int, args[2:]))
    return range(*args)


E = typing.TypeVar("E", bound=enum.Enum)


class EnumParser:
    def __init__(self, enum_: typing.Type[E]):
        self.enum = enum_

    def cli_repr(self) -> str:
        return "{{{}}}".format("|".join(e.name for e in self.enum))

    def config_repr(self) -> str:
        return "|".join(e.name for e in self.enum)

    def _parse(self, arg):
        try:
            e = getattr(self.enum, arg)
        except AttributeError:
            raise ValueError(
                "couldn't convert {!r} to type {!s}; valid choices are {!r}".format(
                    arg, self.enum, [en.name for en in self.enum]
                )
            )
        else:
            return e

    def cli_parse(self, args: str) -> E:
        return self._parse(args)

    def config_decode(self, value: str) -> E:
        return self._parse(value)

    def config_encode(self, value: enum.Enum) -> str:
        if not isinstance(value, self.enum):
            raise TypeError("Expected {}; got {}".format(self.enum, type(value)))
        return value.name


class FlagParser(EnumParser):
    def __init__(self, enum_):
        super().__init__(enum_)

    def _parse(self, arg):
        parts = arg.split("|")
        parse = super(type(self), self)._parse
        es = (parse(e) for e in parts)
        return reduce(operator.or_, es)

    def config_decode(
        self, value: Union[str, Collection[str]]
    ) -> E:
        if isinstance(value, str):
            return super().config_decode(value)
        elif not isinstance(value, typing.Collection):
            raise TypeError("Expected str or collection of str; got {}".format(type(value)))
        else:
            config_decode = super(type(self), self).config_decode
            return reduce(operator.or_, (config_decode(e) for e in value))

    def config_encode(self, value: enum.Flag) -> str:
        if not isinstance(value, self.enum):
            TypeError("Expected {}; got {}".format(self.enum, type(value)))

        a = value.value
        e = 1
        vals = []
        while a > 0:
            a, b = divmod(a, 2)
            if b:
                vals.append(e)
            e *= 2
        return "|".join(self.enum(i).name for i in vals)


EnumParser = lru_cache(None)(EnumParser)
FlagParser = lru_cache(None)(FlagParser)
