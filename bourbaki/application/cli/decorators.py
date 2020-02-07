# coding:utf-8
# decorators for functions defined in a class def context to override default behaviors for how they are configured
# as subcommands
from typing import Collection
from bourbaki.introspection.callables import funcname
from .helpers import _maybe_bool, _validate_parse_order

NO_OUTPUT_HANDLER = object()


class cli_spec:
    @staticmethod
    def allow_positional_args(f):
        """override the require_options setting of the wrapping CLI for the decorated function"""
        f.__allow_positional_args__ = True
        return f

    @staticmethod
    def require_options(f):
        f.__allow_positional_args__ = False
        return f

    @staticmethod
    def noncommand(f):
        """mark a function as not to be processed as a command for a CLI (usually a method in a class def)"""
        f.__noncommand__ = True
        return f

    @staticmethod
    def command_prefix(*prefix):
        """map a function to a nested command. The function name is tokenized, and any tokens from the _tail_ of the
        specified prefix that match those at the _head_ of the function name are only present once in the command path.
        Any remaining (tail) tokens in the function name are also present in the command path.

        The idea is to allow easy nesting of functions under shared command prefixes while yielding succint,
        interpretable command names.

        Example:
            >>> @cli_spec.command_prefix("do", "something")
            >>> def do_something_fast(*args):
            >>>     ...

            This will register `do_something_fast` under the command 'do something fast'

            >>> @cli_spec.command_prefix("do")
            >>> def do_something_fast(*args):
            >>>     ...

            This will register `do_something_fast` under the command 'do something-fast'
        """

        def dec(func):
            func.__command_prefix__ = prefix
            return func

        return dec

    @staticmethod
    def helpname(name):
        """decorator to apply a name to a function so that it prints in help strings on the command line with an
        appropriate name (usually the name of the return type)"""

        def dec(func):
            func.__helpname__ = name
            return func

        return dec

    @staticmethod
    def config_subsection(*section):
        def dec(func):
            section_ = _maybe_bool(section, fallback=tuple)
            func.__config_subsections__ = (
                section_ if isinstance(section_, bool) else [section_]
            )
            return func

        return dec

    @staticmethod
    def config_subsections(*sections):
        def dec(func):
            func.__config_subsections__ = [
                tuple(name) if isinstance(name, (list, tuple)) else (name,)
                for name in sections
            ]
            return func

        return dec

    @staticmethod
    def config_top_level(func):
        # get all args straight from the top level of the config hierarchy
        return cli_spec.config_subsection()(func)

    @staticmethod
    def ignore_in_config(*names):
        """mark argument names to be ignored in configuration files for the decorated function"""
        if len(names) == 1 and callable(names[0]):
            # bare decorator
            f = names[0]
            return cli_spec.config_subsection(False)(f)

        def dec(f):
            f.__ignore_in_config__ = _maybe_bool(names)
            return f

        return dec

    @staticmethod
    def parse_config_as_cli(*names):
        """mark argument names to be parsed from configuration files using the parsers applied on the command line"""

        def dec(f):
            f.__parse_config_as_cli__ = _maybe_bool(names)
            return f

        return dec

    @staticmethod
    def ignore_on_cmd_line(*names):
        """mark argument names to be ignored on the command line for the decorated function"""

        def dec(f):
            f.__ignore_on_cmd_line__ = _maybe_bool(names)
            return f

        return dec

    @staticmethod
    def parse_env(**argname_to_envname: str):
        """mark argument names to be parsed from corresponding environment variable names"""

        def dec(f):
            f.__parse_env__ = argname_to_envname
            return f

        return dec

    @staticmethod
    def parse_order(*names):
        """specify the order in which arguments are parsed, for example to allow failing early when some arguments are
        much more costly to parse than others"""

        def dec(f):
            f.__parse_order__ = _validate_parse_order(*names)
            return f

        return dec

    @staticmethod
    def typecheck(*names):
        """mark argument names to be type-checked for the decorated function, or check all arguments if True is passed"""

        def dec(f):
            f.__typecheck__ = _maybe_bool(names)
            return f

        return dec

    @staticmethod
    def metavars(**renames):
        """mark argument names with metavar names as they will appear in the CLI help string, using
        `@cli_spec.metavars(original_var_name=metavar_name, ...)` syntax"""

        def dec(f):
            f.__metavars__ = renames
            return f

        return dec

    @staticmethod
    def output_handler(func):
        """specify a callable to invoke for handling the return value of the decorated function, for example saving to
        disk. The return value is passed as the first argument and any further args will be supplied as keyword args
        parsed from the CLI or config.."""
        if func is None:
            func = NO_OUTPUT_HANDLER
        elif func is NO_OUTPUT_HANDLER:
            pass
        elif not callable(func):
            raise TypeError("func must be callable; got {}".format(type(func)))

        def dec(f):
            f.__output_handler__ = func
            return f

        return dec

    @staticmethod
    def no_output_handler(func):
        return cli_spec.output_handler(NO_OUTPUT_HANDLER)(func)

    @staticmethod
    def named_groups(**name_to_argnames: Collection[str]):
        def dec(f):
            f.__named_groups__ = {
                name.replace("_", " "): {argnames}
                if isinstance(argnames, str)
                else set(argnames)
                for name, argnames in name_to_argnames.items()
            }
            return f

        return dec


class cli_attrs:
    """retrieve properties set on functions by cli_spec methods"""

    @staticmethod
    def allow_positional_args(f, default=None):
        return getattr(f, "__allow_positional_args__", default)

    @staticmethod
    def require_options(f, default=None):
        if hasattr(f, "__allow_positional_args__"):
            return not cli_attrs.allow_positional_args(f)
        return default

    @staticmethod
    def noncommand(f):
        return getattr(f, "__noncommand__", False)

    @staticmethod
    def command_prefix(f, default=()):
        return getattr(f, "__command_prefix__", default)

    @staticmethod
    def helpname(f):
        return getattr(f, "__helpname__", funcname(f))

    @staticmethod
    def config_subsections(f, default=None):
        return getattr(f, "__config_subsections__", default)

    @staticmethod
    def config_top_level(f):
        return cli_attrs.config_subsections(f) == [()]

    @staticmethod
    def ignore_in_config(f, default=None):
        return getattr(f, "__ignore_in_config__", default)

    @staticmethod
    def parse_config_as_cli(f, default=None):
        return getattr(f, "__parse_config_as_cli__", default)

    @staticmethod
    def ignore_on_cmd_line(f, default=None):
        return getattr(f, "__ignore_on_cmd_line__", default)

    @staticmethod
    def parse_env(f, default=None):
        return getattr(f, "__parse_env__", default)

    @staticmethod
    def parse_order(f):
        return getattr(f, "__parse_order__", None)

    @staticmethod
    def typecheck(f, default=None):
        return getattr(f, "__typecheck__", default)

    @staticmethod
    def metavars(f, default=None):
        return getattr(f, "__metavars__", default)

    @staticmethod
    def output_handler(f, default=None):
        return getattr(f, "__output_handler__", default)

    @staticmethod
    def named_groups(f, default=None):
        return getattr(f, "__named_groups__", default)
