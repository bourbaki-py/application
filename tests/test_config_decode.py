# coding:utf-8
import pytest
import logging
import sys
import re
from itertools import chain, product
from pathlib import PosixPath, Path
from datetime import date, datetime
from fractions import Fraction
from decimal import Decimal
from uuid import UUID, uuid4
from ipaddress import IPv4Address, IPv6Address
from types import BuiltinFunctionType
from typing import (
    Dict,
    Mapping,
    List,
    MutableSet,
    Tuple,
    Union,
    Optional,
    Pattern,
    Counter,
    IO,
    ByteString,
    ChainMap,
    NamedTuple,
    Set,
    Callable,
    Generic,
    Any,
    TypeVar,
    Type,
)
import collections as cl
from enum import Enum, Flag
from bourbaki.application.typed_io.file_types import File
from bourbaki.application.typed_io.config.config_decode import config_decoder
from bourbaki.application.typed_io.config.config_encode import config_encoder

logging.basicConfig(level=logging.INFO, stream=sys.stderr)

some_uuid = uuid4()


class SomeEnum(Enum):
    foo = 1
    bar = 2
    baz = 3


SomeFlag = Flag("SomeFlag", names="foo bar baz".split())


def __repr__(self):
    return "{}({})".format(self.__class__.__name__, super(type(self), self).__repr__())


class _myint(int):
    __repr__ = __repr__


class _myfloat(float):
    __repr__ = __repr__


class _mycomplex(complex):
    __repr__ = __repr__


class _mybytes(bytes):
    __repr__ = __repr__


class _mybytearray(bytearray):
    __repr__ = __repr__


class _myUUID(UUID):
    __repr__ = __repr__


class _myPath(PosixPath):
    __repr__ = __repr__


class _myDecimal(Decimal):
    __repr__ = __repr__


class _myFraction(Fraction):
    pass  # repr uses class name already


class _mydate(date):
    __repr__ = __repr__


class _mydatetime(datetime):
    __repr__ = __repr__


class _mystr(str):
    __repr__ = __repr__


class SomeNamedTuple(NamedTuple):
    x: SomeEnum
    y: Set[_myFraction]

    def __eq__(self, other):
        return same_value(self.x, other.x) and same_contents(self.y, other.y)


T = TypeVar("T", covariant=True)


class MyList(Generic[T]):
    def __init__(self, *values: T):
        self.coll = list(values)

    def __eq__(self, other):
        try:
            same_contents(self.coll, other.coll)
        except AssertionError:
            return False
        return True

    def __str__(self):
        return "{}({})".format(self.__class__.__name__, ", ".join(map(repr, self.coll)))


class SubList(MyList[_myint]):
    def __init__(self, *values: _myint):
        self.coll = list(map(_myint, values))


T_ = TypeVar("T_", bound=datetime)


class SomeCallable(Generic[T_]):
    def __init__(self, x: T_, y: Optional[SomeNamedTuple] = None):
        self.x = x
        self.y = y

    def __call__(self, *args, **kwargs):
        pass

    def __str__(self):
        return "x: {}, y: {}".format(self.x, self.y)

    def __eq__(self, other):
        return (
            type(self.x) is type(other.x)
            and self.x == other.x
            and
            # 'is' operator fails for this namedtuple type for some reason
            type(self.y).__name__ == type(other.y).__name__
            and all(a == b for a, b in zip(self.y, other.y))
        )


def same_value(a, b):
    assert a == b
    assert type(a) is type(b)


def same_file(f1, f2):
    assert f1.name == f2.name
    assert f1.mode == f2.mode
    try:
        assert f1.encoding.lower() == f2.encoding.lower()
    except AttributeError:
        pass
    assert type(f1) is type(f2)


def same_contents(a, b):
    assert len(a) == len(b)
    assert type(a) is type(b)
    if isinstance(a, (set, frozenset)):
        a = sorted(a)
    if isinstance(b, (set, frozenset)):
        b = sorted(b)
    for a_, b_ in zip(a, b):
        same_value(a_, b_)


def same_keyvals(d, e):
    assert len(d) == len(d)
    assert type(d) is type(e)
    for k in d.keys():
        assert k in e
        same_value(d[k], e[k])


def custom_subclasses(cls):
    return (sub for sub in cls.__subclasses__() if sub.__name__.startswith("_my"))


def to_instance_of(value, type_):
    if type(value) is type_:
        return value
    elif issubclass(type_, datetime):
        tup = (
            value.year,
            value.month,
            value.day,
            value.hour,
            value.minute,
            value.second,
            value.microsecond,
        )
        return type_(*tup, tzinfo=value.tzinfo)
    elif issubclass(type_, date):
        return type_(value.year, value.month, value.day)

    try:
        return type_(value)
    except:
        # UUID(UUID('uuid-string')) doesn't work for instance
        return type_(str(value))


