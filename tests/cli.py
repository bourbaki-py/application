#!/usr/bin/env python
import time
tic = time.time()
from typing import *
import datetime
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from numbers import Number
from pathlib import Path
from urllib.parse import ParseResult as URL
from uuid import UUID, uuid4
import ipaddress
from pprint import pprint
from bourbaki.application.logging import Logged
from bourbaki.application.cli import CommandLineInterface, cli_spec, File, CLI, ENV, CONFIG
toc = time.time()
print("Import time: {}s".format(round(toc - tic, 3)))

Num = TypeVar("Num", bound=Number)


class FooEnum(Enum):
    foo = "foo"
    bar = "bar"
    baz = "baz"


class FooTuple(NamedTuple):
    foo: FooEnum
    bar: Path
    baz: datetime.date


def pprint_(value, outfile: Optional[File['w']] = None, *, pretty: bool = False, literal: bool = False):
    """
    print value to a file, if specified, else stdout

    :param value: the value to print
    :param outfile: the file to print the return value to
    :param pretty: use pretty-printing
    :param literal: print the python literal of the value
    :return: the passed value
    """
    if pretty:
        pprint(value, stream=outfile)
    else:
        if literal:
            value = repr(value)
        print(value, file=outfile)


cli = CommandLineInterface(
    prog="cli.py",
    use_verbose_flag=True,
    add_init_config_command=('init', 'config'),
    require_keyword_args=False,
    use_config_file=True,
    require_subcommand=False,
    implicit_flags=True,
    allow_abbrev=True,
    default_metavars=dict(outfile='OUTFILE'),
    source_file=__file__,
    package='bourbaki.application',
    output_handler=pprint_,
    arg_lookup_order=(CLI, CONFIG, ENV),
    package_info_keys=('version', 'license', 'summary', 'platforms'),
    suppress_setup_warnings=True,
)


