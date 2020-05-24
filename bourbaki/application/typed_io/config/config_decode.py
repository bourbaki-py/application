# coding:utf-8
import typing
import types
import collections.abc
import decimal
import enum
import fractions
from functools import singledispatch
import pathlib
import ipaddress
import datetime
import uuid
from urllib.parse import ParseResult as URL, urlparse
from functools import partial
from bourbaki.introspection.callables import UnStarred
from bourbaki.introspection.imports import import_object
from bourbaki.introspection.generic_dispatch import UnknownSignature
from bourbaki.introspection.types import (
    get_constructor_for,
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
from .inflation import inflate_config
from ..base_parsers import (
    parse_regex_bytes,
    parse_regex,
    parse_range,
    parse_iso_date,
    parse_iso_datetime,
    parse_bool,
    parse_bytes,
    EnumParser,
    FlagParser,
)
from ..utils import (
    identity,
    Empty,
    TypeCheckInput,
    TypeCheckImport,
    TypeCheckImportType,
    GenericIOTypeLevelSingleDispatch,
)
from ..file_types import File
from ..exceptions import (
    ConfigTypedInputError, ConfigIOUndefinedForType, AllFailed, RaisedDisallowedExceptions,
)

NoneType = type(None)

T = typing.TypeVar("T")

# basic decoders

# Most of the basic stdlib types could serve as their own parsers, but since configuration values
# can be types we wouldn't necessarily _want_ to silently convert (e.g. to int from bool or float),
# we register specific input types here, using `cant_decode_to` as the base implementation for a
# `singledispatch` function, to simply raise an error for unregistered input types. These can then
# be post-processed with custom subclasses if they are present, using `to_instance_of` below.

def cant_decode_to(value, type_: typing.Type[T], input_types: typing.Tuple[typing.Type]) -> T:
    msg = "Can't convert value {!r} to instance of {!s}".format(value, type_)
    if input_types:
        msg = msg + "; acceptable input types are {}".format(input_types)
    raise TypeError(msg)


def to_instance_of(value, type_: typing.Type[T]) -> T:
    if type(value) is type_:
        return value
    return type_(value)


for _funcname, _types in [
    ('to_int', (int, str)),
    ('to_float', (float, int, str)),
    ('to_complex', (int, float, complex, str)),
    ('to_fraction', (int, float, str, fractions.Fraction)),
    ('to_decimal', (int, str, float, decimal.Decimal)),
    ('to_bytes', (bytes, bytearray, list, tuple)),
    ('to_bytearray', (bytearray, bytes, list, tuple)),
    ('to_uuid', (str,)),
    ('to_ipaddress', (str,)),
    ('to_path', (pathlib.Path, str,)),
    ('to_file', (str,)),
    ('to_str', (str,)),
]:
    globals()[_funcname] = _dispatcher = singledispatch(partial(cant_decode_to, input_types=_types))
    _dispatcher.__name__ = _funcname
    for type_ in _types:
        _dispatcher.register(type_)(to_instance_of)


@to_int.register(float)
def float_to_int(num: float, type_):
    if num.is_integer():
        return type_(num)
    raise ValueError(
        "Can't decode integer type {} from non-integer floating point value {}".format(
            type_.__name__, num
        )
    )


@to_fraction.register(list)
@to_fraction.register(tuple)
def numerator_denominator_to_fraction(tup, type_):
    if len(tup) != 2:
        raise ValueError(
            "If instantiated from a tuple, {} requires a 2-tuple; got {}".format(
                type_.__name__, tup
            )
        )
    return type_(*tup)


to_bytes.register(str)(parse_bytes)
to_bytearray.register(str)(parse_bytes)

to_date = singledispatch(partial(cant_decode_to, input_types=(str, datetime.date, int, float, list, tuple)))
to_datetime = singledispatch(partial(cant_decode_to, input_types=(str, datetime.date, datetime.datetime, int, float, list, tuple)))

to_date.register(str)(parse_iso_date)
to_datetime.register(str)(parse_iso_datetime)

@to_date.register(datetime.date)
@to_datetime.register(datetime.date)
def to_date_date(value: datetime.date, type_: typing.Type[datetime.date]) -> datetime.date:
    if type(value) is not type_:
        return type_(value.year, value.month, value.day)
    return value

@to_datetime.register(datetime.datetime)
def to_datetime_datetime(value: datetime.datetime, type_: typing.Type[datetime.datetime]) -> datetime.datetime:
    if type(value) is not type_:
        tup = (value.year, value.month, value.day, value.hour, value.minute, value.second, value.microsecond)
        return type_(*tup, tzinfo=value.tzinfo)
    return value

@to_date.register(list)
@to_date.register(tuple)
@to_datetime.register(list)
@to_datetime.register(tuple)
def date_from_tuple(t, type_: typing.Type[datetime.date]) -> datetime.date:
    return type_(*t)

@to_date.register(int)
@to_date.register(float)
@to_datetime.register(int)
@to_datetime.register(float)
def to_date_timestamp(value: int, type_: typing.Type[datetime.date]) -> datetime.date:
    return type_.fromtimestamp(value)


# range, bool, and NoneType aren't subclassable, so we bind them here
to_bool = singledispatch(partial(cant_decode_to, type_=bool, input_types=(bool, str)))
to_bool.register(bool)(identity)
to_bool.register(str)(parse_bool)

to_range = singledispatch(partial(cant_decode_to, type_=range, input_types=(str, list, tuple, range)))
to_range.register(range)(identity)
to_range.register(str)(parse_range)

@to_range.register(list)
@to_range.register(tuple)
def range_from_tuple(tup):
    return range(*tup)


@to_range.register(int)
def range_from_int(i):
    return range(i)


to_null = singledispatch(partial(cant_decode_to, type_=NoneType, input_types=(NoneType,)))
to_null.register(NoneType)(identity)


# The main dispatcher

config_decoder = GenericIOTypeLevelSingleDispatch(
    "config_decoder",
    isolated_bases=[typing.Union, typing.Generic],
    resolve_exc_class=ConfigIOUndefinedForType,
    call_exc_class=ConfigTypedInputError,
)


class basic_decoder:
    def __init__(self, func):
        self.func = func

    def __call__(self, type_, *args):
        return partial(self.func, type_=get_constructor_for(type_))


# All the simple parsers
for type_, decoder in [
    (str, to_str),
    (int, to_int),
    (float, to_float),
    (complex, to_complex),
    (fractions.Fraction, to_fraction),
    (decimal.Decimal, to_decimal),
    (bytes, to_bytes),
    (bytearray, to_bytearray),
    (datetime.date, to_date),
    (datetime.datetime, to_datetime),
    (uuid.UUID, to_uuid),
    (ipaddress.IPv4Address, to_ipaddress),
    (ipaddress.IPv6Address, to_ipaddress),
    (pathlib.Path, to_path),
    (File, to_file),
]:
    config_decoder.register(type_)(basic_decoder(decoder))

for type_, decoder in [
    (NoneType, to_null),
    (bool, to_bool),
    (range, to_range),
    (typing.Pattern, parse_regex),
    (typing.Pattern[str], parse_regex),
    (typing.Pattern[bytes], parse_regex_bytes),
    (URL, urlparse),
    # ByteString is not a constructor - defer to bytes as default
    (typing.ByteString, config_decoder(bytes)),
]:
    config_decoder.register(type_, as_const=True)(decoder)


# enums

@config_decoder.register_all(enum.Enum, enum.IntEnum)
def enum_config_decoder(enum_type):
    return EnumParser(enum_type).config_decode


@config_decoder.register_all(enum.Flag, enum.IntFlag)
def flag_enum_config_decoder(enum_type):
    return FlagParser(enum_type).config_decode


############################
# Custom and generic types #
############################


# for unannotated params, try to inflate, and if not inflatable return config unchanged (handled by inflate_config)
config_decoder.register(Empty, as_const=True)(inflate_config)


@config_decoder.register_all(typing.Any, typing.Generic)
class TypeCheckInflateConfig(TypeCheckInput):
    def __init__(self, type_, *args):
        super().__init__(type_, *args)

    def decode(self, conf):
        # elide expensive construction if we can rule out that the classpath in the config is wrong from the start
        return inflate_config(conf, target_type=self.type_)


####################
# Importable types #
####################


# treat typing.Callable[...] specially; many things are callable that aren't importable
@config_decoder.register(typing.Callable)
class TypeCheckInflateCallableConfig(TypeCheckInflateConfig):
    def decode(self, conf):
        if isinstance(conf, str):
            # try a function import for a string
            return import_object(conf)
        return super().decode(conf)


config_decoder.register_all(types.FunctionType, types.BuiltinFunctionType)(TypeCheckImport)
config_decoder.register(typing.Type)(TypeCheckImportType)


###############
# Collections #
###############


# base for decoders that decode collections
class GenericConfigDecoderMixin(PicklableWithType):
    getter = config_decoder
    get_reducer = staticmethod(get_constructor_for)
    legal_container_types = None
    helper_cls = None
    exc_cls = ConfigTypedInputError
    init_type = True

    def __init__(self, generic, *args):
        if self.init_type:
            PicklableWithType.__init__(self, generic, *args)
        self.helper_cls.__init__(self, generic, *args)

    def typecheck(self, conf):
        if self.legal_container_types is None:
            return conf
        if not isinstance(conf, self.legal_container_types):
            raise TypeError(
                "Expected an instance of {}; got {}".format(
                    self.legal_container_types, type(conf)
                )
            )
        return conf

    def __call__(self, conf):
        arg = self.typecheck(conf)
        return self.helper_cls.__call__(self, arg)


@config_decoder.register(typing.Collection)
class CollectionConfigDecoder(GenericConfigDecoderMixin, CollectionWrapper):
    legal_container_types = (NonAnyStrCollection,)
    helper_cls = CollectionWrapper


# don't allow sequences to parse from unordered collections
@config_decoder.register(typing.Sequence)
class SequenceConfigDecoder(CollectionConfigDecoder):
    legal_container_types = (collections.abc.Sequence,)


@config_decoder.register(typing.Mapping)
class MappingConfigDecoder(GenericConfigDecoderMixin, MappingWrapper):
    legal_container_types = (collections.abc.Mapping,)
    helper_cls = MappingWrapper

    def __init__(self, coll_type, key_type=typing.Any, val_type=Empty):
        super().__init__(coll_type, key_type, val_type)


@config_decoder.register(typing.ChainMap)
class ChainMapConfigDecoder(MappingConfigDecoder):
    reduce = dict

    def __call__(self, arg):
        to_map = partial(self.helper_cls.__call__, self)
        if isinstance(arg, typing.Sequence):
            maps = arg
        else:  # mapping
            maps = [arg]
        # these will typecheck
        maps = map(to_map, maps)
        return collections.ChainMap(*maps)


@config_decoder.register(typing.Counter)
class CounterConfigDecoder(MappingConfigDecoder):
    init_type = False

    def __init__(self, coll_type, key_type):
        super().__init__(coll_type, key_type, int)
        # can't pass two type args to Counter, hence init_type = False above and we set the type_ attr manually here
        PicklableWithType.__init__(self, coll_type, key_type)

    def __call__(self, arg):
        # don't actually count entries; treat them as key-value tuples
        it = self.call_iter(arg)
        return self.reduce(dict(it))


@config_decoder.register(typing.Tuple)
class TupleConfigDecoder(GenericConfigDecoderMixin, TupleWrapper):
    legal_container_types = (NonAnyStrCollection,)
    helper_cls = TupleWrapper


class _DictFromNamedTupleIter:
    def __init__(self, tuple_cls):
        self.tuple_cls = tuple_cls

    def __call__(self, keyvals):
        return self.tuple_cls(**dict(keyvals))


@config_decoder.register(NamedTupleABC)
class NamedTupleConfigDecoder(GenericConfigDecoderMixin, NamedTupleWrapper):
    get_named_reducer = staticmethod(_DictFromNamedTupleIter)
    get_reducer = staticmethod(UnStarred)
    legal_container_types = (collections.abc.Sequence, collections.abc.Mapping)
    helper_cls = NamedTupleWrapper


@config_decoder.register(typing.Union)
class UnionConfigDecoder(GenericConfigDecoderMixin, UnionWrapper):
    tolerate_errors = (ConfigIOUndefinedForType, UnknownSignature)
    reduce = staticmethod(next)
    exc_class_bad_exception = RaisedDisallowedExceptions
    exc_class_no_success = AllFailed
    helper_cls = UnionWrapper


@config_decoder.register(LazyType)
class LazyConfigDecoder(LazyWrapper):
    getter = config_decoder