basic_type_val_tups = [
    (bool, True, ["true", True]),
    (int, 123, [123, "123"]),
    (float, 123.0, [123.0, 123, "123e0"]),
    (float, 1.23, [1.23, "1.23"]),
    (complex, 123 + 0j, [123, 123.0, "123.0", "123+0j"]),
    (complex, 1 + 23j, [1 + 23j, "1+23j"]),
    (Decimal, Decimal("1.23"), ["1.23", Decimal("1.23")]),
    (Decimal, Decimal(1), [1, 1.0]),
    (Fraction, Fraction(2, 1), [2, 2.0, "2/1", [2, 1], (2, 1)]),
    (
        date,
        date(1234, 5, 6),
        ["1234-05-06", date(1234, 5, 6), [1234, 5, 6], (1234, 5, 6)],
    ),
    (
        datetime,
        datetime(1234, 5, 6, 7, 8, 9),
        [
            datetime(1234, 5, 6, 7, 8, 9).timestamp(),
            "1234-05-06T07:08:09",
            datetime(1234, 5, 6, 7, 8, 9),
            (1234, 5, 6, 7, 8, 9),
            [1234, 5, 6, 7, 8, 9],
        ],
    ),
    (
        bytes,
        b"\x01\x02\x03",
        [b"\x01\x02\x03", "\x01\x02\x03", bytearray([1, 2, 3]), [1, 2, 3], (1, 2, 3)],
    ),
    (
        bytearray,
        bytearray(b"\x01\x02\x03"),
        [b"\x01\x02\x03", "\x01\x02\x03", bytearray([1, 2, 3]), [1, 2, 3], (1, 2, 3)],
    ),
    (UUID, some_uuid, [str(some_uuid)]),
    (IPv4Address, IPv4Address("1.2.3.4"), ["1.2.3.4"]),
    (IPv6Address, IPv6Address("1:2::3:4"), ["1:2::3:4", "1:2:0::0:3:4"]),
    (PosixPath, PosixPath("foo/bar/baz/"), ["foo/bar/baz/", "foo/bar/baz"]),
    (str, "1 2 3", ["1 2 3"]),
]


basic_testcases = list(
    chain.from_iterable(
        (
            (t, i, to_instance_of(ovalue, t), same_value)
            for t, i in product(chain((type_,), custom_subclasses(type_)), ivalues)
        )
        for (type_, ovalue, ivalues) in basic_type_val_tups
    )
)

complex_test_cases = [
    (type, "collections.OrderedDict", cl.OrderedDict, same_value),
    (range, "1:2:3", range(1, 2, 3), same_value),
    (range, [1, 2, 3], range(1, 2, 3), same_value),
    (SomeEnum, "foo", SomeEnum.foo, same_value),
    (SomeFlag, ["foo", "bar"], SomeFlag.foo | SomeFlag.bar, same_value),
    (SomeFlag, "foo|bar", SomeFlag.foo | SomeFlag.bar, same_value),
    (Callable, "itertools.chain", chain, same_value),
    (
        Counter[str],
        {"foo": 1, "bar": 2},
        cl.Counter(["foo", "bar", "bar"]),
        same_keyvals,
    ),
    (
        Counter[int],
        [("1", 1), ("2", "2"), ("3", "3")],
        cl.Counter({1: 1, 2: 2, 3: 3}),
        same_keyvals,
    ),
    (date, "2018-01-01", date(2018, 1, 1), same_value),
    (datetime, "2018-01-01T12:00:00.000", datetime(2018, 1, 1, 12), same_value),
    (bytes, [1, 2, 3], b"\x01\x02\x03", same_value),
    (ByteString, "foo", b"foo", same_value),
    (List[bytes], ["foo", [1, 2, 3]], [b"foo", b"\x01\x02\x03"], same_contents),
    (
        MutableSet[bytes],
        ["foo\xff", [1, 2, 3]],
        {b"foo\xff", b"\x01\x02\x03"},
        same_contents,
    ),
    (
        Tuple[float, date, List[Path]],
        [1, "2018-01-01", ("foo", "bar")],
        (1.0, date(2018, 1, 1), [Path("foo"), Path("bar")]),
        same_contents,
    ),
    (Pattern[bytes], "foobar", re.compile(b"foobar"), same_value),
    (
        List[Tuple[float, bool]],
        ([1, True], [2, False]),
        [(1.0, True), (2.0, False)],
        same_contents,
    ),
    (
        Union[Mapping[date, Tuple[int, bool]], List[Tuple[date, Tuple[int, bool]]]],
        [["2018-01-01", [1, True]], ["2019-01-01", [2, "false"]]],
        [(date(2018, 1, 1), (1, True)), (date(2019, 1, 1), (2, False))],
        same_contents,
    ),
    (
        Union[Mapping[date, Tuple[int, bool]], List[Tuple[date, ...]]],
        dict([["2018-01-01", [1, "true"]], ["2019-01-01", [2, False]]]),
        dict([(date(2018, 1, 1), (1, True)), (date(2019, 1, 1), (2, False))]),
        same_contents,
    ),
    (Tuple[complex, ...], ["1+2j", 3 + 4j], (1 + 2j, 3 + 4j), same_contents),
    (
        ChainMap[int, range],
        [{1: "1:2", 2: [3, 4, 5]}, {"3": "6:7"}],
        cl.ChainMap({1: range(1, 2), 2: range(3, 4, 5), 3: range(6, 7)}),
        same_keyvals,
    ),
    (
        ChainMap[int, range],
        {1: "1:2", 2: [3, 4, 5], "3": "6:7"},
        cl.ChainMap({1: range(1, 2), 2: range(3, 4, 5), 3: range(6, 7)}),
        same_keyvals,
    ),
    (
        SomeNamedTuple,
        {"x": "foo", "y": [[1, 2], "3/4"]},
        SomeNamedTuple(SomeEnum.foo, {_myFraction(1, 2), _myFraction(3, 4)}),
        same_contents,
    ),
    (
        SomeNamedTuple,
        ["foo", (0.5, "3/4")],
        SomeNamedTuple(SomeEnum.foo, {_myFraction(1, 2), _myFraction(3, 4)}),
        same_contents,
    ),
    (
        Dict[BuiltinFunctionType, Tuple[Type[int], Type[str]]],
        {
            "sorted": ["int", "str"],
            "ord": [
                "{}.{}".format(__name__, _myint.__name__),
                "{}.{}".format(__name__, _mystr.__name__),
            ],
        },
        {sorted: (int, str), ord: (_myint, _mystr)},
        same_keyvals,
    ),
    (
        Callable[[Any], SomeEnum],
        "{}.{}".format(__name__, SomeEnum.__name__),
        SomeEnum,
        same_value,
    ),
]

