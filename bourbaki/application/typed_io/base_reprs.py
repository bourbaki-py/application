# coding:utf-8
from typing import Collection
import typing
import types
import datetime
import decimal
import fractions
import ipaddress
import numbers
import pathlib
import sys
import uuid
from urllib.parse import ParseResult as URL
from functools import singledispatch
from inspect import Parameter
from bourbaki.introspection.types import (
    is_named_tuple_class,
    get_constructor_for,
    issubclass_generic,
)
from bourbaki.introspection.types.abcs import NonStrCollection
from bourbaki.introspection.callables import UnStarred
from bourbaki.introspection.classes import classpath, parameterized_classpath
from .file_types import File, BinaryFile, TextFile

######################################################
# Base type repr values/functions for CLI and config #
######################################################

Empty = Parameter.empty

KEY_VAL_JOIN_CHAR = "="


@singledispatch
def type_spec(type_):
    if type_.__module__ == "builtins":
        path = type_.__name__
    else:
        path = classpath(type_)
    return "<{}>".format(path)


@type_spec.register(str)
def type_spec_str(s):
    return "<{}>".format(s)


def parser_constructor_for_collection(cls):
    if is_named_tuple_class(cls):
        return UnStarred(cls)
    return get_constructor_for(cls)


byte_repr = "<0-255>"
regex_repr = "<regex>"
regex_bytes_repr = "<byte-regex>"
date_repr = "YYYY-MM-DD"
path_repr = "<path>"
binary_path_repr = "<binary-file>"
text_path_repr = "<text-file>"
classpath_type_repr = "path.to.type[params]"
classpath_function_repr = "path.to.function"
int_repr = type_spec(int)
float_repr = type_spec(float)
decimal_repr = "<decimal-str>"
fraction_repr = "{i}[/{i}]".format(i=int_repr)
complex_repr = "{f}[+{f}j]".format(f=float_repr)
range_repr = "{i}:{i}[:{i}]".format(i=int_repr)
datetime_repr = "YYYY-MM-DD[THH:MM:SS[.ms]]"
ipv4_repr = "<ipaddr>"
ipv6_repr = "<ipv6addr>"
url_repr = "scheme://netloc[/path][;params][?query][#fragment]"
uuid_repr = "[0-f]{32}"
ellipsis_ = "..."
any_repr = "____"


default_repr_values = {
    str: type_spec(str),
    int: int_repr,
    float: float_repr,
    complex: complex_repr,
    fractions.Fraction: fraction_repr,
    decimal.Decimal: decimal_repr,
    range: range_repr,
    datetime.date: date_repr,
    datetime.datetime: datetime_repr,
    pathlib.Path: path_repr,
    File: path_repr,
    BinaryFile: binary_path_repr,
    TextFile: text_path_repr,
    typing.Pattern: regex_repr,
    typing.Pattern[bytes]: regex_bytes_repr,
    ipaddress.IPv4Address: ipv4_repr,
    ipaddress.IPv6Address: ipv6_repr,
    URL: url_repr,
    uuid.UUID: uuid_repr,
    Empty: any_repr,
    typing.Callable: classpath_function_repr,
    types.FunctionType: classpath_function_repr,
    types.BuiltinFunctionType: classpath_function_repr,
    numbers.Number: "|".join(
        (int_repr, float_repr, complex_repr.replace("[", "").replace("]", ""))
    ),
    numbers.Real: "|".join((int_repr, float_repr)),
    numbers.Integral: int_repr,
}

default_value_repr_values = {
    sys.stdout: "stdout",
    sys.stderr: "stderr",
    sys.stdin: "stdin",
}


def is_nested_collection(type_):
    return issubclass_generic(type_, Collection[NonStrCollection])


def repr_type(type_, supertype=None):
    # type_ is always typing.Type; we keep the same signature as registerable functions
    if supertype is None:
        return classpath_type_repr
    return "{}<:{}".format(classpath_type_repr, parameterized_classpath(supertype))


def repr_value(value: object) -> str:
    """Represent a default value on the command line"""
    r = default_value_repr_values.get(value)
    if r is None:
        return str(value)
    return r
