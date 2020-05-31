import os
from typing import TypeVar, Generic
from bourbaki.application.typed_io.config.inflation import (
    instance_from,
    ConfigTypedInputError,
    ConfigInflationError,
)
from bourbaki.introspection.typechecking import type_checker
import pytest

T_co = TypeVar("T_co", covariant=True)


class Class(Generic[T_co]):
    def __init__(self, x: str, y: T_co, *args: str, **kwargs: float):
        self.x = x
        self.y = y

    def __eq__(self, other):
        return type(self) is type(other) and self.x == other.x and self.y == other.y


class Subclass(Class[T_co]):
    pass


MODULE = os.path.splitext(os.path.basename(__file__))[0]
CLASSPATH = MODULE + "." + Class.__name__
SUBCLASSPATH = MODULE + "." + Subclass.__name__


# regiser this to allow typechecking below
@type_checker.register(Class)
def type_checker_for_class(cls, arg):
    def type_check(value, arg=arg):
        return isinstance(value, cls) and type_checker(arg)(value.y)

    return type_check


@pytest.mark.parametrize(
    "config_val,test_val,target_type",
    [
        # basic with positional args
        (dict(__classpath__=CLASSPATH, __args__=("1", 2)), Class("1", 2), Class),
        # with extra *args of correct type
        (
            dict(__classpath__=CLASSPATH, __args__=("1", 2, "three")),
            Class("1", 2),
            Class,
        ),
        # with **kwargs
        (
            dict(__classpath__=CLASSPATH, __kwargs__=dict(x="1", y=2)),
            Class("1", 2),
            Class,
        ),
        # with extra **kwargs of correct tpye
        (
            dict(__classpath__=CLASSPATH, __kwargs__=dict(x="1", y=2, z=1.23)),
            Class("1", 2),
            Class,
        ),
        # parameterized
        (
            dict(__classpath__=CLASSPATH + "[int]", __args__=("1", 2)),
            Class("1", 2),
            Class[int],
        ),
        (
            dict(__classpath__=CLASSPATH + "[str]", __args__=("1", "2")),
            Class("1", "2"),
            Class[str],
        ),
        # config-specified is subtype of target type
        (
            dict(__classpath__=SUBCLASSPATH + "[bool]", __kwargs__=dict(x="1", y=True)),
            Subclass("1", True),
            Class[int],
        ),
        # nested inflation - target is a supertype of the config-specified type and the arg is generic
        (
            dict(
                __classpath__=SUBCLASSPATH + "[{}[{}]]".format(SUBCLASSPATH, "str"),
                __kwargs__=dict(
                    x="1",
                    y=dict(__classpath__=SUBCLASSPATH + "[str]", __args__=("2", "3")),
                ),
            ),
            Subclass("1", Subclass("2", "3")),
            Class[Class[str]],
        ),
    ],
)
def test_config_inflation(config_val, test_val, target_type):
    parsed_val = instance_from(**config_val, target_type=target_type)
    assert parsed_val == test_val


@pytest.mark.parametrize(
    "config_val,target_type,exc_type,match",
    [
        # classpath to non-type
        (dict(__classpath__=MODULE + ".CLASSPATH"), Class, TypeError, "not a type"),
        # classpath to non-subtype
        (
            dict(__classpath__="int"),
            Class,
            TypeError,
            r"not\b[\s\w]* a generic subclass of .*\b" + CLASSPATH,
        ),
        # classpath to non-subtype with params
        (
            dict(__classpath__=CLASSPATH + "[str]"),
            Class[int],
            TypeError,
            r"not\b[\s\w]* a generic subclass of .*\b" + CLASSPATH + "\[int\]",
        ),
        # classpath is fine but parameterized arg is wrong type
        (
            dict(__classpath__=CLASSPATH + "[str]", __args__=("1", 2)),
            Class[str],
            ConfigInflationError,
            r"occurred for arg[\w]* y\b",
        ),
        # classpath is fine and parameterized arg is fine but non-parameterized arg is wrong type
        (
            dict(__classpath__=CLASSPATH + "[str]", __args__=(1, "2")),
            Class[str],
            ConfigInflationError,
            r"occurred for arg[\w]* x\b",
        ),
        # classpath and parameterized arg are fine but **kwargs are wrong type
        (
            dict(
                __classpath__=CLASSPATH + "[int]",
                __args__=("1", 2),
                __kwargs__={"z": "notfloat"},
            ),
            Class[int],
            ConfigInflationError,
            r"occurred for arg[\w]* \*\*kwargs\b",
        ),
        # classpath and parameterized arg are fine but *args are wrong type
        (
            dict(__classpath__=CLASSPATH + "[int]", __args__=("1", 2, 3, 4)),
            Class[int],
            ConfigInflationError,
            r"occurred for arg[\w]* \*args\b",
        ),
    ],
)
def test_config_inflation_raises(config_val, target_type, exc_type, match):
    with pytest.raises(exc_type, match=match):
        parsed_val = instance_from(**config_val, target_type=target_type)
