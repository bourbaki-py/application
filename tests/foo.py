#!/usr/bin/env python
import sys
from typing import *

from bourbaki.application.cli import CommandLineInterface, ArgSource, cli_spec

cli = CommandLineInterface(
    prog="foo.py", arg_lookup_order=(ArgSource.CLI, ArgSource.STDIN, ArgSource.DEFAULTS)
)


@cli.definition
class Foo:
    """command line interface called foo"""

    def __init__(self, x: int = 42, y: Optional[List[bool]] = None):
        """
        set it up

        :param x: an int
        :param y: a list of bools
        """
        self.x = x
        self.y = y

    @cli_spec.parse_stdin("opt")
    @cli_spec.stdin_parser(".py")
    def nested(
        self,
        tup: Tuple[Tuple[int, int], str, complex],
        opt: Optional[List[Set[int]]] = None,
    ):
        """read and print nested types
        :param tup: crazy nested tuple
        :param opt: nested list of sets
        :return:
        """
        print(tup, file=sys.stderr)
        print(opt)


if __name__ == "__main__":
    cli.run()
