# coding:utf-8
from functools import partial
from typing import AnyStr, Callable, TextIO, Union, Any
from ..cli.cli_parse import cli_parser
from ..cli.cli_nargs_ import cli_nargs
from ..env.env_parse import lex_env_var
from ...config import ConfigFormat, load_config

StdinParser = Callable[[TextIO], Any]


class stdin_parser:
    def __init__(self, type_):
        """Parser for value of type type_ from standard input. Lexing depends on cli_nargs(type_) and cli_nargs of
        the first generic type variable of type_ in the case of nested collections. cli_parser(type_) is then called
        on the lexed result."""
        self.cli_nargs = cli_nargs(type_)
        self.nested_collection = is_nested_collection(type_)
        self.parser = cli_parser(type_)

    def __call__(self, text: Union[TextIO, AnyStr]):
        if not isinstance(text, str):
            if not isinstance(text, bytes):
                text = text.read()
                if isinstance(text, bytes):
                    text = text.decode()
            else:
                text = text.decode()

        if self.nested_collection:
            # split lines and lex each line
            return self.parser(list(map(lex_env_var, text.splitlines())))
        elif self.cli_nargs is None:
            # just parse the whole thing as a string (removing trailing endlines)
            return self.parser(text.rstrip("\r\n"))
        elif isinstance(self.cli_nargs, int):
            # lex the input for tuple types - this will work for both line breaks and other whitespace
            # as in a columnar format
            return self.parser(lex_env_var(text))
        else:
            # basic collection type; split lines
            return self.parser(text.splitlines())


def to_stdin_parser(parser_or_format: Union[ConfigFormat, StdinParser]) -> StdinParser:
    if isinstance(parser_or_format, str):
        parser = partial(load_config, ext=ConfigFormat(parser_or_format))
    elif isinstance(parser_or_format, ConfigFormat):
        parser = partial(load_config, ext=ConfigFormat.value)
    elif callable(parser_or_format):
        parser = parser_or_format
    else:
        raise TypeError(
            "parser_or_format must be a callable or an instance of {}.{}; got {}".format(
                ConfigFormat.__module__, ConfigFormat.__name__, type(parser_or_format)
            )
        )

    return parser
