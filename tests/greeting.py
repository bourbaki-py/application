#!/usr/bin/env python
from datetime import datetime
from enum import Enum, IntEnum
import operator
import sys
from typing import *

from bourbaki.application.cli import CommandLineInterface, ArgSource, File, cli_spec
from bourbaki.application.completion import BashCompletion
from bourbaki.application.typed_io import cli_completer, cli_repr

Name = NewType("Name", str)

cli_completer.register(Name)(BashCompletion.usergroup)
cli_repr.register(Name, as_const=True)("NAME")


class Descriptor(Enum):
    Pythonista = "python enthusiast"
    Haskeller = "functional purist"
    Rustacean = "bare metal admirer"


class Person(NamedTuple):
    name: Name
    birthdate: datetime
    desc: Descriptor


class TimeUnit(IntEnum):
    seconds = 1
    minutes = 60
    hours = 60 * 60
    days = 24 * 60 * 60
    weeks = 7 * 24 * 60 * 60


def write_to_file(response, *, outfile: File['w'] = sys.stdout, literal: bool=False):
    """
    Write the response to a file
    :param response: The response to write
    :param outfile: The file to write the result to
    :param literal: Use literal representation (as opposed to str representation)
    """
    if literal:
        print(repr(response), file=outfile)
    else:
        print(response, file=outfile)


def oxford_comma(tokens):
    tokens = list(tokens)
    if len(tokens) > 2:
        last = tokens.pop()
        penultimate = tokens.pop()
        tokens.append("{}, and {}".format(penultimate, last))
    return tokens


cli = CommandLineInterface(
    prog="greeting.py",
    source_file=__file__,
    require_options=False,
    require_subcommand=True,
    use_verbose_flag=True,
    add_init_config_command=True,
    output_handler=write_to_file,
    arg_lookup_order=(ArgSource.CLI, ArgSource.ENV, ArgSource.CONFIG),
    implicit_flags=True,
)


@cli.definition
class Greeting:
    """
    CLI for saying hello 👋
    """
    def __init__(self, person: Person):
        """
        Args:
           person: a tuple of name, birthdate, and descriptor
        """
        self.person = person

    @cli_spec.command_prefix("greet")
    def greet_self(self, greeting: str):
        """
        Greet yourself!
        :param greeting: The greeting to use
        :return: The resulting greeting
        """
        return "{}, {}! I see that you're a fellow {}".format(greeting, self.person.name, self.person.desc.value)

    def hello(self):
        """
        Greet oneself with a hello! 😃
        :return: The greeting
        """
        return self.greet("Hello")

    @cli_spec.command_prefix("greet")
    def greet_friends(self, greeting: str, *friends: Name):
        """
        Greet some friends

        Args:
            greeting: The greeting to use
            friends: The friends to greet
        """
        return "{}, {}!".format(greeting, ", ".join(oxford_comma(list(friends))))

    @cli_spec.command_prefix("apply")
    def apply_funcs(self, name_func: Callable[[str], Any], birthday_func: Callable[[datetime], Any]):
        """
        Apply some functions to one's attributes

        :param name_func: Funtion to apply to one's name
        :param birthday_func: Function to apply to one's birthdate
        :return: The result of calling the functions
        """
        return name_func(self.person.name), birthday_func(self.person.birthdate)

    @cli_spec.command_prefix("when", "is", "my")
    def when_is_my_birthday(self, units: Set[TimeUnit] = {TimeUnit.days}):
        """
        Report on time remaining until one's own birthday

        :param units: Time units to report remaining time in; time will be reported in these units,
          sorted by size desceding
        :return: The message indicating how long until your birthday
        """
        today = datetime.now()
        bday = self.person.birthdate.replace(year=today.year)

        if bday < today:
            bday = bday.replace(year=bday.year + 1)

        remaining = (bday - today).total_seconds()
        tokens = []

        for unit in sorted(units, reverse=True):
            chunk = int(remaining // unit.value)
            remaining = remaining - chunk * unit.value
            tokens.append("{} {}".format(chunk, unit.name))

        return "Your birthday is in {}!".format(", ".join(oxford_comma(tokens)))


if __name__ == "__main__":
    cli.run()
