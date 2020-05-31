# coding:utf-8
from inspect import signature
from pprint import pformat
import shutil
from textwrap import indent, wrap
from bourbaki.introspection.types import eval_type_tree, concretize_typevars
from bourbaki.introspection.classes import classpath, parameterized_classpath

STACKTRACE_VALUE_LITERAL_MAX_LINES = 7
STACKTRACE_VALUE_LITERAL_MAX_DEPTH = 1
STACKTRACE_VALUE_LITERAL_INDENT = 1
# this will allow reported errors for nested structures of up to 6 indentation levels
# before terminal text wrapping occurs
STACKTRACE_LEVEL_INDENT = 2
TERMINAL_WIDTH = shutil.get_terminal_size().columns
STACKTRACE_VALUE_LITERAL_WIDTH = TERMINAL_WIDTH - 6 * STACKTRACE_LEVEL_INDENT


def linewrap(msg: str):
    return "\n".join(wrap(msg, TERMINAL_WIDTH))


def pretty_repr(obj):
    """For representing value literals in exception strings upon I/O encode/decode error"""
    s = pformat(
        obj,
        indent=STACKTRACE_VALUE_LITERAL_INDENT,
        depth=STACKTRACE_VALUE_LITERAL_MAX_DEPTH,
        compact=False,
    )
    if s.count("\n") >= STACKTRACE_VALUE_LITERAL_MAX_LINES:
        lines = s.splitlines()
        nlines = STACKTRACE_VALUE_LITERAL_MAX_LINES // 2
        prefix = " " * STACKTRACE_VALUE_LITERAL_INDENT
        newlines = (
            lines[:nlines]
            + [prefix + "    ...", prefix + "<TRUNCATED>", prefix + "    ..."]
            + lines[-nlines:]
        )
        s = "\n".join(newlines)
    return s


class BourbakiTypedIOException(Exception):
    """Base exception class of all bourbaki typed I/O exceptions.
    repr method formats as `ExceptionName('message')`"""

    _type = None

    @property
    def type_(self):
        return concretize_typevars(eval_type_tree(self._type))

    def __repr__(self):
        return "{}({})".format(type(self).__name__, repr(str(self)))


class TypedIOTypeError(TypeError, BourbakiTypedIOException):
    """Base type error class for all 'compile-time' bourbaki typed I/O exceptions;
    e.g. for unparseable types"""

    def __init__(self, type_):
        super().__init__(type_)
        self._type = type_


class TypedIOValueError(ValueError, BourbakiTypedIOException):
    """Base type error class for all 'runtime' bourbaki typed I/O exceptions;
    e.g. parse errors for specific input values"""

    source = None
    method = None
    # the msg must define these fields for formatting
    msg = "{value_type} {source} {method} {type}"

    def __init__(self, type_, value, exc=None):
        super().__init__(type_, value)
        self._type = type_
        self.value = value
        self.exc = exc

    def __str__(self):
        msg = "\n".join(
            wrap(
                self.msg.format(
                    type=parameterized_classpath(self.type_),
                    source=self.source,
                    method=self.method,
                    value_type=classpath(type(self.value)),
                ),
                TERMINAL_WIDTH,
            )
        )
        msg = "{}\n{}".format(
            msg, indent(pretty_repr(self.value), " " * STACKTRACE_LEVEL_INDENT)
        )
        if self.exc is None:
            return msg
        return "{}\nRaised:\n{!s}".format(
            msg, indent(str(self.exc), " " * STACKTRACE_LEVEL_INDENT)
        )


###############################################
# 'compile-time' errors for unparseable types #
###############################################


class IOUndefinedForType(TypedIOTypeError):
    source = None
    values = "values"
    msg = "{source} I/O is not defined for {values} of type {type}; use {methods} to register custom {functions}"
    addendum = ""
    methods = []
    functions = []

    def __str__(self):
        methods = "/".join(self.methods) + ".register"
        functions = "/".join(self.functions)
        msg = (self.msg + " " + self.addendum).format(
            source=self.source, type=self.type_, methods=methods, functions=functions
        )
        return linewrap(msg)


class ConfigIOUndefinedForType(IOUndefinedForType):
    source = "configuration file"
    methods = ["config_encoder", "config_decoder", "config_repr"]
    functions = [
        "encoder",
        "decoder",
        "type-representer (for generating config templates)",
    ]
    addendum = "for parsing and encoding values of type {type} to configuration values (JSON-like)"


class ConfigIOUndefinedForKeyType(ConfigIOUndefinedForType):
    values = "mapping keys"
    methods = ["config_key_encoder", "config_key_decoder", "config_key_repr"]
    addendum = "for parsing and encoding mapping keys of type {type} to configuration keys (generally, strings)"


class CLIIOUndefinedForType(IOUndefinedForType):
    source = "command line"
    methods = ["cli_parser", "cli_repr", "cli_completer"]
    functions = [
        "parser",
        "type-representer (for generating help strings)",
        "completer (see bourbaki.application.completion for completers)",
    ]
    addendum = "for parsing and completing user input for values of type {type}"


class EnvIOUndefinedForType(IOUndefinedForType):
    source = "environment variable"
    methods = ["env_parser"]
    functions = ["parser"]
    addendum = "for parsing environment variables to values of type {type}"


class StdinIOUndefinedForType(IOUndefinedForType):
    source = "stdin"
    methods = ["stdin_parser"]
    functions = ["parser"]
    addendum = "for parsing standard input to values of type {type}"


#############################################################
# 'runtime' errors, i.e. unparseable/unrepresentable values #
#############################################################


class TypedInputError(TypedIOValueError):
    msg = "Can't parse value (type {value_type}) from {source} using {method}({type}):"


class TypedOutputError(TypedIOValueError):
    msg = "Can't encode value (type {value_type}) to {source} using {method}({type}):"


# For Union parser/encoders


class AllFailed(ValueError):
    def __str__(self):
        return "\n\n".join(map(str, self.args))


class RaisedDisallowedExceptions(ValueError):
    def __str__(self):
        return "\n\n".join(map(str, self.args))


# Config


class ConfigTypedInputError(TypedInputError):
    source = "configuration file"
    method = "config_decoder"


class ConfigCallableInputError(ConfigTypedInputError):
    def __str__(self):
        msg = super().__str__()
        try:
            sig = signature(self.value)
        except ValueError:
            return msg
        else:
            return msg + "; signature of parsed input is {}".format(sig)


class ConfigTypedOutputError(TypedOutputError):
    source = "configuration file"
    method = "config_encoder"


class ConfigTypedKeyOutputError(ConfigTypedOutputError):
    source = "configuration mapping key"
    method = "config_key_encoder"


# CLI


class CLITypedInputError(TypedInputError):
    source = "command line"
    method = "cli_parser"


# Env


class EnvTypedInputError(TypedInputError):
    source = "environment variable"
    method = "env_parser"


# Stdin


class StdinTypedInputError(TypedInputError):
    source = "stdin"
    method = "stdin_parser"
