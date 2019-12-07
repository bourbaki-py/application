# coding:utf-8
import decimal
import enum
import fractions
import io
import os
import sys
import typing
import types
import numbers
import pathlib
import datetime
import ipaddress
import collections
import uuid
from functools import partial
from operator import attrgetter
from urllib.parse import ParseResult as URL, urlunparse
from bourbaki.introspection.callables import function_classpath
from bourbaki.introspection.types import LazyType, NamedTupleABC
from bourbaki.introspection.generic_dispatch import (
    GenericTypeLevelSingleDispatch,
    UnknownSignature,
)
from bourbaki.introspection.generic_dispatch_helpers import (
    CollectionWrapper,
    TupleWrapper,
    MappingWrapper,
    UnionWrapper,
    LazyWrapper,
)
from .parsers import EnumParser, FlagParser
from .exceptions import (
    ConfigIOUndefined,
    ConfigTypedOutputError,
    ConfigTypedKeyOutputError,
    ConfigUnionOutputError,
)
from .utils import (
    Empty,
    identity,
    File,
    IODispatch,
    TypeCheckOutput,
    TypeCheckOutputFunc,
    TypeCheckOutputType,
)


class ConfigEncodeDispatch(IODispatch):
    exc_type = ConfigTypedOutputError


class ConfigKeyEncodeDispatch(IODispatch):
    exc_type = ConfigTypedKeyOutputError


to_int_config = ConfigEncodeDispatch("to_int_config", int)
to_int_config.register(numbers.Integral)(int)

to_bool_config = ConfigEncodeDispatch("to_bool_config", bool)
to_bool_config.register(numbers.Integral)(bool)

to_float_config = ConfigEncodeDispatch("to_float_config", float)
to_float_config.register(numbers.Number)(float)

to_complex_config = ConfigEncodeDispatch("to_complex_config", complex)
to_complex_config.register(numbers.Complex)(str)


@to_complex_config.register(numbers.Number)
def number_to_complex_str(x):
    return str(complex(x))


to_fraction_config = ConfigEncodeDispatch("to_fraction_config", fractions.Fraction)
to_fraction_config.register(fractions.Fraction)(str)


@to_fraction_config.register(numbers.Number)
def number_to_fraction_str(x):
    return str(fractions.Fraction(x))


to_decimal_config = ConfigEncodeDispatch("to_decimal_config", decimal.Decimal)
to_decimal_config.register(decimal.Decimal)(str)


@to_decimal_config.register(numbers.Number)
def number_to_decimal_str(x):
    return str(decimal.Decimal(x))


to_bytes_config = ConfigEncodeDispatch("to_bytes_config", bytes)
to_bytes_config.register((bytes, bytearray))(list)


bool_to_str = ConfigKeyEncodeDispatch("bool_to_str", bool)
bool_to_str.register(bool)(str)


@bool_to_str.register(numbers.Integral)
def integral_to_bool_str(i):
    return str(bool(i))


int_to_str = ConfigKeyEncodeDispatch("int_to_str", int)
int_to_str.register(int)(str)


@int_to_str.register(numbers.Integral)
def integral_to_int_str(b):
    return str(int(b))


float_to_str = ConfigKeyEncodeDispatch("float_to_str", float)
float_to_str.register(float)(str)


@float_to_str.register(numbers.Number)
def number_to_float_str(i):
    return str(float(i))


bytes_to_str = ConfigKeyEncodeDispatch("bytes_to_str", typing.ByteString)
bytes_to_str.register(bytes)(repr)


@bytes_to_str.register(bytearray)
def bytearray_to_str(b):
    return repr(bytes(b))


def repr_range(r):
    if r.step == 1:
        return "{}:{}".format(r.start, r.stop)
    return "{}:{}:{}".format(r.start, r.stop, r.step)


def encode_bytes_re(r):
    s = encode_str_re(r)
    if isinstance(s, str):
        return s
    return s.decode()


encode_str_re = attrgetter("pattern")


def config_file_encode(file: io.IOBase):
    if file in (sys.stdout, sys.stderr, sys.stdin):
        return "-"
    try:
        name = file.name
    except AttributeError as e:
        raise ConfigTypedOutputError(type(file), file, e)
    else:
        return os.path.abspath(name)


config_encoder_methods = {
    str: identity,
    range: repr_range,
    pathlib.Path: str,
    uuid.UUID: str,
    File: config_file_encode,
    types.FunctionType: function_classpath,
    types.BuiltinFunctionType: function_classpath,
    datetime.date: datetime.date.isoformat,
    datetime.datetime: datetime.datetime.isoformat,
    ipaddress.IPv4Address: str,
    ipaddress.IPv6Address: str,
    URL: urlunparse,
    typing.Pattern: encode_str_re,
    typing.Pattern[str]: encode_str_re,
    typing.Pattern[bytes]: encode_bytes_re,
}


class TypeCheckConfigEncoder(TypeCheckOutput):
    exc_cls = ConfigTypedOutputError


# don't isolate user-defined Generics because in general we don't know how to encode them...

config_key_encoder = GenericTypeLevelSingleDispatch(
    __name__, isolated_bases=[typing.Union]
)

