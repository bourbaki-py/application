# coding:utf-8
from typing import Union, Optional, TextIO, BinaryIO, IO
from argparse import FileType, ZERO_OR_MORE, ONE_OR_MORE, OPTIONAL
import io
import typing
import types
import datetime
import decimal
import encodings
import fractions
import ipaddress
import numbers
import pathlib
import sys
import uuid
from urllib.parse import ParseResult as URL
from functools import lru_cache, singledispatch
from inspect import Parameter
from multipledispatch import Dispatcher
from bourbaki.introspection.types import (
    deconstruct_generic,
    is_named_tuple_class,
    get_constructor_for,
    PseudoGenericMeta,
)
from bourbaki.introspection.typechecking import isinstance_generic
from bourbaki.introspection.docstrings import CallableDocs, ParamDocs, ParamDoc
from bourbaki.introspection.imports import import_object
from bourbaki.introspection.callables import function_classpath, UnStarred
from bourbaki.introspection.classes import classpath, parameterized_classpath
from bourbaki.introspection.generic_dispatch_helpers import PicklableWithType
from .exceptions import TypedInputError, TypedOutputError

Empty = Parameter.empty
Doc = Union[CallableDocs, ParamDocs, ParamDoc]

READ_MODES = {"r", "rb", "r+", "rb+", "a+", "ab+", "wb+"}
WRITE_MODES = {"w", "wb", "w+", "wb+", "a", "ab", "a+", "ab+", "rb+", "x", "xb"}
FILE_MODES = READ_MODES.union(WRITE_MODES)

NARGS_OPTIONS = (ZERO_OR_MORE, ONE_OR_MORE, OPTIONAL, None)
CLI_PREFIX_CHAR = "-"
KEY_VAL_JOIN_CHAR = "="


class _FileHandleConstructor(PseudoGenericMeta):
    @lru_cache(None)
    def __getitem__(cls, mode_enc) -> type:
        if isinstance(mode_enc, tuple):
            mode, encoding = mode_enc
        else:
            mode, encoding = mode_enc, None

        if cls.mode is not None or cls.encoding is not None:
            raise TypeError(
                "Can't subscript File more than once; tried to subscript {} with {}".format(
                    repr(cls), mode_enc
                )
            )
        mode, encoding, is_binary, base = _file_args(mode, encoding)
        new_cls = BinaryFile if is_binary else TextFile
        mcs = type(cls)
        return type.__new__(
            mcs,
            new_cls.__name__,
            (new_cls, base),
            dict(__args__=(mode, encoding), __origin__=File),
        )

    def __repr__(cls):
        tname = cls.__name__
        if cls.encoding:
            return "{}[{}, {}]".format(tname, repr(cls.mode), repr(cls.encoding))
        if cls.mode:
            return "{}[{}]".format(tname, repr(cls.mode))
        else:
            return tname

    @property
    def readable(cls):
        return cls.mode in READ_MODES

    @property
    def writable(cls):
        return cls.mode in WRITE_MODES

    @property
    def binary(cls):
        return "b" in cls.mode

    @property
    def mode(cls):
        if not cls.__args__:
            return None
        return cls.__args__[0]

    @property
    def encoding(cls):
        if not cls.__args__:
            return None
        return cls.__args__[1]

    def __instancecheck__(cls, instance):
        return isinstance(instance, cls.__bases__)


class File(metaclass=_FileHandleConstructor):
    encoding = None
    mode = None

    def __new__(cls, path) -> IO:
        # argparse.FileType has the nice feature of treating '-' as stdin/stdout and raising nice errors
        return FileType(cls.mode, encoding=cls.encoding)(path)


class TextFile(File):
    def __new__(cls, path) -> TextIO:
        return super().__new__(cls, path)


class BinaryFile(File):
    def __new__(cls, path) -> BinaryIO:
        return super().__new__(cls, path)


class PositionalMetavarFormatter:
    """Hack to deal with the fact that argparse doesn't allow tuples for positional arg metavars 
    (in contrast to the behavior for options)"""

    def __init__(self, *metavar: str, name: str):
        self.metavar = metavar
        self.name = name
        self._iter = iter(metavar * 2)

    def copy(self):
        return self.__class__(*self.metavar, name=self.name)

    def __getitem__(self, item):
        return self.metavar[item]

    def __str__(self):
        try:
            metavar = str(next(self._iter))
        except StopIteration:
            # for the help section
            s = self.name
        else:
            # for the usage line
            if self.name is None:
                s = metavar
            else:
                s = "{}-{}".format(self.name, metavar)

        return str(s)

    def __len__(self):
        return len(self.metavar)  # max(map(len, self.metavar))


