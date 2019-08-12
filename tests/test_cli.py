from io import StringIO
from logging import getLogger
from pathlib import Path
import sys

import pytest

from bourbaki.application.config import load_config
from bourbaki.application.logging import ProgressLogger
from bourbaki.application.typed_io.utils import *
from bourbaki.application.typed_io.cli_repr_ import bool_cli_repr
from bourbaki.application.typed_io.parsers import EnumParser

DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(DIR))
from cli import cli, MyCommandLineApp, FooEnum

CONFIG_FILE = str(DIR / "conf.yml")

CONFIG = {'__init__':
              {'a': 1, 'b': [1, 2, 3], 'c': None, 'pretty': False, 'outfile': None, 'literal': False},
          'print': {'pretty': False, 'outfile': None, 'literal': False},
          'tuple_kwarg': {'tup': [type_spec(int), type_spec(str), type_spec(float)],
                          'pretty': False, 'outfile': None, 'literal': False},
          'tuple_union_kwarg': {'tup': [[type_spec(int), type_spec(str)], 'OR', [type_spec(str), type_spec(bool)]],
                                'pretty': False, 'outfile': None, 'literal': False},
          'args_and_kwargs': {'ips': [ipv6_repr, '...'],
                              'pretty': False, 'outfile': None, 'literal': False,
                              'named_ips': {type_spec(str): ipv4_repr, ellipsis_: ellipsis_}},
          'enum': {'foo': None, 'pretty': False, 'outfile': None, 'literal': False},
          'bytes': {'b': [byte_repr, ellipsis_],
                    'pretty': False, 'outfile': None, 'literal': False},
          'flags': {'boolean1': bool_cli_repr, 'boolean2': False,
                    'flag1': False, 'flag2': True},
          'args': {'args': [EnumParser(FooEnum).config_repr(), ellipsis_],
                   'pretty': False, 'outfile': None, 'literal': False},
          }
COMMANDS = ['--only-commands', *(n.replace('_', '-') for n in CONFIG if not n.startswith('__'))]


def test_command_names():
    assert set(cli.subcommands) == set(n.replace('_', '-') for n, v in MyCommandLineApp.__dict__.items()
                                       if callable(v) and not n.startswith('this') and not n.startswith('_'))


# TODO: more tests
@pytest.mark.parametrize("args, result, config_format", [
    (['--config', CONFIG_FILE], None, None),
    (['--config', CONFIG_FILE, 'print'], {'a': 1, 'b': [1, 2, 3], 'c': datetime.date.today()}, None),
    (['init-config', '--format', 'yaml', *COMMANDS], CONFIG, '.yaml'),
    (['init-config', '--format', 'json', *COMMANDS], CONFIG, '.json'),
    (['--config', CONFIG_FILE, 'tuple-kwarg'], (12345678, "a_string", 1234.5678), None),
    (['tuple-kwarg', '--tup', '123', '456', '7.89'], (123, '456', 7.89), None)
])
def test_cli_result(args, result, config_format, capsys):
    cli_result = cli.run(args)
    assert cli_result == result
    if config_format:
        out = capsys.readouterr().out
        parsed = load_config(StringIO(out), ext=config_format)
        assert parsed == result
