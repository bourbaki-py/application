# coding:utf-8
import pytest
import re
from pathlib import Path
from datetime import date, datetime
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


class SomeEnum(Enum):
    foo = 1
    bar = 2
    baz = 3


SomeFlag = Flag("SomeFlag", names="foo bar baz".split())


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


@pytest.mark.parametrize(
    "type_,value,expected,cmp",
    [
        (int, 1, 1, same_value),
        (str, "foo", "foo", same_value),
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
        (Path, "foo/bar", Path("foo") / "bar", same_value),
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
            [["2018-01-01", [1, True]], ["2019-01-01", [False, 2]]],
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
    postproc = config_decoder(type_)
    out = postproc(value)
    cmp(expected, out)
