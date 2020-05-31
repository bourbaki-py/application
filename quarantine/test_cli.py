from io import StringIO
from fractions import Fraction
from itertools import cycle
from operator import itemgetter
from pathlib import Path
import pickle
from random import choices

from cytoolz import assoc, groupby, valmap
import pytest

from bourbaki.application.config import load_config
from bourbaki.application.cli.main import OPTIONAL_ARG_TEMPLATE
from bourbaki.application.typed_io.utils import *
from bourbaki.application.typed_io.cli_repr_ import bool_cli_repr
from bourbaki.introspection.callables import is_classmethod, is_staticmethod

DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(DIR))
from cli import cli, MyCommandLineApp, FooEnum


def maybe(key):
    return OPTIONAL_ARG_TEMPLATE.format(key)


output_args = {"pretty": False, "literal": False, maybe("outfile"): text_path_repr}

fooenum_repr = "|".join(v.name for v in FooEnum)

today = datetime.date.today().isoformat()

CONFIG_FILE = str(DIR / "conf.yml")

CONFIG = {
    "__init__": {"a": 1, "b": [1, 2, 3], maybe("c"): date_repr},
    "print": {
        "ns": {**output_args},
        "tuple": {
            "kwarg": {
                "tup": [
                    type_spec(int),
                    type_spec(int) + " OR " + fraction_repr,
                    type_spec(float),
                ],
                **output_args,
            },
            "pos": {
                "tup": [
                    type_spec(int),
                    type_spec(int) + " OR " + fraction_repr,
                    type_spec(float),
                ],
                **output_args,
            },
            "union-kwarg": {
                "tup": [
                    [type_spec(int) + " OR " + fraction_repr, type_spec(str)],
                    "OR",
                    [type_spec(str), type_spec(bool)],
                ],
                **output_args,
            },
        },
        "enum": {maybe("foo"): fooenum_repr, **output_args},
        "bytes": {"b": [byte_repr, ellipsis_], **output_args},
        "flags": {
            "boolean1": bool_cli_repr,
            "boolean2": False,
            "flag1": False,
            "flag2": True,
        },
        "mapping": {
            "foo_to_date": {fooenum_repr: date_repr, ellipsis_: ellipsis_},
            **output_args,
        },
        "named-tuple": {
            "tup": {"foo": FooEnum.foo.name, "bar": ".", "baz": today},
            **output_args,
        },
        "numbers": {
            maybe("x"): decimal_repr,
            maybe("y"): fraction_repr,
            maybe("z"): complex_repr,
            **output_args,
        },
        "url": {"url": url_repr, **output_args},
        "uuid": {maybe("uuid"): uuid_repr, **output_args},
    },
    "args": {"args": [fooenum_repr, ellipsis_], **output_args},
    "args-and-kwargs": {
        "ips": [ipv6_repr, "..."],
        **output_args,
        "named_ips": {type_spec(str): ipv4_repr, ellipsis_: ellipsis_},
    },
    "types": {
        "number": classpath_type_repr + "<:Union[int,fractions.Fraction]",
        **output_args,
        "types": {
            type_spec(str): classpath_type_repr + "<:Mapping",
            ellipsis_: ellipsis_,
        },
    },
    "leading": {
        "list": {"l_1": [float_repr, ellipsis_], "i_2": int_repr, **output_args}
    },
    "cant": {
        "parse": {
            maybe("cant_parse_me"): [[type_spec(str), ellipsis_], ellipsis_],
            "can_parse_me": [type_spec(str), ellipsis_],
            **output_args,
        }
    },
    "get": {"attr": {"attr": type_spec(str), **output_args}},
}


def keys_recursive(dict_: dict):
    def inner(dict_, prefix):
        recurse = all(isinstance(v, dict) for v in dict_.values())
        if recurse:
            for k, v in dict_.items():
                yield from inner(v, (*prefix, k))
        else:
            yield prefix

    return list(t for t in inner(dict_, ()) if not t[0].startswith("__"))


def getrecursive(dict_, keys):
    if not any(keys):
        return dict_
    head_to_tails = valmap(
        lambda l: [t[1:] for t in l], groupby(itemgetter(0), filter(len, keys))
    )
    return {
        head: getrecursive(dict_[head], tails) for head, tails in head_to_tails.items()
    }


COMMANDS = keys_recursive(CONFIG)

RANDOM_COMMANDS = [set(choices(COMMANDS, k=3)) for _ in range(10)]

fmts = ["py", "yaml", "json"]


def test_command_names():
    fns = (
        getattr(v, "__command_prefix__", (n.replace("_", "-"),))[0]
        for n, v in MyCommandLineApp.__dict__.items()
        if callable(v)
        and not n.startswith("_")
        and not is_classmethod(MyCommandLineApp, n)
        and not is_staticmethod(MyCommandLineApp, n)
    )
    assert set(cli.subcommands) == set(fns).union(["init"])


# TODO: more tests
@pytest.mark.parametrize(
    "args, result, config_format",
    [
        (
            ["--config", CONFIG_FILE, "print", "ns"],
            {"a": 1, "b": [1, 2, 3], "c": datetime.date.today()},
            None,
        ),
        (
            ["--config", CONFIG_FILE, "print", "tuple", "kwarg"],
            (12345678, Fraction(1234, 5678), 1234.5678),
            None,
        ),
        (
            ["print", "tuple", "kwarg", "--tup", "123", "456", "7.89"],
            (123, 456, 7.89),
            None,
        ),
        *[(["init", "config", "--format", fmt], CONFIG, "." + fmt) for fmt in fmts],
        *[
            (
                [
                    "init",
                    "config",
                    "--format",
                    fmt,
                    "--only-commands",
                    *map(" ".join, cmds),
                ],
                assoc(getrecursive(CONFIG, cmds), "__init__", CONFIG["__init__"]),
                "." + fmt,
            )
            for cmds, fmt in zip(RANDOM_COMMANDS, cycle(fmts))
        ],
    ],
)
def test_cli_result(args, result, config_format, capsys):
    cli_result = cli.run(args)
    assert cli_result == result
    if config_format:
        out = capsys.readouterr().out
        parsed = load_config(StringIO(out), ext=config_format)
        assert parsed == result


@pytest.mark.parametrize(
    "args,exc",
    [
        (["--install-bash-completion"], SystemExit),
        (["--version"], SystemExit),
        (["--info"], SystemExit),
        (["--execute", "print", "ns"], None),
    ],
)
def test_cli_special_actions(args, exc):
    if exc is None:
        cli.run(args)
    else:
        with pytest.raises(exc):
            cli.run(args)


def test_cli_parses_env(monkeypatch):
    monkeypatch.setenv("CLI_ARG_B", "\"1/2\" 34 '56'")
    ns = cli.run(["print", "ns"])
    assert ns["b"] == [Fraction(1, 2), 34, 56]
    monkeypatch.delenv("CLI_ARG_B")
