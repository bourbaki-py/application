#!/usr/bin/env python
# coding:utf-8
from typing import *
from typing import ChainMap
import collections
import itertools
from numbers import Number
import os
import tempfile

import pytest

from bourbaki.introspection.types import LazyType, get_generic_args
from bourbaki.introspection.types.compat import NEW_TYPING
from bourbaki.introspection.callables import call_repr
from bourbaki.application.typed_io import TypedIO
from bourbaki.application.typed_io.utils import *
from bourbaki.application.typed_io.exceptions import *
from bourbaki.application.typed_io.cli_repr_ import bool_cli_repr, KEY_VAL_JOIN_CHAR
from bourbaki.application.typed_io.utils import byte_repr, READ_MODES, WRITE_MODES
from bourbaki.application.typed_io.config_repr_ import (
    config_repr,
    bool_config_repr,
    bytes_config_repr,
)
from bourbaki.application.typed_io.config_encode import config_encoder
from bourbaki.application.typed_io.inflation import CLASSPATH_KEY, ARGS_KEY, KWARGS_KEY
from bourbaki.application.typed_io.cli_parse import cli_parser, cli_nargs, cli_repr

undefined = object()


def equal_contents(coll1, coll2):
    if type(coll1) is not type(coll2):
        return False
    if len(coll1) != len(coll2):
        return False
    return set(coll1) == set(coll2)


def equal_contents_nested(coll1, coll2):
    print(coll1, coll2)
    if type(coll1) is not type(coll2):
        return False
    return all(map(equal_contents, coll1, coll2))


def equal_types(val1, val2):
    if type(val1) is not type(val2):
        return False
    return val1 == val2


class _TestCase:
    def __init__(
        self,
        type_,
        cli_nargs=undefined,
        cli_repr=undefined,
        config_repr=undefined,
        test_val=undefined,
        cli_test_val=undefined,
        config_test_val=undefined,
        cli_action=None,
        *,
        encoded_eq=equal_types,
        multi_test=False,
    ):
        self.typed_io = TypedIO(type_)
        self.type_ = type_
        self.cli_nargs = cli_nargs
        self.cli_repr = cli_repr
        self.cli_action = cli_action
        self.cli_test_val = cli_test_val
        self.config_repr = config_repr
        self.config_test_val = config_test_val
        self.test_val = test_val
        self.encoded_eq = encoded_eq
        self.multi_test = multi_test

    def __str__(self):
        return str(self.type_)

    def __repr__(self):
        return repr(self.type_)

    def should_test(self, attr):
        attr_ = dict(
            cli_parser="cli_test_val",
            config_decoder="config_test_val",
            config_encoder="test_val",
        ).get(attr, attr)
        selfattr = getattr(self, attr_)
        if selfattr is undefined:
            return False
        return True

    def _test_attr(self, attr):
        if self.should_test(attr):
            target, test = getattr(self.typed_io, attr), getattr(self, attr)
            assert target == test

    def _test_callable_attr(self, attr, target, test, exc, encoded=False):
        cond = self.should_test(attr)
        if cond:
            func = getattr(self.typed_io, attr)
            if not self.multi_test:
                test = [test]
            print(attr, "\n test: ", test[0], "\n target: ", target, file=sys.stderr)
            for test_case in test:
                if encoded:
                    cmp = self.encoded_eq
                    assert cmp(target, func(test_case))
                else:
                    assert target == func(test_case)
        elif cond is False:
            with pytest.raises(exc):
                func = getattr(self.typed_io, attr)

    def test_cli_parser(self):
        self._test_callable_attr(
            "cli_parser", self.test_val, self.cli_test_val, CLIIOUndefined
        )

    def test_config_decoder(self):
        self._test_callable_attr(
            "config_decoder", self.test_val, self.config_test_val, ConfigIOUndefined
        )

    def test_config_encoder(self):
        target_val = (
            self.config_test_val[0] if self.multi_test else self.config_test_val
        )
        test_val = [self.test_val] if self.multi_test else self.test_val
        self._test_callable_attr(
            "config_encoder", target_val, test_val, ConfigIOUndefined, encoded=True
        )

    def test_cli_nargs(self):
        self._test_attr("cli_nargs")

    def test_cli_action(self):
        self._test_attr("cli_action")

    def test_cli_repr(self):
        self._test_attr("cli_repr")

    def test_config_repr(self):
        self._test_attr("config_repr")


