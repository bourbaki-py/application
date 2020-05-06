from itertools import chain
import os
from pathlib import Path
from typing import List, Iterable

from bourbaki.application.cli import CommandLineInterface


cli = CommandLineInterface(
    require_subcommand=True,
    implicit_flags=True,
    use_config_file=True,
)


@cli.definition
class CommonCommands:
    def ls(self, *dirs: Path) -> Iterable[Path]:
        if not dirs:
            return Path(".").iterdir()
        else:
            return chain.from_iterable(dir_.iterdir() for dir_ in dirs)

    def


def print_iterable(it: Iterable):
    for i in it:
        print(i)


if __name__ == "__main__":
    cli.run()
