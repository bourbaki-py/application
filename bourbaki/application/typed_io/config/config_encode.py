# coding:utf-8
import typing
import types
import collections.abc
import decimal
import enum
import fractions
from functools import singledispatch, lru_cache
import io
import os
import pathlib
import ipaddress
import datetime
import sys
import uuid
from urllib.parse import ParseResult as URL, urlunparse
from warnings import warn
from bourbaki.introspection.callables import function_classpath
from bourbaki.introspection.classes import parameterized_classpath
from bourbaki.introspection.types import (
    NamedTupleABC,
    NonAnyStrCollection,
    LazyType,
)
from bourbaki.introspection.generic_dispatch_helpers import (
    LazyWrapper,
    CollectionWrapper,
    TupleWrapper,
    MappingWrapper,
    NamedTupleWrapper,
    UnionWrapper,
    PicklableWithType,
)
from bourbaki.introspection.generic_dispatch import UnknownSignature
from ..base_parsers import (
    EnumParser,
    FlagParser,
)
from ..utils import (
    identity,
    GenericIOTypeLevelSingleDispatch,
)
from ..file_types import File
from ..exceptions import (
    ConfigTypedOutputError, ConfigIOUndefinedForType, AllFailed, RaisedDisallowedExceptions,
)

NoneType = type(None)

T = typing.TypeVar("T")

# The main dispatcher

config_encoder = GenericIOTypeLevelSingleDispatch(
    "config_encoder",
    isolated_bases=[typing.Union, typing.Generic],
    resolve_exc_class=ConfigIOUndefinedForType,
    call_exc_class=ConfigTypedOutputError,
)


# basic encoders

@config_encoder.register(decimal.Decimal, as_const=True)
def to_config_decimal(dec: decimal.Decimal):
    return float(dec) if float(dec) == dec else str(dec)


@config_encoder.register(fractions.Fraction, as_const=True)
def to_config_fraction(frac: fractions.Fraction):
    return frac.numerator if frac.denominator == 1 else str(frac)


config_encoder.register_all(
    complex,
    fractions.Fraction,
    ipaddress.IPv4Address,
    ipaddress.IPv6Address,
    pathlib.Path,
    uuid.UUID,
    as_const=True,
)(str)


config_encoder.register(URL, as_const=True)(urlunparse)


# basic config/JSON types

for _type in [int, float, bool, str]:
    config_encoder.register(_type, as_const=True)(_type)


# encode bytes types to lists of ints by default

config_encoder.register_all(typing.ByteString, as_const=True)(list)


@config_encoder.register(File, as_const=True)
def to_config_file(f: io.IOBase):
    if f is sys.stdin or f is sys.stdout or f is sys.stderr:
        # argparse FileType parses this to on of the above handles depending on the mode
        return '-'
    name = getattr(f, name, None)
    if name is None:
        warn("Can't determine path/name for file object {}".format(f))
        return None
    return os.path.abspath(name)


@config_encoder.register_all(datetime.date, as_const=True)
def to_config_datetime(d: datetime.date):
    return d.isoformat()


@config_encoder.register(range, as_const=True)
def to_range_config(r: range):
    if r.step == 1 or r.step is None:
        return "{:d}:{:d}".format(r.start, r.stop)
    return "{:d}:{:d}:{:d}".format(r.start, r.stop, r.step)


config_encoder.register(NoneType, as_const=True)(identity)


@config_encoder.register(typing.Pattern[str], as_const=True)
def to_regex_str_config(r: typing.Pattern[str]):
    return r.pattern


@config_encoder.register(typing.Pattern[bytes], as_const=True)
def to_regex_bytes_config(r: typing.Pattern[bytes]):
    pattern_encoded = ''.join(map(chr, r.pattern))
    return pattern_encoded


# enums


@config_encoder.register_all(enum.Enum, enum.IntEnum)
def enum_config_encoder(enum_type):
    return EnumParser(enum_type).config_encode


@config_encoder.register_all(enum.Flag, enum.IntFlag)
def flag_enum_config_encoder(enum_type):
    return FlagParser(enum_type).config_encode


# ############################
# # Custom and generic types #
# ############################


# Note: inflate_config has no inverse; custom classes require custom encoders; thus we don't register for
# unnanotated types (annotation == inspect.Empty or typing.Any) as in the config_decode case


# ####################
# # Importable types #
# ####################


# typing.Callable[...] has the same caveat as custom classes - there's no automatic way to do it.
# However, config_encoder's purpose is to allow encoding function defaults, and generally when
# providing a default for an arg with a typing.Callable annotation, one chooses an importable function;
# we will raise a type Error here if something else was provided.
# in that case, one may @to_config_callable.register(<custom-callable-type>)
@config_encoder.register(typing.Callable)
@singledispatch
def to_config_callable(f: typing.Callable):
    raise TypeError(
        "Don't know how to encode value of type {} as configuration; "
        "Use `{}.register` to define an encoder for this type".format(
            type(f), function_classpath(to_config_callable)
        )
    )


_lru = lru_cache(None)(lambda x: x)

for _type in [types.FunctionType, types.BuiltinFunctionType, type, type(_lru)]:
    to_config_callable.register(_type)(function_classpath)

del _lru

config_encoder.register(typing.Type)(parameterized_classpath)


###############
# Collections #
###############


@config_encoder.register(typing.Collection)
class CollectionConfigEncoder(CollectionWrapper):
    reduce = staticmethod(list)
    getter = config_encoder


@config_encoder.register(typing.Mapping)
class MappingConfigEncoder(MappingWrapper):
    reduce = staticmethod(dict)
    getter = config_encoder
    init_type = True

    def __init__(self, coll_type, *args):
        if self.init_type:
            PicklableWithType.__init__(self, coll_type, *args)
        super().__init__(coll_type, *args)


@config_encoder.register(typing.ChainMap)
class ChainMapConfigEncoder(MappingConfigEncoder):
    reduce = dict

    def __call__(self, value: typing.ChainMap):
        to_dict = super().__call__
        dicts = map(to_dict, value.maps)
        return list(dicts)


@config_encoder.register(typing.Counter)
class CounterConfigEncoder(MappingConfigEncoder):
    init_type = False

    def __init__(self, coll_type, key_type):
        super().__init__(coll_type, key_type, int)
        # can't pass two type args to Counter, hence init_type = False above and we set the type_ attr manually here
        PicklableWithType.__init__(self, coll_type, key_type)


@config_encoder.register(typing.Tuple)
class TupleConfigEncoder(TupleWrapper):
    getter = config_encoder
    reduce = staticmethod(list)


@config_encoder.register(NamedTupleABC)
class NamedTupleConfigEncoder(NamedTupleWrapper):
    getter = config_encoder
    reduce_named = staticmethod(dict)

    def __call__(self, value):
        return super().__call__(value._asdict())


# TODO: finish this
@config_encoder.register(typing.Union)
class UnionConfigEncoder(UnionWrapper):
    tolerate_errors = (ConfigIOUndefinedForType, UnknownSignature, ConfigTypedOutputError)
    reduce = staticmethod(next)
    getter = config_encoder
    exc_class_bad_exception = RaisedDisallowedExceptions
    exc_class_no_success = AllFailed


@config_encoder.register(LazyType)
class LazyConfigEncoder(LazyWrapper):
    getter = config_encoder