def validate_nargs(nargs):
    if isinstance(nargs, int):
        if nargs > 0:
            return nargs
        raise ValueError("if an int, nargs must be positive; got {}".format(nargs))
    if nargs not in NARGS_OPTIONS:
        raise ValueError(
            "nargs must be a positive int or one of {}; got {}".format(
                NARGS_OPTIONS, nargs
            )
        )
    return nargs


def to_cmd_line_name(s: str, negative_flag=False):
    name = s.replace("_", "-").rstrip("-")
    if negative_flag:
        name = "no-" + name
    return name


def cmd_line_arg_names(name, positional=False, prefix_char=None, negative_flag=False):
    if not positional:
        if prefix_char is None:
            prefix_char = CLI_PREFIX_CHAR
        names = (
            (prefix_char * min(len(name), 2)) + to_cmd_line_name(name, negative_flag),
        )
    else:
        names = (name,)
    return names


def get_dest_name(args, prefix_chars):
    cs = prefix_chars
    try:
        dest = next(
            argname.lstrip(cs) for argname in args if len(argname.lstrip(cs)) > 1
        )
    except StopIteration:
        dest = args[0]
    return dest


@singledispatch
def to_str_cli_repr(repr_, n: Optional[int] = None):
    if n == ONE_OR_MORE:
        "{r} [{r} ...]".format(r=repr_)
    elif n == ZERO_OR_MORE:
        return "[{r} [{r} ...]]".format(r=repr_)
    elif n == OPTIONAL:
        return "[{}]".format(repr_)
    return repr_


@to_str_cli_repr.register(tuple)
@to_str_cli_repr.register(list)
def to_str_cli_repr_tuple(repr_, n):
    return " ".join(map(to_str_cli_repr, repr_))


def normalize_encoding(enc):
    if enc is None:
        return sys.getdefaultencoding()
    enc_ = encodings.search_function(enc)
    if not enc_:
        raise ValueError(
            "{} is not a valid text encoding; see encodings.aliases.aliases for the set of legal "
            "values".format(enc)
        )
    return enc_.name


def cached_property(method):
    """compute the getter once and store the result in the instance dict under the same name,
    so it isn't computed again"""
    attr = method.__name__

    def newmethod(self):
        value = method(self)
        self.__dict__[attr] = value
        return value

    return property(newmethod)


def normalize_file_mode(mode):
    if mode not in FILE_MODES:
        raise ValueError(
            "{} is not a valid file mode; choose one of {}".format(
                mode, tuple(FILE_MODES)
            )
        )
    return mode


def is_binary_mode(mode):
    return "b" in mode and mode in FILE_MODES


def is_write_mode(mode):
    return mode in WRITE_MODES


def is_read_mode(mode):
    return mode in READ_MODES


def _file_args(mode, encoding):
    mode = normalize_file_mode(mode)

    if is_binary_mode(mode):
        is_binary = True

        if encoding is not None:
            raise ValueError(
                "binary mode {} can't be specified with an encoding; got encoding={}".format(
                    repr(mode), repr(encoding)
                )
            )

        if is_read_mode(mode) and is_write_mode(mode):
            base = io.BufferedRandom
        elif is_read_mode(mode):
            base = io.BufferedReader
        else:
            base = io.BufferedWriter
    else:
        is_binary = False
        base = io.TextIOWrapper
        encoding = normalize_encoding(encoding)

    return mode, encoding, is_binary, base


def singleton(cls):
    return cls()


def identity(x):
    return x


def name_of(x):
    return getattr(x, "__name__", getattr(type(x), "__name__", str(x)))


@singledispatch
def type_spec(type_):
    if type_.__module__ == "builtins":
        path = type_.__name__
    else:
        path = classpath(type_)
    return "<{}>".format(path)


@type_spec.register(str)
def type_spec_str(s):
    return "<{}>".format(s)


def parser_constructor_for_collection(cls):
    if is_named_tuple_class(cls):
        return UnStarred(cls)
    return get_constructor_for(cls)


byte_repr = "<0-255>"
regex_repr = "<regex>"
regex_bytes_repr = "<byte-regex>"
date_repr = "YYYY-MM-DD"
path_repr = "<path>"
binary_path_repr = "<binary-file>"
text_path_repr = "<text-file>"
classpath_type_repr = "path.to.type[params]"
classpath_function_repr = "path.to.function"
int_repr = type_spec(int)
float_repr = type_spec(float)
decimal_repr = "<decimal-str>"
fraction_repr = "{i}[/{i}]".format(i=int_repr)
complex_repr = "{f}[+{f}j]".format(f=float_repr)
range_repr = "{i}:{i}[:{i}]".format(i=int_repr)
datetime_repr = "YYYY-MM-DD[THH:MM:SS[.ms]]"
ipv4_repr = "<ipaddr>"
ipv6_repr = "<ipv6addr>"
url_repr = "scheme://netloc[/path][;params][?query][#fragment]"
uuid_repr = "[0-f]{32}"
ellipsis_ = "..."
any_repr = "____"


