# coding:utf-8
import pytest
import re
from itertools import chain, product, repeat
from pathlib import PosixPath, Path
from datetime import date, datetime
from fractions import Fraction
from decimal import Decimal
from uuid import UUID, uuid4
from ipaddress import IPv4Address, IPv6Address
from typing import (
    Mapping,
    List,
    MutableSet,
    Tuple,
    Union,
    Pattern,
    Counter,
    ByteString,
    ChainMap,
)
import collections as cl
from enum import Enum, Flag
from bourbaki.application.typed_io.config.config_decode import config_decoder

some_uuid = uuid4()


class SomeEnum(Enum):
    foo = 1
    bar = 2
    baz = 3


SomeFlag = Flag("SomeFlag", names="foo bar baz".split())


class _myint(int):
    pass


class _myfloat(float):
    pass


class _mycomplex(complex):
    pass


class _mybytes(bytes):
    pass


class _mybytearray(bytearray):
    pass


class _myUUID(UUID):
    pass


class _myPath(PosixPath):
    pass


def same_value(a, b):
    assert a == b
    assert type(a) is type(b)


def same_contents(a, b):
    assert len(a) == len(b)
    assert type(a) is type(b)
    for a_, b_ in zip(a, b):
        same_value(a_, b_)


def same_keyvals(d, e):
    assert len(d) == len(d)
    assert type(d) is type(e)
    for k, l in zip(sorted(set(d)), sorted(set(e))):
        same_value(k, l)
        same_value(d[k], e[l])


def custom_subclasses(cls):
    return (sub for sub in cls.__subclasses__() if sub.__name__.startswith("_my"))


def to_instance_of(value, type_):
    if type(value) is type_:
        return value
    try:
        return type_(value)
    except:
        # UUID(UUID('uuid-string')) doesn't work for instance
        return type_(str(value))


basic_type_val_tups = [
    (int, 123, [123, '123']),
    (float, 123.0, [123.0, 123, '123e0']),
    (float, 1.23, [1.23, '1.23']),
    (complex, 123+0j, [123, 123.0, '123.0', '123+0j']),
    (complex, 1+23j, [1+23j, '1+23j']),
    (bytes, b'\x01\x02\x03', [b'\x01\x02\x03', bytearray([1,2,3]), [1,2,3], (1,2,3)]),
    (bytearray, bytearray(b'\x01\x02\x03'), [b'\x01\x02\x03', bytearray([1,2,3]), [1,2,3], (1,2,3)]),
    (UUID, some_uuid, [str(some_uuid)]),
    (IPv4Address, IPv4Address("1.2.3.4"), ['1.2.3.4']),
    (IPv6Address, IPv6Address("1:2::3:4"), ['1:2::3:4', '1:2:0::0:3:4']),
    (PosixPath, PosixPath("foo/bar/baz/"), ["foo/bar/baz/", "foo/bar/baz"]),
    (str, "1 2 3", ["1 2 3"]),
]


basic_testcases = list(chain.from_iterable(
    ((t, i, to_instance_of(ovalue, t), same_value) for t, i in product(chain((type_,), custom_subclasses(type_)), ivalues))
    for (type_, ovalue, ivalues) in basic_type_val_tups
))


@pytest.mark.parametrize(
    "type_,value,expected,cmp",
    basic_testcases + [
        (type, "collections.OrderedDict", cl.OrderedDict, same_value),
        (range, "1:2:3", range(1, 2, 3), same_value),
        (range, [1, 2, 3], range(1, 2, 3), same_value),
        (SomeEnum, "foo", SomeEnum.foo, same_value),
        (SomeFlag, ["foo", "bar"], SomeFlag.foo | SomeFlag.bar, same_value),
        (
            Counter[str],
            {"foo": 1, "bar": 2},
            cl.Counter(["foo", "bar", "bar"]),
            same_keyvals,
        ),
        (
            Counter[int],
            [("1", "1"), ("2", "2"), ("3", "3")],
            cl.Counter({1: 1, 2: 2, 3: 3}),
            same_keyvals,
        ),
        (date, "2018-01-01", date(2018, 1, 1), same_value),
        (datetime, "2018-01-01T12:00:00.000", datetime(2018, 1, 1, 12), same_value),
        (bytes, [1, 2, 3], b"\x01\x02\x03", same_value),
        (ByteString, "b'foo'", b"foo", same_value),
        (List[bytes], ["b'foo'", [1, 2, 3]], [b"foo", b"\x01\x02\x03"], same_contents),
        (
            MutableSet[bytes],
            ["b'foo'", [1, 2, 3]],
            {b"foo", b"\x01\x02\x03"},
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
            Union[List[Tuple[date, tuple]], Mapping[date, tuple]],
            [["2018-01-01", [1, True]], ["2019-01-01", [False, 2]]],
            [(date(2018, 1, 1), (1, True)), (date(2019, 1, 1), (False, 2))],
            same_contents,
        ),
        (
            Union[Mapping[date, tuple], List[Tuple[date, ...]]],
            dict([["2018-01-01", [1, True]], ["2019-01-01", [False, 2]]]),
            dict([(date(2018, 1, 1), (1, True)), (date(2019, 1, 1), (False, 2))]),
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
    ],
)
def test_postproc(type_, value, expected, cmp):
    """We have to use a custom comparison here to assert that types are the same as well as
    values; e.g. 1.0 compares equal to 1 but we want a stricter test than that."""
    postproc = config_decoder(type_)
    out = postproc(value)
    cmp(expected, out)
