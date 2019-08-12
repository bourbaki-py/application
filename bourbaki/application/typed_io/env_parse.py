# coding:utf-8
from shlex import shlex
from .cli_parse import cli_parser
from .cli_nargs_ import cli_nargs


def unquote(s):
    for qchar in ('"', "'", '"""', "'''"):
        if s.startswith(qchar) and s.endswith(qchar):
            return s[1:-1]
    return s


def lex_env_var(s):
    return list(map(unquote, shlex(s)))


class env_parser:
    def __init__(self, type_):
        self.parser = cli_parser(type_)
        self.nargs = cli_nargs(type_)

    def __call__(self, env_var):
        if self.nargs is None:
            return self.parser(env_var)

        return self.parser(lex_env_var(env_var))
