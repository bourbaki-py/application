# coding:utf-8
"""
Configure bash completions for argparse-based command line interfaces
Note: the full functioning of this module requires installation of [bash-completion](https://github.com/scop/bash-completion)
In turn, `bash-completion` assumes that GNU versions of common command line utilities are installed, so if you are using
a Mac OS, you will need to install these as well, using homebrew (`bash-completion` itself is also available via homebrew)
The minimal set set of dependencies can be installed via:
$ brew install bash-completion
$ brew install gnu-sed --with-default-names
$ brew install gnu-which --with-default-names
$ brew install grep --with-default-names
$ brew install findutils --with-default-names
$ brew install coreutils
$ brew install awk

You will also need to add the following line to your ~/.bash_profile:
$ [ -f /usr/local/etc/bash_completion ] && . /usr/local/etc/bash_completion
See the linked repository for `bash-completion` more detailed installation instructions for all operating systems.

>>> from argparse import ArgumentParser
>>> parser = ArgumentParser()
>>> # define parser arguments
>>> ...
>>> from bourbaki.application.completion import install_shell_completion
>>> install_shell_completion(parser, "command_for_script", "other_command_for_script", ...)

Or, if your parser is an `bourbaki.application.CommandLineInterface`, just
>>> parser.install_shell_completion()
In that case, you may optionally supply command names; otherwise they are inferred from the `prog` arg to
the constructor as in `argparse.ArgumentParser` (an error is thrown if no `prog` is passed)
"""

from .compgen_python_classpaths import COMPLETION_DEBUG_ENV_VAR
from .completers import install_shell_completion
from .completers import (
    Complete,
    RawShellFunctionComplete,
    FixedShellFunctionComplete,
    BashCompletion,
)