def mapping_cli_repr_str(keystr, valstr):
    return "{}{}{}".format(keystr, KEY_VAL_JOIN_CHAR, valstr)


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

cli_nargs.register(LazyListInt, as_const=True)(ZERO_OR_MORE)

bytes_cli_repr = byte_repr
bytes_int = [0, 1, 255]
bytes_str = ["0", "1", "255"]
bytes_ = bytes(bytes_int)
bytearray_ = bytearray(bytes_int)

any_coll_cli_repr = any_repr  # seq_cli_repr_template.format(t=any_repr)
any_coll_config_repr = [any_repr, ellipsis_]
int_coll_cli_repr = type_spec(int)  # seq_cli_repr_template.format(t=type_spec(int))
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
bool_float_or_str_cli_repr = "|".join((bool_cli_repr, type_spec(float), type_spec(str)))
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

    def config_encode(self, t=None):
        conf = super().config_encode()
        if t is None:
            enc = identity
        else:
            enc = config_encoder(t)
            conf[CLASSPATH_KEY] = conf[CLASSPATH_KEY] + "[{}]".format(
                parameterized_classpath(t)
            )

        conf["__kwargs__"]["xs"] = {
            str(k): enc(v) for k, v in conf["__kwargs__"]["xs"].items()
        }
        conf["__args__"] = [enc(v) for v in conf["__args__"]]
        return conf


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
    _TestCase(
        bool,
        None,
        bool_cli_repr,
        bool_config_repr,
        True,
        ["true", "True"],
        [True],
        multi_test=True,
    ),
    _TestCase(int, None, type_spec(int), type_spec(int), -1234, "-1234", -1234),
    _TestCase(
        datetime.date,
        None,
        date_repr,
        date_repr,
        date_,
        [date_str],
        [date_str, date_int, date_tup],
        multi_test=True,
    ),
    _TestCase(
        datetime.datetime,
        None,
        datetime_repr,
        datetime_repr,
        datetime_,
        datetime_str,
        datetime_str,
    ),
    _TestCase(
        ipaddress.IPv4Address, None, ipv4_repr, ipv4_repr, ipv4, ipv4_str, ipv4_str
    ),
    _TestCase(
        ipaddress.IPv6Address, None, ipv6_repr, ipv6_repr, ipv6, ipv6_str, ipv6_str
    ),
    # types and functions
    _TestCase(
        Type[Number],
        None,
        classpath_type_repr + "<:numbers.Number",
        classpath_type_repr + "<:numbers.Number",
        test_val=complex,
        cli_test_val="builtins.complex",
        config_test_val="complex",
    ),
    _TestCase(
        types.FunctionType,
        None,
        classpath_function_repr,
        classpath_function_repr,
        test_val=equal_contents,
        cli_test_val="{}.equal_contents".format(__name__),
        config_test_val="{}.equal_contents".format(__name__),
    ),
    # Unions
    _TestCase(
        any_ip,
        None,
        "{}|{}".format(ipv4_repr, ipv6_repr),
        any_ip_config_repr,
        ipv4,
        ipv4_str,
        ipv4_str,
    ),
    _TestCase(
        any_ip,
        None,
        "{}|{}".format(ipv4_repr, ipv6_repr),
        any_ip_config_repr,
        ipv6,
        ipv6_str,
        ipv6_str,
    ),
    _TestCase(
        bool_float_or_str,
        None,
        bool_float_or_str_cli_repr,
        bool_float_or_str_config_repr,
        "asdf",
        "asdf",
        "asdf",
    ),
    _TestCase(
        bool_float_or_str,
        None,
        bool_float_or_str_cli_repr,
        bool_float_or_str_config_repr,
        3.14,
        ".314e1",
        3.14,
    ),
    _TestCase(
        bool_float_or_str,
        None,
        bool_float_or_str_cli_repr,
        bool_float_or_str_config_repr,
        False,
        "FALSE",
        False,
    ),
    # Collections
    _TestCase(
        bytes,
        ZERO_OR_MORE,
        bytes_cli_repr,
        bytes_config_repr,
        bytes_,
        bytes_str,
        bytes_int,
    ),
    _TestCase(
        bytearray,
        ZERO_OR_MORE,
        bytes_cli_repr,
        bytes_config_repr,
        bytearray_,
        bytes_str,
        bytes_int,
    ),
    _TestCase(
        tuple,
        ZERO_OR_MORE,
        any_coll_cli_repr,
        any_coll_config_repr,
        tuple_str_,
        list_str,
        list_str,
    ),
    _TestCase(
        set,
        ZERO_OR_MORE,
        any_coll_cli_repr,
        any_coll_config_repr,
        set_str,
        list_str,
        list_str,
        encoded_eq=equal_contents,
    ),
    _TestCase(
        frozenset,
        ZERO_OR_MORE,
        any_coll_cli_repr,
        any_coll_config_repr,
        frozenset_str,
        list_str,
        list_str,
        encoded_eq=equal_contents,
    ),
    _TestCase(
        list,
        ZERO_OR_MORE,
        any_coll_cli_repr,
        any_coll_config_repr,
        list_str,
        list_str,
        list_str,
    ),
    # mappings
    _TestCase(
        Mapping[int, Tuple[datetime.date, ipaddress.IPv4Address]],
        undefined,
        undefined,
        {type_spec(int): [date_repr, ipv4_repr], ellipsis_: ellipsis_},
        test_val=map_int_tup_date_ip,
        cli_test_val=undefined,
        config_test_val={
            str(k): [d.isoformat(), str(i)] for k, (d, i) in map_int_tup_date_ip.items()
        },
    ),
    _TestCase(
        Mapping[
            Union[int, datetime.date],
            Tuple[Union[ipaddress.IPv4Address, ipaddress.IPv6Address], ...],
        ],
        undefined,
        undefined,
        config_repr={
            "{} OR {}".format(type_spec(int), date_repr): [
                any_ip_config_repr,
                ellipsis_,
            ],
            ellipsis_: ellipsis_,
        },
        test_val=map_int_or_date_tup_any_ip_,
        cli_test_val=undefined,
        config_test_val=map_int_or_date_tup_any_ip_config,
    ),
    _TestCase(
        ChainMap[Type, datetime.date],
        ZERO_OR_MORE,
        cli_repr=mapping_cli_repr_str(classpath_type_repr, date_repr),
        config_repr={classpath_type_repr: date_repr, ellipsis_: ellipsis_},
        test_val=collections.ChainMap({int: date_, complex: date_epoch}),
        cli_test_val=[
            "{}={}".format("int", date_.isoformat()),
            "{}={}".format("builtins.complex", date_epoch.isoformat()),
        ],
        config_test_val=[{"int": date_.isoformat(), "complex": date_epoch.isoformat()}],
    ),
    _TestCase(
        Counter[types.FunctionType],
        ZERO_OR_MORE,
        cli_repr=mapping_cli_repr_str(classpath_function_repr, type_spec(int)),
        config_repr={classpath_function_repr: type_spec(int), ellipsis_: ellipsis_},
        test_val={int: 1, len: 2, __import__: -1234567890},
        cli_test_val=[
            "{}={}".format("int", 1),
            "{}={}".format("len", 2),
            "{}={}".format("__import__", -1234567890),
        ],
        config_test_val={"int": 1, "len": 2, "__import__": -1234567890},
    ),
    # parameterized collections
    _TestCase(
        List[int],
        ZERO_OR_MORE,
        int_coll_cli_repr,
        int_coll_config_repr,
        list_int,
        list_int_as_str,
        list_int,
    ),
    _TestCase(
        Set[int],
        ZERO_OR_MORE,
        int_coll_cli_repr,
        int_coll_config_repr,
        set_int,
        list_int_as_str,
        list_int,
        encoded_eq=equal_contents,
    ),
    _TestCase(
        FrozenSet[int],
        ZERO_OR_MORE,
        int_coll_cli_repr,
        int_coll_config_repr,
        frozenset_int,
        list_int_as_str,
        list_int,
        encoded_eq=equal_contents,
    ),
    _TestCase(
        Tuple[int, ...],
        ZERO_OR_MORE,
        int_coll_cli_repr,
        int_coll_config_repr,
        tuple_int_,
        list_int_as_str,
        list_int,
    ),
    # tuples
    _TestCase(
        Tuple[int, int, int],
        3,
        tuple([type_spec(int)] * 3),
        [type_spec(int)] * 3,
        tuple_int_,
        list_int_as_str,
        list_int,
    ),
    _TestCase(
        Tuple[int],
        1,
        (type_spec(int),),
        [type_spec(int)],
        tuple_int_[:1],
        list_int_as_str[:1],
        list_int[:1],
    ),
    _TestCase(
        Tuple[bool, datetime.datetime, ipaddress.IPv4Address],
        3,
        (bool_cli_repr, datetime_repr, ipv4_repr),
        [bool_config_repr, datetime_repr, ipv4_repr],
        (False, datetime_, ipv4),
        [["false", datetime_str, ipv4_str]],
        [[False, datetime_str, ipv4_str], [False, datetime_int, ipv4_int]],
        multi_test=True,
    ),
    _TestCase(
        FooTup,
        2,
        (type_spec(int), type_spec(str)),
        {"foo": type_spec(int), "bar": type_spec(str)},
        FooTup(1, "2"),
        [["1", 2]],
        [{"foo": 1, "bar": "2"}, [1, "2"]],
        multi_test=True,
    ),
    # Nested collections
    _TestCase(
        List[FooTup],
        2,
        (type_spec(int), type_spec(str)),
        [{"foo": type_spec(int), "bar": type_spec(str)}, '...'],
        [FooTup(1, "2"), FooTup(3, "4")],
        [[["1", 2], ["3", "4"]]],
        [[{"foo": 1, "bar": "2"}, {"foo": 3, "bar": "4"}], [[1, "2"], [3, "4"]]],
        cli_action="append",
        multi_test=True,
    ),
    _TestCase(
        Tuple[FooTup, ...],
        2,
        (type_spec(int), type_spec(str)),
        [{"foo": type_spec(int), "bar": type_spec(str)}, '...'],
        (FooTup(1, "2"), FooTup(3, "4")),
        [[["1", 2], ["3", "4"]]],
        [[{"foo": 1, "bar": "2"}, {"foo": 3, "bar": "4"}], [[1, "2"], [3, "4"]]],
        cli_action="append",
        multi_test=True,
    ),
    _TestCase(
        List[Set[bool_float_or_str]],
        '*',
        bool_float_or_str_cli_repr,
        [[bool_float_or_str_config_repr, '...'], '...'],
        [{True, 2.0, 'foo'}, {3.0, False}],
        [["true", "2", "foo"], ["3", "false"]],
        [[True, 2, "foo"], [3, False]],
        cli_action="append",
        encoded_eq=equal_contents_nested,
        multi_test=False,
    ),
    # Lazy types
    # type_spec here rather than the usual cli_repr because we don't want to load the type to print CLI help
    _TestCase(
        LazyType["datetime.datetime"],
        None,
        type_spec(datetime.datetime),
        datetime_repr,
        datetime_,
        datetime_str,
        datetime_str,
    ),
    _TestCase(
        LazyListInt,
        ZERO_OR_MORE,
        "<List[int]>",
        [type_spec(int), ellipsis_],
        list_int,
        list_int_as_str,
        list_int,
    ),  # we registered with cli_nargs above to get '*' rather than None
    # custom classes
    _TestCase(
        custom_class,
        undefined,
        undefined,
        custom_class.config_repr,
        test_val=custom_class(),
        cli_test_val=undefined,
        config_test_val=custom_class().config_encode(),
    ),
    _TestCase(
        custom_class_with_varargs,
        undefined,
        undefined,
        config_repr=custom_class_with_varargs.config_repr,
        test_val=custom_class_with_varargs(datetime_),
        cli_test_val=undefined,
        config_test_val=custom_class_with_varargs(datetime_).config_encode(),
    ),
    _TestCase(
        custom_class_with_kwargs,
        undefined,
        undefined,
        config_repr=custom_class_with_kwargs.config_repr,
        test_val=custom_class_with_kwargs(a=1, b="two"),
        cli_test_val=undefined,
        config_test_val=custom_class_with_kwargs(a=1, b="two").config_encode(),
    ),
    # custom generic classes
    _TestCase(
        custom_generic_class,
        undefined,
        undefined,
        config_repr=custom_generic_class.config_repr,
        test_val=custom_generic_class(1, 2, 3, xs={1: "two", 3: "four"}),
        cli_test_val=undefined,
        config_test_val=custom_generic_class(
            1, 2, 3, xs={1: "two", 3: "four"}
        ).config_encode(),
    ),
    _TestCase(
        custom_generic_class[str],
        undefined,
        undefined,
        config_repr=custom_generic_class[str].config_repr,
        test_val=custom_generic_class("1", "2", "3", xs={1: "two", 3: "four"}),
        cli_test_val=undefined,
        config_test_val=custom_generic_class(
            "1", "2", "3", xs={"1": "two", "3": "four"}
        ).config_encode(str),
    ),
    _TestCase(
        custom_generic_class[datetime.date],
        undefined,
        undefined,
        config_repr=custom_generic_class[datetime.date].config_repr,
        test_val=custom_generic_class(date_, xs={1: date_}),
        cli_test_val=undefined,
        config_test_val=custom_generic_class(date_, xs={"1": date_}).config_encode(
            datetime.date
        ),
    ),
]


