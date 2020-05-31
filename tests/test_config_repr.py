#!/usr/bin/env python
# coding:utf-8
from typing import *
from typing import ChainMap
import datetime
import ipaddress
import itertools
from numbers import Number
import types

import pytest

from bourbaki.introspection.types import LazyType, get_generic_args
from bourbaki.introspection.types.compat import NEW_TYPING
from bourbaki.introspection.callables import call_repr
from bourbaki.application.typed_io.utils import *
from bourbaki.application.typed_io.exceptions import *
from bourbaki.application.typed_io.base_reprs import (
    any_repr,
    byte_repr,
    complex_repr,
    date_repr,
    datetime_repr,
    ellipsis_,
    type_spec,
    ipv4_repr,
    ipv6_repr,
    classpath,
    classpath_type_repr,
    classpath_function_repr,
)
from bourbaki.application.typed_io.config.config_repr_ import (
    config_repr,
    bool_config_repr,
    bytes_config_repr,
)
from bourbaki.application.typed_io.config.config_encode import config_encoder
from bourbaki.application.typed_io.config.inflation import (
    CLASSPATH_KEY,
    ARGS_KEY,
    KWARGS_KEY,
)


tuple_str_ = ("foo", "bar", "baz")
list_str = list(tuple_str_)
set_str = set(tuple_str_)
frozenset_str = frozenset(tuple_str_)

tuple_int_ = tuple_int_int_int = (-1, 135514356, 0)
list_int_as_str = list(map(str, tuple_int_))
list_int = list(tuple_int_)
set_int = set(tuple_int_)
frozenset_int = frozenset(tuple_int_)
LazyListInt = LazyType["List[int]"]

bytes_int = [0, 1, 255]
bytes_str = ["0", "1", "255"]
bytes_ = bytes(bytes_int)
bytearray_ = bytearray(bytes_int)

any_coll_config_repr = [any_repr, ellipsis_]
int_coll_config_repr = [type_spec(int), ellipsis_]

date_ = datetime.date.today()
date_epoch = datetime.date(1970, 1, 1)
date_str = date_.isoformat()
date_tup = [date_.year, date_.month, date_.day]

datetime_ = datetime.datetime.now()
datetime_str = datetime_.isoformat()
date_int = datetime_int = datetime_.timestamp()
datetime_tup = [
    datetime_.year,
    datetime_.month,
    datetime_.day,
    datetime_.hour,
    datetime_.minute,
    datetime_.second,
    datetime_.microsecond,
]

ipv4_str = "1.23.45.67"
ipv6_str = "12:34:a:b:c:d:e:f"
ipv4 = ipaddress.IPv4Address(ipv4_str)
ipv6 = ipaddress.IPv6Address(ipv6_str)
ipv4_int = int(ipv4)

map_int_tup_date_ip = {
    0: (date_, ipv4),
    -1234567: (date_ - datetime.timedelta(days=100000), ipv4),
}
map_int_or_date_tup_any_ip_ = {
    -1234567: (ipv4, ipv6),
    date_: (ipv6, ipv6),
    date_ - datetime.timedelta(days=100000): (ipv4, ipv4, ipv6, ipv6),
}
map_int_or_date_tup_any_ip_config = {
    str(k) if isinstance(k, int) else k.isoformat(): list(map(str, v))
    for k, v in map_int_or_date_tup_any_ip_.items()
}

any_ip = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]
any_ip_config_repr = " OR ".join([ipv4_repr, ipv6_repr])

bool_float_or_str = Union[bool, float, str]
bool_float_or_str_config_repr = " OR ".join(
    [bool_config_repr, type_spec(float), type_spec(str)]
)


class SimpleEQ:
    args = ()

    def __eq__(self, other):
        return (
            type(self) is type(other)
            and self.args == other.args
            and self.kwargs == other.kwargs
        )

    @property
    def kwargs(self):
        kwargs = dict(self.__dict__)
        sig = signature(self.__init__)
        to_pop = [k for k in kwargs if k not in sig.parameters]
        for k in to_pop:
            kwargs.pop(k)
        kwargs.pop("args", None)
        return kwargs

    def __str__(self):
        args = self.args
        kwargs = self.kwargs
        return call_repr(type(self), args, kwargs)

    __repr__ = __str__


class ConfigReprMeta(type):
    @property
    def __classpath__(self):
        return parameterized_classpath(self)

    __sig_args__ = None
    __kwargs__ = {}

    @property
    def config_repr(self):
        repr_ = {CLASSPATH_KEY: self.__classpath__, KWARGS_KEY: self.__kwargs__}
        if self.__sig_args__ is not None:
            repr_[ARGS_KEY] = self.__sig_args__
        return repr_


class SimpleConfigRepr(SimpleEQ, metaclass=ConfigReprMeta):
    def config_encode(self, *args):
        ns = dict(self.__dict__)
        ns.pop("args", None)
        repr_ = {CLASSPATH_KEY: classpath(type(self)), KWARGS_KEY: ns}
        if hasattr(self, "args"):
            repr_[ARGS_KEY] = list(self.args)
        return repr_


@config_encoder.register(SimpleConfigRepr)
def simple_config_encode(cls, *args):
    def encode(val):
        return val.config_encode(*args)

    return encode


class custom_class(SimpleConfigRepr):
    def __init__(self):
        pass


class custom_class_with_varargs(SimpleConfigRepr):
    def __init__(self, *args: datetime.datetime):
        self.args = args

    __sig_args__ = [datetime_repr, ellipsis_]


class custom_class_with_kwargs(SimpleConfigRepr):
    def __init__(self, **kwargs: Union[int, str]):
        self.__dict__.update(kwargs)

    __kwargs__ = {ellipsis_: " OR ".join((type_spec(int), type_spec(str)))}


