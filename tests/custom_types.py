# coding:utf-8
import logging
import sys
from pathlib import PosixPath, Path
from datetime import date, datetime
from fractions import Fraction
from decimal import Decimal
from uuid import UUID, uuid4
from typing import (
    Optional,
    NamedTuple,
    Set,
    Generic,
    TypeVar,
)
from enum import Enum, Flag

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
    print(value, type_)
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


__all__ = list(name for name in globals() if not name.startswith("__"))
