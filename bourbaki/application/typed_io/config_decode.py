# coding:utf-8
import typing
import types
import ast
import collections
import decimal
import enum
import fractions
import pathlib
import ipaddress
import datetime
import uuid
from urllib.parse import ParseResult as URL, urlparse
from functools import partial
from bourbaki.introspection.callables import UnStarred
from bourbaki.introspection.imports import import_object
from bourbaki.introspection.generic_dispatch import (
    GenericTypeLevelSingleDispatch,
    UnknownSignature,
)
from bourbaki.introspection.types import (
    issubclass_generic,
    get_constructor_for,
    NamedTupleABC,
    NonStrCollection,
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
)
from bourbaki.application.typed_io.inflation import inflate_config
from .parsers import (
    parse_regex_bytes,
    parse_regex,
    parse_range,
    parse_iso_date,
    parse_iso_datetime,
    parse_bool,
    parse_path,
    EnumParser,
    FlagParser,
)
from .exceptions import (
    ConfigTypedInputError,
    ConfigIOUndefined,
    ConfigUnionInputError,
    ConfigCollectionKeysNotAllowed,
    ConfigCallableInputError,
)
from .utils import identity, Empty, IODispatch, TypeCheckInput, PicklableWithType, File
from .parsers import TypeCheckImportFunc, TypeCheckImportType
from .config_repr_ import bytes_config_key_repr


class ConfigDecodeDispatch(IODispatch):
    exc_type = ConfigTypedInputError


# basic decoders

config_parse_bool = partial(parse_bool, exc_type=ConfigTypedInputError)

to_int = ConfigDecodeDispatch("to_int", int)
to_int.register(int)(identity)
to_int.register(str)(int)

to_bool = ConfigDecodeDispatch("to_bool", bool)
to_bool.register(bool)(identity)
to_bool.register(str)(config_parse_bool)

to_float = ConfigDecodeDispatch("to_float", float)
to_float.register(float)(identity)
to_float.register((int, str))(float)

to_complex = ConfigDecodeDispatch("to_complex", complex)
to_complex.register(complex)(identity)
to_complex.register((int, str, float))(complex)

to_fraction = ConfigDecodeDispatch("to_fraction", fractions.Fraction)
to_fraction.register(fractions.Fraction)(identity)
to_fraction.register((int, str, float))(fractions.Fraction)


@to_fraction.register((list, tuple))
def numerator_denominator_to_fraction(tup):
    if len(tup) != 2:
        raise ValueError(
            "If instantiated from a tuple, Fraction requires a 2-tuple; got {}".format(
                tup
            )
        )
    return fractions.Fraction(*tup)


to_decimal = ConfigDecodeDispatch("to_decimal", decimal.Decimal)
to_decimal.register(decimal.Decimal)(identity)
to_decimal.register((int, str, float))(decimal.Decimal)

to_bytes = ConfigDecodeDispatch("to_bytes", bytes)
to_bytes.register(bytes)(identity)
to_bytes.register((list, bytearray))(bytes)


@to_bytes.register(str)
def str_to_bytes(s, type_=bytes, exc_type=ConfigTypedInputError):
    try:
        t = ast.parse(s, mode="eval")
    except SyntaxError as e:
        raise exc_type(type_, s, e)
    else:
        expr = t.body
        if not isinstance(expr, ast.Bytes):
            raise exc_type(
                type_,
                s,
                SyntaxError(
                    "{} is not a legal bytes expression; use format {}".format(
                        repr(s), bytes_config_key_repr
                    )
                ),
            )
        b = eval(s)
        if type_ is bytearray:
            b = bytearray(b)
        return b


to_bytearray = ConfigDecodeDispatch("to_bytearray", bytearray)
to_bytearray.register(bytearray)(identity)
to_bytearray.register((list, bytes))(bytearray)
to_bytearray.register(str)(partial(str_to_bytes, type_=bytearray))

to_date = ConfigDecodeDispatch("to_date", datetime.date)
to_date.register(datetime.date)(identity)
to_date.register((int, float))(datetime.date.fromtimestamp)
to_date.register(str)(parse_iso_date)


@to_date.register((tuple, list))
def date_from_tuple(t):
    return datetime.date(*t)


to_datetime = ConfigDecodeDispatch("to_datetime", datetime.datetime)
to_datetime.register(datetime.datetime)(identity)
to_datetime.register((int, float))(datetime.datetime.fromtimestamp)
to_datetime.register(str)(parse_iso_datetime)


@to_datetime.register((tuple, list))
def datetime_from_tuple(t):
    return datetime.datetime(*t)


to_range = ConfigDecodeDispatch("to_range", range)
to_range.register(str)(parse_range)


@to_range.register((list, tuple))
def range_from_tuple(tup):
    return range(*tup)


config_key_decoder_methods = {
    int: to_int,
    bool: to_bool,
    float: to_float,
    complex: to_complex,
    fractions.Fraction: to_fraction,
    decimal.Decimal: to_decimal,
    range: to_range,
    bytes: to_bytes,
    bytearray: to_bytearray,
    typing.ByteString: to_bytes,
    typing.Pattern: parse_regex,
    typing.Pattern[str]: parse_regex,
    typing.Pattern[bytes]: parse_regex_bytes,
    datetime.date: to_date,
    datetime.datetime: to_datetime,
    uuid.UUID: uuid.UUID,
    URL: urlparse,
    ipaddress.IPv4Address: ipaddress.IPv4Address,
    ipaddress.IPv6Address: ipaddress.IPv6Address,
    pathlib.Path: parse_path,
}


# The main dispatcher