config_encoder = GenericTypeLevelSingleDispatch(__name__, isolated_bases=[typing.Union])


@config_encoder.register_all(types.FunctionType, types.BuiltinFunctionType)
@config_key_encoder.register_all(types.FunctionType, types.BuiltinFunctionType)
class TypeCheckConfigEncodeFunc(TypeCheckOutputFunc):
    exc_cls = ConfigTypedOutputError


@config_encoder.register(typing.Type)
@config_key_encoder.register(typing.Type)
class TypeCheckConfigEncodeType(TypeCheckOutputType):
    exc_cls = ConfigTypedOutputError


# base for decoders that decode collections
class GenericConfigEncoderMixin:
    getter = config_encoder
    legal_container_types = None
    reduce = list
    helper_cls = None

    def typecheck(self, value):
        if self.legal_container_types is None:
            return value
        if not isinstance(value, self.legal_container_types):
            raise ConfigTypedOutputError(self.reduce, value)
        return value

    def __call__(self, value):
        arg = self.typecheck(value)
        return self.helper_cls.__call__(self, arg)


@config_encoder.register(typing.Collection)
class ConfigCollectionEncoder(GenericConfigEncoderMixin, CollectionWrapper):
    reduce = list
    helper_cls = CollectionWrapper


@config_encoder.register(typing.Mapping)
class ConfigMappingEncoder(GenericConfigEncoderMixin, MappingWrapper):
    reduce = dict
    key_getter = config_key_encoder
    helper_cls = MappingWrapper


@config_encoder.register(typing.ChainMap)
class ConfigChainMapEncoder(ConfigMappingEncoder):
    def __call__(self, arg):
        if isinstance(arg, collections.ChainMap):
            maps = arg.maps
        else:
            maps = [self.typecheck(arg)]
        to_map = super(type(self), self).__call__
        maps = map(to_map, maps)
        return list(maps)


@config_encoder.register(typing.Counter)
class ConfigCounterEncoder(ConfigMappingEncoder):
    def __init__(self, coll_type, key_type):
        super(ConfigCounterEncoder, self).__init__(coll_type, key_type, int)


@config_encoder.register(typing.Tuple)
class ConfigTupleEncoder(TupleWrapper):
    getter = config_encoder
    reduce = staticmethod(list)
    _collection_cls = ConfigCollectionEncoder


class _DictFromNamedTupleIter:
    def __init__(self, tuple_cls):
        self.tuple_cls = tuple_cls

    def __call__(self, iter_):
        return dict(zip(self.tuple_cls._fields, iter_))


@config_encoder.register(NamedTupleABC)
class ConfigNamedTupleEncoder(TupleWrapper):
    getter = config_encoder
    get_reducer = staticmethod(_DictFromNamedTupleIter)


@config_encoder.register(typing.Union)
class UnionConfigEncoder(GenericConfigEncoderMixin, UnionWrapper):
    tolerate_errors = (ConfigIOUndefined, UnknownSignature)
    reduce = staticmethod(next)
    helper_cls = UnionWrapper
    exc_class = ConfigUnionOutputError


@config_encoder.register(LazyType)
class LazyConfigDecoder(LazyWrapper):
    getter = config_encoder


@config_encoder.register_all(enum.Enum, enum.IntEnum)
@config_key_encoder.register_all(enum.Enum, enum.IntEnum)
def config_enum_encoder(enum_):
    return EnumParser(enum_).config_encode


@config_encoder.register_all(enum.Flag, enum.IntFlag)
@config_key_encoder.register_all(enum.Flag, enum.IntFlag)
def config_flag_encoder(enum_):
    return FlagParser(enum_).config_encode


@config_key_encoder.register(typing.Union)
class UnionConfigKeyEncoder(UnionConfigEncoder):
    getter = config_key_encoder


# typecheck the inputs of these; they aren't dispatched and they're specific
for t, enc in config_encoder_methods.items():
    f = partial(TypeCheckConfigEncoder, encoder=enc)
    config_encoder.register(t)(f)
    config_key_encoder.register(t)(f)


# don't need to typecheck these; they're dispatched selectively
for t, (enc, key_enc) in {
    int: (to_int_config, int_to_str),
    float: (to_float_config, float_to_str),
    bool: (to_bool_config, bool_to_str),
    typing.ByteString: (to_bytes_config, bytes_to_str),
}.items():
    config_encoder.register(t, as_const=True)(enc)
    config_key_encoder.register(t, as_const=True)(key_enc)


# let unspecified-type values pass through unaltered; dumping config later will raise an error if they aren't
# encodeable in the specified format. In most cases this will enforce JSON-typed objects
config_encoder.register(Empty, as_const=True)(identity)
config_encoder.register(typing.Any, as_const=True)(identity)


# require keys to be strings when the types aren't specified; deserialization can only return string keys so we require
# this for round-trip consistency
require_str_for_key = TypeCheckConfigEncoder(str, encoder=identity)
config_key_encoder.register(Empty, as_const=True)(require_str_for_key)
config_key_encoder.register(typing.Any, as_const=True)(require_str_for_key)
