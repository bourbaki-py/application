from typing import *

import pytest

from bourbaki.application.typed_io.cli_nargs_ import is_nested_collection_for_cli


class FooTup(NamedTuple):
    x: int
    y: str


class FooTupNested(NamedTuple):
    x: complex
    y: FooTup


@pytest.mark.parametrize(
    "type_",
    [
        List[FooTup],
        Tuple[FooTup, ...],
        Set[FooTupNested],
        Tuple[FooTupNested, ...],
        Set[Tuple[int, List[bool]]],
        Set[FrozenSet[float]],
    ],
)
def test_is_nested_type_for_cli(type_):
    assert is_nested_collection_for_cli(type_)


@pytest.mark.parametrize(
    "type_",
    [FooTup, FooTupNested, Tuple[FooTup, FooTup], List[float], Set[int], FrozenSet],
)
def test_is_not_nested_type_for_cli(type_):
    assert not is_nested_collection_for_cli(type_)