@pytest.mark.parametrize("test_case", test_cases)
def test_cli_nargs(test_case: _TestCase):
    test_case.test_cli_nargs()


@pytest.mark.parametrize("test_case", test_cases)
def test_cli_action(test_case: _TestCase):
    test_case.test_cli_action()


@pytest.mark.parametrize("test_case", test_cases)
def test_cli_repr(test_case: _TestCase):
    test_case.test_cli_repr()


@pytest.mark.parametrize("test_case", test_cases)
def test_cli_parser(test_case: _TestCase):
    test_case.test_cli_parser()


@pytest.mark.parametrize("test_case", test_cases)
def test_config_repr(test_case: _TestCase):
    test_case.test_config_repr()


@pytest.mark.parametrize("test_case", test_cases)
def test_config_decoder(test_case: _TestCase):
    test_case.test_config_decoder()


@pytest.mark.parametrize("test_case", test_cases)
def test_config_encoder(test_case: _TestCase):
    test_case.test_config_encoder()


@pytest.mark.parametrize(
    "fileclass1,fileclass2",
    [
        (File, File),
        (File["w"], File),
        (File["r"], File),
        (File["wb"], File),
        (File["rb"], File),
        (BinaryFile, File),
        (TextFile, File),
        (File["w"], TextFile),
        (File["r"], TextFile),
        (File["wb"], BinaryFile),
        (File["rb"], BinaryFile),
        (File["rb"], io.BufferedReader),
        (File["wb"], io.BufferedWriter),
        (File["rb+"], io.BufferedRandom),
        (File["r", "utf-8"], io.TextIOWrapper),
        (File["w", "ascii"], io.TextIOWrapper),
        (File["r+", "utf16"], io.TextIOWrapper),
    ],
)
def test_file_issubclass(fileclass1, fileclass2):
    assert issubclass(fileclass1, fileclass2)
    if fileclass1 != fileclass2:
        assert not issubclass(fileclass2, fileclass1)


@pytest.mark.parametrize(
    "file,fileclass", [(io.BytesIO(), File["wb"]), (io.StringIO(), File["w+"])]
)
def test_file_isinstance(file, fileclass):
    assert isinstance(file, fileclass)


@pytest.mark.parametrize("mode", list(READ_MODES))
def test_open_file_isinstance_by_read_mode(mode):
    path = tempfile.mktemp()
    with open(path, "w") as f:
        # create file
        pass
    with open(path, mode) as f:
        assert isinstance(f, File[mode])
    assert isinstance(f, File[mode])
    os.remove(path)


@pytest.mark.parametrize("mode", list(WRITE_MODES))
def test_open_file_isinstance_by_write_mode(mode):
    path = tempfile.mktemp()
    if "x" not in mode:
        with open(path, "w") as f:
            # create file
            pass
    with open(path, mode) as f:
        assert isinstance(f, File[mode])
    assert isinstance(f, File[mode])
    os.remove(path)
