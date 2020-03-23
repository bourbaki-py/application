# coding:utf-8
from inspect import signature
from textwrap import indent
from bourbaki.introspection.types import eval_type_tree, concretize_typevars


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

    def __init__(self, type_, value, exc=None):
        super().__init__(type_, value)
        self._type = type_
        self.value = value
        self.exc = exc


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
        methods = '/'.join(self.methods) + '.register'
        functions = '/'.join(self.functions)
        return (self.msg + ' ' + self.addendum).format(
            source=self.source, type=self.type_, methods=methods, functions=functions,
        )


class ConfigIOUndefinedForType(IOUndefinedForType):
    source = 'configuration file'
    methods = ['config_encoder', 'config_decoder', 'config_repr']
    functions = ['encoder', 'decoder', 'type-representer (for generating config templates)']
    addendum = "for parsing and encoding values of type {type} to configuration values (JSON-like)"


class ConfigIOUndefinedForKeyType(ConfigIOUndefinedForType):
    values = 'mapping keys'
    methods = ['config_key_encoder', 'config_key_decoder', 'config_key_repr']
    addendum = "for parsing and encoding mapping keys of type {type} to configuration keys (generally, strings)"


class CLIIOUndefinedForType(IOUndefinedForType):
    source = 'command line'
    methods = ['cli_parser', 'cli_repr', 'cli_completer']
    functions = [
        'parser',
        'type-representer (for generating help strings)',
        'completer (see bourbaki.application.completion for completers)'
    ]
    addendum = "for parsing and completing user input for values of type {type}"


class EnvIOUndefinedForType(IOUndefinedForType):
    source = 'environment variable'
    methods = ['env_parser']
    functions = ['parser']
    addendum = "for parsing environment variables to values of type {type}"


class StdinIOUndefinedForType(IOUndefinedForType):
    source = 'stdin'
    methods = ['stdin_parser']
    functions = ['parser']
    addendum = "for parsing standard input to values of type {type}"


#############################################################
# 'runtime' errors, i.e. unparseable/unrepresentable values #
#############################################################


class TypedInputError(TypedIOValueError):
    source = None
    method = None
    msg = "can't parse value of type {type} from {source} value {value!r} using {method}({type})"

    def __str__(self):
        msg = self.msg.format(type=self.type_, source=self.source, value=self.value, method=self.method)
        if self.exc is None:
            return msg
        return msg + ";\nraised:\n{!s}".format(indent(str(self.exc), '    '))


class TypedOutputError(TypedIOValueError):
    source = None
    method = None
    msg = "can't encode value {value!r} of type {value_type} to {source} using {method}({type})"

    def __str__(self):
        msg = self.msg.format(
            type=self.type_,
            source=self.source,
            value=self.value,
            method=self.method,
            value_type=type(self.value),
        )
        if self.exc is None:
            return msg
        return msg + ";\nraised:\n{!s}".format(indent(str(self.exc), '    '))


# For Union parser/encoders

class AllFailed(ValueError):
    def __str__(self):
        return '\n\n'.join(map(str, self.args))


class RaisedDisallowedExceptions(ValueError):
    def __str__(self):
        return '\n\n'.join(map(str, self.args))


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
