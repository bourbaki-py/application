#!/usr/bin/env python
from bourbaki.application.cli import CommandLineInterface, ArgSource
from typing import *

cli = CommandLineInterface(
    prog="foo.py", arg_lookup_order=(ArgSource.CLI, ArgSource.DEFAULTS)
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

    def wut(
        self,
        tup: Tuple[Tuple[int, int], str, Tuple[complex, ...]],
        opt: Optional[List[Set[int]]] = None,
    ):
        """
        wut to the wut
        :param tup: crazy nested tuple
        :param opt: nested lists
        :return:
        """
        print(tup)
        print(opt)


if __name__ == "__main__":
    cli.run()
