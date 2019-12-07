# coding:utf-8
from typing import IO, TextIO, BinaryIO, Sequence, AbstractSet, Union
import typing
import datetime
import enum
import operator
import pathlib
import re
from functools import reduce, lru_cache
from inspect import Parameter
from argparse import ZERO_OR_MORE, ONE_OR_MORE, OPTIONAL
from bourbaki.introspection.types import get_generic_args, concretize_typevars
from bourbaki.introspection.typechecking import isinstance_generic
from bourbaki.introspection.imports import import_type
from .utils import TypeCheckImport

Empty = Parameter.empty

NARGS_OPTIONS = (None, ZERO_OR_MORE, ONE_OR_MORE, OPTIONAL)


class TypedIOException(ValueError):
    def __init__(self, type_, value):
        self.type_ = type_
        self.value = value


class TypedIOParseError(TypedIOException):
    def __str__(self):
        return "Could not parse value of type {} from {}".format(
            self.type_, repr(self.value)
        )


class TypedIOConfigReprError(TypedIOException):
    def __str__(self):
        return "Could not represent value {} for type {} in config-safe way".format(
            repr(self.value), self.type_
        )


bool_constants = {"true": True, "false": False}


def parse_bool(s, exc_type):
    try:
        return bool_constants[s.lower()]
    except KeyError as e:
        raise exc_type(
            bool,
            s,
            ValueError("Legal boolean constants are {}".format(tuple(bool_constants))),
        )


def parse_regex(s: str):
    return re.compile(s)


def parse_regex_bytes(s: str):
    return re.compile(s.encode())


def parse_path(s: str):
    return pathlib.Path(s)


def parse_iso_date(s):
    return datetime.datetime.strptime(s, "%Y-%m-%d").date()


def parse_iso_datetime(s):
    dt = None
    strptime = datetime.datetime.strptime
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


class EnumParser:
    def __init__(self, enum_: enum.EnumMeta):
        self.enum = enum_

    def cli_repr(self) -> str:
        return "{{{}}}".format("|".join(e.name for e in self.enum))

    def config_repr(self) -> str:
        return "|".join(e.name for e in self.enum)

    def _parse(self, arg, exc_type=TypedIOParseError):
        try:
            e = getattr(self.enum, arg)
        except AttributeError:
            raise exc_type(self.enum, arg)
        return e

    def cli_parse(self, args: str) -> enum.Enum:
        return self._parse(args)

    def config_decode(self, value: str) -> enum.Enum:
        return self._parse(value)

    def config_encode(self, value: enum.Enum) -> str:
        if not isinstance(value, self.enum):
            raise TypedIOConfigReprError(self.enum, value)
        return value.name


class FlagParser(EnumParser):
    def __init__(self, enum_: enum.EnumMeta):
        super().__init__(enum_)

    def _parse(self, arg, exc_type=TypedIOParseError):
        parts = arg.split("|")
        parse = super(type(self), self)._parse
        es = (parse(e, exc_type) for e in parts)
        return reduce(operator.or_, es)

    def config_decode(
        self, value: Union[str, Sequence[str], AbstractSet[str]]
    ) -> enum.Flag:
        if isinstance(value, str):
            return self._parse(value)
        elif not isinstance(value, typing.Collection):
            raise TypedIOParseError(self.enum, value)
        else:
            config_decode = super(type(self), self).config_decode
            return reduce(operator.or_, (config_decode(e) for e in value))

    def config_encode(self, value: enum.Flag) -> str:
        if not isinstance(value, self.enum):
            raise TypedIOConfigReprError(self.enum, value)
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


class TypeCheckImportFunc(TypeCheckImport):
    # only check that the imported object is callable; don't demand that it be a specific function type
    def type_check(self, value):
        if not callable(value):
            raise self.exc_cls(self.type_, value)
        return value


class TypeCheckImportType(TypeCheckImport):
    decode = staticmethod(import_type)

    def type_check(self, type_):
        if not isinstance_generic(type_, self.type_):
            bound = concretize_typevars(get_generic_args(self.type_)[0])
            raise self.exc_cls(
                self.type_,
                type_,
                TypeError("{} is not a subclass of {}".format(type_, bound)),
            )
        return type_