inflation_test_cases = [
    # inflation path for callables
    (
        Callable,
        {
            "__classpath__": "{}.{}".format(__name__, SomeCallable.__name__),
            "__args__": [[1234, 5, 6, 7, 8, 9], {"x": "bar", "y": [[1, 2], "3/4"]}],
        },
        SomeCallable(
            datetime(1234, 5, 6, 7, 8, 9),
            SomeNamedTuple(SomeEnum.bar, {_myFraction(1, 2), _myFraction(3, 4)}),
        ),
        same_value,
    ),
    (
        SomeCallable[_mydatetime],
        {
            "__classpath__": "{}.{}".format(__name__, SomeCallable.__name__),
            "__kwargs__": {"x": "1234-05-06T07:08:09", "y": ("foo", ["3/4"])},
        },
        SomeCallable(
            _mydatetime(1234, 5, 6, 7, 8, 9),
            SomeNamedTuple(SomeEnum.foo, {_myFraction(3, 4)}),
        ),
        same_value,
    ),
    (
        MyList[int],
        {"__classpath__": "test_config_decode.SubList", "__args__": [True, 2, 3.0]},
        SubList(_myint(1), _myint(2), _myint(3)),
        same_value,
    ),
]


@pytest.mark.parametrize(
    "type_,input_,expected,cmp",
    basic_testcases + complex_test_cases + inflation_test_cases,
)
def test_postproc(type_, input_, expected, cmp):
    """We have to use a custom comparison here to assert that types are the same as well as
    values; e.g. 1.0 compares equal to 1 but we want a stricter test than that."""
    print("computing decoder for", type_)
    postproc = config_decoder(type_)
    print("decoder", postproc)
    print("decoding value", input_)
    decoded = postproc(input_)
    print("decoded", decoded)
    print("type", type(decoded))
    print("value", str(decoded))
    cmp(expected, decoded)


@pytest.mark.parametrize(
    "type_,input_,expected,cmp", basic_testcases + complex_test_cases
)
def test_roundtrip(type_, input_, expected, cmp):
    """We have to use a custom comparison here to assert that types are the same as well as
    values; e.g. 1.0 compares equal to 1 but we want a stricter test than that."""
    print("computing decoder for", type_)
    postproc = config_decoder(type_)
    print("decoder", postproc)
    print("computing encoder for", type_)
    preproc = config_encoder(type_)
    print("encoder", preproc)
    encoded = preproc(expected)
    print("encoded", encoded)
    decoded = postproc(encoded)
    print("decoded", decoded)
    # TODO: a couple comparisons fail here
    print("type", type(decoded))
    print("value", str(decoded))
    cmp(expected, decoded)


@pytest.mark.parametrize(
    "type_,input_,expected",
    [
        (File["r"], "-", sys.stdin),
        (File["w"], "-", sys.stdout),
        (File["a+"], None, None),
        (File["rb"], None, None),
        (IO[str], None, None),
        (IO[bytes], None, None),
    ],
)
def test_filetype_roundtrip(type_, input_, expected, tmp_path):
    if input_ is None:
        # IO case - read mode if file exists, write mode otherwise
        newpath = tmp_path / "test"
        if type_ is IO[str]:
            mode = "r"
        elif type_ is IO[bytes]:
            mode = "rb"
        else:
            mode = type_.mode

        # create for reading
        newpath.touch()
        input_ = str(newpath)
        expected = open(newpath, mode)
        cmp = same_file
    else:
        cmp = same_value

    test_postproc(type_, input_, expected, cmp)
    test_roundtrip(type_, input_, expected, cmp)
