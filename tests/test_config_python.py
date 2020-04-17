from bourbaki.application.config.python import (
    load_python,
    validate_python_config_source,
    IllegalFunctionInSourceConfig,
    IllegalNameInSourceConfig,
    IllegalExpressionInSourceConfig,
    PythonSourceConfigSyntaxError,
    PythonSourceConfigRuntimeError,
)
import io

import pytest


@pytest.mark.parametrize("source,value", [
    ("x=1; y=2", dict(x=1, y=2)),
    ("x = [i for i in range(10)]; y = sum(x)", dict(x=list(range(10)), y=sum(range(10)))),
    ("foobar=frozenset(zip(range(3), 'foo'))", dict(foobar=frozenset(zip(range(3), 'foo')))),
    ("dict(x=list('foo'))", dict(x=list("foo"))),
    ("x = 0; y = [x <= 1]", dict(x=0, y=[True])),
    ("{c for c in 'foobar'}", set("foobar")),
])
def test_load_python_equals(source, value):
    f = io.StringIO(source)
    assert load_python(f) == value


@pytest.mark.parametrize("source,exception", [
    ("dt = __import__('datetime')", IllegalFunctionInSourceConfig),
    ("file = open(anything)", IllegalFunctionInSourceConfig),
    ("mod = __module__", IllegalNameInSourceConfig),
    ("{x = 1}", PythonSourceConfigSyntaxError),
    ("x = 1; 1234", PythonSourceConfigSyntaxError),
    ("dict(x=list('foo')", PythonSourceConfigSyntaxError),
    ("{'fun': lambda foo: bar}", IllegalExpressionInSourceConfig),
    ("x=1; y=z", PythonSourceConfigRuntimeError),
    ("opener = __builtins__.open", IllegalNameInSourceConfig),
    ("x = os", PythonSourceConfigRuntimeError),
    ("dict.__new__()", IllegalFunctionInSourceConfig),
    ("def func(x=1, y=2): ...", PythonSourceConfigSyntaxError),
])
def test_load_python_raises(source, exception):
    f = io.StringIO(source)
    with pytest.raises(exception):
        _ = load_python(f)
    if not issubclass(exception, (PythonSourceConfigSyntaxError, PythonSourceConfigRuntimeError)):
        with pytest.raises(exception):
            _ = validate_python_config_source(source)