config_decoder = GenericTypeLevelSingleDispatch(
    "config_decoder", isolated_bases=[typing.Union, typing.Generic]
)

config_key_decoder = GenericTypeLevelSingleDispatch(
    "config_key_decoder", isolated_bases=[typing.Union, typing.Generic]
)


# no typecheck for unannotated params
config_decoder.register(Empty, as_const=True)(inflate_config)

# File subclasses are their own parsers
config_decoder.register(File)(identity)
config_key_decoder.register(File)(identity)


# don't allow inflation for simple JSON-encodable atomic types
@config_decoder.register_all(str, type(None))
class TypeCheckConfig(TypeCheckInput):
    exc_cls = ConfigTypedInputError


# typecheck annotated params
@config_decoder.register_all(typing.Any, typing.Generic)
class TypeCheckInflateConfig(TypeCheckInput):
    exc_cls = ConfigTypedInputError

    def __init__(self, type_, *args):
        super().__init__(type_, *args)

    def decode(self, conf):
        # elide expensive construction if we can rule out that the classpath in the config is wrong from the start
        return inflate_config(conf, target_type=self.type_)


@config_decoder.register(typing.Callable)
class TypeCheckInflateCallableConfig(TypeCheckInflateConfig):
    exc_cls = ConfigCallableInputError

    def decode(self, conf):
        if isinstance(conf, str):
            # try a function import for a string
            return import_object(conf)
        return super().decode(conf)


@config_decoder.register_all(types.FunctionType, types.BuiltinFunctionType)
@config_key_decoder.register_all(types.FunctionType, types.BuiltinFunctionType)
class TypeCheckImportFuncConfig(TypeCheckImportFunc):
    exc_cls = ConfigTypedInputError


@config_decoder.register(typing.Type)
@config_key_decoder.register(typing.Type)
class TypeCheckImportTypeConfig(TypeCheckImportType):
    exc_cls = ConfigTypedInputError


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
            raise ConfigTypedInputError(
                self.type_,
                conf,
                TypeError(
                    "{} is not an instance of any of {}".format(
                        conf, self.legal_container_types
                    )
                ),
            )
        return conf

    def __call__(self, conf):
        arg = self.typecheck(conf)
        try:
            return self.helper_cls.__call__(self, arg)
        except Exception as e:
            raise self.exc_cls(self.type_, conf, e)


@config_decoder.register(typing.Collection)
class CollectionConfigDecoder(GenericConfigDecoderMixin, CollectionWrapper):
    legal_container_types = (NonAnyStrCollection,)
    helper_cls = CollectionWrapper


# don't allow sequences to parse from unordered collections
@config_decoder.register(typing.Sequence)
class SequenceConfigDecoder(CollectionConfigDecoder):
    legal_container_types = (typing.Sequence,)


@config_decoder.register(typing.Mapping)
class MappingConfigDecoder(GenericConfigDecoderMixin, MappingWrapper):
    legal_container_types = (collections.abc.Mapping, NonAnyStrCollection)
    helper_cls = MappingWrapper

    def __init__(self, coll_type, key_type=typing.Any, val_type=Empty):
        if issubclass_generic(key_type, NonStrCollection):
            raise ConfigCollectionKeysNotAllowed((coll_type, key_type, val_type))
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
        try:
            return collections.ChainMap(*maps)
        except Exception as e:
            raise self.exc_cls(self.type_, arg, e)


@config_decoder.register(typing.Counter)
class CounterConfigEncoder(MappingConfigDecoder):
    init_type = False

    def __init__(self, coll_type, key_type):
        super().__init__(coll_type, key_type, int)
        # can't pass two type args to Counter, hence init_type = False above and we set the type_ attr manually here
        PicklableWithType.__init__(self, coll_type, key_type)

    def __call__(self, arg):
        # don't actually count entries; treat them as key-value tuples
        try:
            it = self.call_iter(arg)
        except Exception as e:
            raise self.exc_cls(self.type_, arg, e)
        return self.reduce(dict(it))


@config_decoder.register(typing.Tuple)
class TupleConfigDecoder(GenericConfigDecoderMixin, TupleWrapper):
    _collection_cls = SequenceConfigDecoder
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
    legal_container_types = (typing.Sequence, typing.Mapping)
    helper_cls = NamedTupleWrapper


@config_decoder.register(typing.Union)
class UnionConfigDecoder(GenericConfigDecoderMixin, UnionWrapper):
    tolerate_errors = (ConfigIOUndefined, UnknownSignature)
    reduce = staticmethod(next)
    helper_cls = UnionWrapper
    exc_class = ConfigUnionInputError


@config_decoder.register(LazyType)
class LazyConfigDecoder(LazyWrapper):
    getter = config_decoder


# enums
@config_decoder.register_all(enum.Enum, enum.IntEnum)
@config_key_decoder.register_all(enum.Enum, enum.IntEnum)
def enum_config_decoder(enum_type):
    return EnumParser(enum_type).config_decode


@config_decoder.register_all(enum.Flag, enum.IntFlag)
@config_key_decoder.register_all(enum.Flag, enum.IntFlag)
def enum_config_decoder(enum_type):
    return FlagParser(enum_type).config_decode


# basic types that require parsing but not typechecking, because the parsers are well-typed
config_decoder.register_from_mapping(config_key_decoder_methods, as_const=True)
config_key_decoder.register_from_mapping(config_key_decoder_methods, as_const=True)

config_key_decoder.register(typing.Any)(identity)


@config_key_decoder.register(typing.Union)
class UnionConfigKeyDecoder(UnionConfigDecoder):
    getter = config_key_decoder
