# coding:utf-8
import pytest
import logging
import os
import sys
import re
from itertools import chain, product
from ipaddress import IPv4Address, IPv6Address
from types import BuiltinFunctionType
from typing import (
    Dict,
    Mapping,
    List,
    MutableSet,
    Tuple,
    Union,
    Pattern,
    Counter,
    IO,
    ByteString,
    ChainMap,
    Callable,
    Any,
    Type,
)
import collections as cl
from bourbaki.application.typed_io.file_types import File
from bourbaki.application.typed_io.config.config_decode import config_decoder
from bourbaki.application.typed_io.config.config_encode import config_encoder

sys.path.insert(0, os.path.dirname(__file__))
from custom_types import *

logging.basicConfig(level=logging.INFO, stream=sys.stderr)


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
        [b"\x01\x02\x03", "01 02 03", bytearray([1, 2, 3]), [1, 2, 3], (1, 2, 3)],
    ),
    (
        bytearray,
        bytearray(b"\x01\x02\x03"),
        [b"\x01\x02\x03", "010203", bytearray([1, 2, 3]), [1, 2, 3], (1, 2, 3)],
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
    (ByteString, "01ff", b"\x01\xff", same_value),
    (List[bytes], ["01 ff", [1, 2, 3]], [b"\x01\xff", b"\x01\x02\x03"], same_contents),
    (
        MutableSet[bytes],
        ["ff", [1, 2, 3]],
        {b"\xff", b"\x01\x02\x03"},
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
                "{}.{}".format(_myint.__module__, _myint.__name__),
                "{}.{}".format(_mystr.__module__, _mystr.__name__),
            ],
        },
        {sorted: (int, str), ord: (_myint, _mystr)},
        same_keyvals,
    ),
    (
        Callable[[Any], SomeEnum],
        "{}.{}".format(SomeEnum.__module__, SomeEnum.__name__),
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