class MyCommandLineApp(Generic[Num], Logged):
    """
    a simple cli.
    prints args that were passed from the command line, for various types of args.

    You can also add lots of extensive documentation down here.
    """
    @cli_spec.config_subsection("__main__")
    def __init__(self, a: Num = 1, b: List[Num] = [1, 2, 3], c: Optional[datetime.date] = None):
        """
        :param a: an number called a
        :param b: a list of numbers called b
        :param c: a datetime called c
        """
        if c is None:
            c = datetime.date.today()
        self.a = a
        self.b = b
        self.c = c

    @cli_spec.command_prefix("print")
    def print_ns(self):
        """
        print the parsed args

        prints all of the args that were passed to main

        :return:
        """
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

    @cli_spec.ignore_on_cmd_line("cant_parse_me")
    @cli_spec.command_prefix("cant")
    def cant_parse(self, can_parse_me: List[str], cant_parse_me: Optional[List[List[str]]] = None):
        print("cant_parse_me:", cant_parse_me or [])
        return can_parse_me

    @cli_spec.command_prefix("print", "tuple")
    def tuple_kwarg(self, *, tup: Tuple[int, Num, float]):
        """
        print a tuple

        print all the entries in a tuple that was passed
        :param tup: a tuple of three things
        :return:
        """
        return tup

    @cli_spec.command_prefix("print")
    @cli_spec.require_keyword_args
    def print_named_tuple(self, tup: FooTuple = FooTuple(FooEnum.foo, Path("."), datetime.date.today())):
        """
        print an instance of a namedtuple
        :param tup: a namedtuple class with 3 fields of mixed type
        :return:
        """
        return tup

    @cli_spec.command_prefix("print", "tuple")
    def tuple_pos(self, tup: Tuple[int, Num, float]):
        """
        print a tuple

        print all the entries in a tuple that was passed
        :param tup: a tuple of three things
        :return:
        """
        return tup

    @cli_spec.command_prefix("print", "tuple")
    def tuple_union_kwarg(self, *, tup: Union[Tuple[Num, str], Tuple[str, bool]]):
        """
        print one of two kinds of tuple

        one is (int, str) the other is (str, bool)
        :param tup: either a tuple of int, str or a tuple of str, bool
        :return:
        """
        return tup

    def args_and_kwargs(self, *ips: ipaddress.IPv6Address, **named_ips: ipaddress.IPv4Address):
        """
        print some named ipv4 addresses

        and also a list of anonymous ipv6 addresses

        :param ips: list of ip addresses
        :param named_ips: mapping of name -> ipv6 address
        :return:
        """
        return ips, named_ips

    @cli_spec.command_prefix("leading")
    def leading_list(self, l_1: List[float], i_2: int):
        """
        demonstrates that positional variable-length args can be safely handled as the last arg of a command
        and that arg names with underscores are fine

        :param l_1: a list of floats
        :param i_2: a single int
        :return:
        """
        return l_1, i_2

    @cli_spec.command_prefix("print")
    def enum(self, foo: Optional[FooEnum] = None):
        """
        print an enum

        :param foo: a FooEnum
        """
        return foo

    @cli_spec.command_prefix("print")
    def uuid(self, uuid: Optional[UUID]=None):
        """
        print a UUID; if one isn't passed, generate one
        :param uuid: optional UUID
        :return:
        """
        return uuid or uuid4()

    @cli_spec.command_prefix("print")
    def numbers(self, x: Optional[Decimal] = None, y: Optional[Fraction] = None, z: Optional[complex] = None):
        """
        print varying numeric types of data
        :param x: an arbitrary-precision decimal
        :param y: a fraction
        :param z: a complex number
        :return:
        """
        return x, y, z

    @cli_spec.command_prefix("print")
    @cli_spec.parse_config_as_cli('b')
    def bytes(self, b: bytes):
        """
        print some bytes
        :param b: some bytes
        :return: b
        """
        return b

    @cli_spec.command_prefix("print")
    def url(self, url: URL):
        """
        print a URL
        :param url: any standards-compliant URL
        :return:
        """
        return url

    @cli_spec.command_prefix("print")
    def mapping(self, foo_to_date: Mapping[FooEnum, datetime.date]):
        """
        print a complex mapping
        :param foo_to_date: a mapping of FooEnum to dates
        :return:
        """
        return foo_to_date

    @cli_spec.command_prefix("print")
    @cli_spec.no_output_handler
    @cli_spec.parse_config_as_cli('boolean1')
    def flags(self, boolean1: bool = False, boolean2: bool = False, *, flag1: bool = False, flag2: bool = True):
        """
        print some boolean flags
        :param flag1: a flag which is False by default
        :param flag2: a flag which is True by default
        :return:
        """
        print("boolean1:", boolean1)
        print("boolean2:", boolean2)
        print("flag1:", flag1)
        print("flag2:", flag2)
        return boolean1, boolean2, flag1, flag2

    def types(self, number: Type[Num], **types: Type[Mapping]):
        """
        Inflate python types from classpaths
        :param types: a bunch of python types
        :param number: a python numeric type
        :return:
        """
        return number, types

    @cli_spec.command_prefix("get")
    def get_attr(self, attr: str):
        """
        Return an attribute of this app class instance
        :param attr: name of the attribute
        :return:
        """
        return getattr(self, attr)

    @cli_spec.require_output_keyword_args
    def args(self, *args: FooEnum):
        """
        Print positional *args from the command line
        :param args:
        :return:
        """
        return args

    @classmethod
    def this_is_not_a_command(cls):
        pass

    @staticmethod
    def this_is_also_not_a_command():
        pass

    def _this_is_also_not_a_command(self):
        pass


cli.definition(MyCommandLineApp[Union[int, float, complex, Fraction]])


if __name__ == "__main__":
    tic = time.time()
    print("Setup time: {}s".format(round(tic - toc, 3)))
    cli.run()