default_repr_values = {
    str: type_spec(str),
    int: int_repr,
    float: float_repr,
    complex: complex_repr,
    fractions.Fraction: fraction_repr,
    decimal.Decimal: decimal_repr,
    range: range_repr,
    datetime.date: date_repr,
    datetime.datetime: datetime_repr,
    pathlib.Path: path_repr,
    File: path_repr,
    BinaryFile: binary_path_repr,
    TextFile: text_path_repr,
    typing.Pattern: regex_repr,
    typing.Pattern[bytes]: regex_bytes_repr,
    ipaddress.IPv4Address: ipv4_repr,
    ipaddress.IPv6Address: ipv6_repr,
    URL: url_repr,
    uuid.UUID: uuid_repr,
    Empty: any_repr,
    typing.Callable: classpath_function_repr,
    types.FunctionType: classpath_function_repr,
    types.BuiltinFunctionType: classpath_function_repr,
    numbers.Number: "|".join(
        (int_repr, float_repr, complex_repr.replace("[", "").replace("]", ""))
    ),
    numbers.Real: "|".join((int_repr, float_repr)),
    numbers.Integral: int_repr,
}

default_value_repr_values = {
    sys.stdout: "stdout",
    sys.stderr: "stderr",
    sys.stdin: "stdin",
}


def repr_type(type_, supertype=None):
    if supertype is None:
        return classpath_type_repr
    return "{}<:{}".format(classpath_type_repr, parameterized_classpath(supertype))


def repr_value(value: object) -> str:
    """Represent a default value on the command line"""
    r = default_value_repr_values.get(value)
    if r is None:
        return str(value)
    return r


def maybe_map(f, it, exc=Exception):
    for i in it:
        try:
            res = f(i)
        except exc:
            pass
        else:
            yield res


def to_param_doc(param: Doc, name: str) -> Optional[str]:
    if param is None:
        return None
    elif isinstance(param, CallableDocs):
        p = param.params.get(name)
        if p:
            return p.doc
    elif isinstance(param, ParamDocs):
        p = param.get(name)
        if p:
            return p.doc
    elif isinstance(param, ParamDoc):
        return param.doc
    else:
        raise TypeError(
            "must pass introspection.CallableDocs/Params/Param for a docstring; got {}".format(
                type(param)
            )
        )


class Missing(list):
    # we make this a list subclass to allow argparse append actions to take place
    @classmethod
    def missing(cls, value):
        if isinstance(value, cls):
            # nothing appended yet
            return not value
        elif isinstance(value, type):
            return issubclass(value, cls)
        return False


class IODispatch(Dispatcher):
    """interject a custom exception into the dispatch process"""

    exc_type = IOError

    def __init__(self, name, return_type, doc=None):
        self.return_type = deconstruct_generic(return_type)
        super().__init__(name, doc=doc)

    def __call__(self, arg):
        try:
            return Dispatcher.__call__(self, arg)
        except Exception as e:
            raise self.exc_type(self.return_type, arg, e)


class TypeCheckPicklableWithType(PicklableWithType):
    def type_check(self, value):
        if not isinstance_generic(value, self.type_):
            raise self.exc_cls(self.type_, value)
        return value


class TypeCheckInput(TypeCheckPicklableWithType):
    exc_cls = TypedInputError
    decode = staticmethod(identity)

    def __call__(self, value):
        try:
            parsed = self.decode(value)
        except Exception as e:
            raise self.exc_cls(self.type_, value, e)
        else:
            return self.type_check(parsed)


class TypeCheckImport(TypeCheckInput):
    decode = staticmethod(import_object)

    def __call__(self, value):
        if isinstance(value, str):
            return super().__call__(value)
        else:
            return self.type_check(value)


class TypeCheckOutput(TypeCheckPicklableWithType):
    exc_cls = TypedOutputError
    encode = staticmethod(identity)

    def __init__(self, type_, *args, encoder=None):
        super().__init__((type_, *args))
        if encoder is not None:
            self.encode = encoder

    def __call__(self, value):
        value = self.type_check(value)
        try:
            out = self.encode(value)
        except Exception as e:
            raise self.exc_cls(self.type_, value, e)
        else:
            return out


class TypeCheckOutputFunc(TypeCheckOutput):
    encode = staticmethod(function_classpath)

    def type_check(self, value):
        if not callable(value):
            raise self.exc_cls(
                self.type_, value, TypeError("{} is not callable".format(value))
            )
        return value

    def __call__(self, value):
        path = super().__call__(value)
        if import_object(path) is not value:
            raise self.exc_cls(
                self.type_,
                value,
                ValueError(
                    "classpath {} does not refer to the same object as {}".format(
                        path, value
                    )
                ),
            )
        return path


class TypeCheckOutputType(TypeCheckOutput):
    encode = staticmethod(parameterized_classpath)