T_co = TypeVar("T", covariant=True)


if NEW_TYPING:
    _SimpleConfigReprGenericMeta_bases = ()
else:
    _SimpleConfigReprGenericMeta_bases = (GenericMeta,)


class SimpleConfigReprGenericMeta(ConfigReprMeta, *_SimpleConfigReprGenericMeta_bases):
    @property
    def __kwargs__(cls):
        args = get_generic_args(cls)
        if not args:
            return {"xs": {type_spec(int): any_repr, ellipsis_: ellipsis_}}
        return {"xs": {type_spec(int): config_repr(args[0]), ellipsis_: ellipsis_}}

    @property
    def __sig_args__(cls):
        args = get_generic_args(cls)
        if not args:
            return [any_repr, ellipsis_]
        return [config_repr(args[0]), ellipsis_]


class FooTup(NamedTuple):
    foo: int
    bar: str


class custom_generic_class(
    SimpleConfigRepr, Generic[T_co], metaclass=SimpleConfigReprGenericMeta
):
    def __init__(self, *args: T_co, xs: Mapping[int, T_co]):
        self.xs = xs
        self.args = args


if NEW_TYPING:
    # can't mix metaclasses with Generic in python3.7! No worry, this only complicates testing;
    # the class properties defined above aren't necessary in real use cases
    for t, attr in itertools.product(
        (str, datetime.date),
        ("__kwargs__", "__classpath__", "__sig_args__", "config_repr"),
    ):
        gen = custom_generic_class[t]
        gen.__dict__[attr] = getattr(SimpleConfigReprGenericMeta, attr).fget(gen)


test_cases = [
    # atomic
    (bool, bool_config_repr),
    (int, type_spec(int)),
    (datetime.date, date_repr),
    (datetime.datetime, datetime_repr),
    (ipaddress.IPv4Address, ipv4_repr),
    (ipaddress.IPv6Address, ipv6_repr),
    # types and functions
    (Type[Number], classpath_type_repr + "<:numbers.Number"),
    (types.FunctionType, classpath_function_repr),
    # Unions
    (any_ip, any_ip_config_repr),
    (bool_float_or_str, bool_float_or_str_config_repr),
    (bool_float_or_str, bool_float_or_str_config_repr),
    (bool_float_or_str, bool_float_or_str_config_repr),
    # Collections
    (bytes, bytes_config_repr),
    (bytearray, bytes_config_repr),
    (tuple, any_coll_config_repr),
    (set, any_coll_config_repr),
    (frozenset, any_coll_config_repr),
    (list, any_coll_config_repr),
    # mappings
    (
        Mapping[int, Tuple[datetime.date, ipaddress.IPv4Address]],
        {type_spec(int): [date_repr, ipv4_repr], ellipsis_: ellipsis_},
    ),
    (
        Mapping[
            Union[int, datetime.date],
            Tuple[Union[ipaddress.IPv4Address, ipaddress.IPv6Address], ...],
        ],
        {
            "{} OR {}".format(type_spec(int), date_repr): [
                any_ip_config_repr,
                ellipsis_,
            ],
            ellipsis_: ellipsis_,
        },
    ),
    (
        ChainMap[Type, datetime.date],
        {classpath_type_repr: date_repr, ellipsis_: ellipsis_},
    ),
    (
        Counter[types.FunctionType],
        {classpath_function_repr: type_spec(int), ellipsis_: ellipsis_},
    ),
    (
        DefaultDict[Union[Type, types.BuiltinFunctionType], int],
        {
            "{} OR {}".format(classpath_type_repr, classpath_function_repr): type_spec(
                int
            ),
            ellipsis_: ellipsis_,
        },
    ),
    # parameterized collections
    (List[int], int_coll_config_repr),
    (Set[int], int_coll_config_repr),
    (FrozenSet[int], int_coll_config_repr),
    (Tuple[int, ...], int_coll_config_repr),
    # tuples
    (Tuple[int, int, int], [type_spec(int)] * 3),
    (Tuple[int], [type_spec(int)]),
    (
        Tuple[bool, datetime.datetime, ipaddress.IPv4Address],
        [bool_config_repr, datetime_repr, ipv4_repr],
    ),
    (FooTup, {"foo": type_spec(int), "bar": type_spec(str)}),
    (
        Tuple[FooTup, complex],
        [{"foo": type_spec(int), "bar": type_spec(str)}, complex_repr],
    ),
    # Nested collections
    (List[FooTup], [{"foo": type_spec(int), "bar": type_spec(str)}, "..."]),
    (Tuple[FooTup, ...], [{"foo": type_spec(int), "bar": type_spec(str)}, "..."]),
    (List[Set[bool_float_or_str]], [[bool_float_or_str_config_repr, "..."], "..."]),
    # Lazy types
    (LazyType["datetime.datetime"], datetime_repr),
    (LazyListInt, [type_spec(int), ellipsis_]),
    # custom classes
    (custom_class, custom_class.config_repr),
    (custom_class_with_varargs, custom_class_with_varargs.config_repr),
    (custom_class_with_kwargs, custom_class_with_kwargs.config_repr),
    # custom generic classes
    (custom_generic_class, custom_generic_class.config_repr),
    (custom_generic_class[str], custom_generic_class[str].config_repr),
    (
        custom_generic_class[datetime.date],
        custom_generic_class[datetime.date].config_repr,
    ),
]


@pytest.mark.parametrize("type_, repr_", test_cases)
def test_config_repr(type_, repr_):
    conf_repr = config_repr(type_)
    assert conf_repr == repr_
