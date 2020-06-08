# coding:utf-8
from typing import Union, Optional, Callable, TypeVar, Any, List, Type
from argparse import ZERO_OR_MORE, ONE_OR_MORE, OPTIONAL
from functools import partial, singledispatch
from inspect import Parameter
from bourbaki.introspection.typechecking import isinstance_generic
from bourbaki.introspection.docstrings import CallableDocs, ParamDocs, ParamDoc
from bourbaki.introspection.imports import import_object, import_type
from bourbaki.introspection.callables import function_classpath
from bourbaki.introspection.classes import parameterized_classpath
from bourbaki.introspection.generic_dispatch import (
    GenericTypeLevelSingleDispatch,
    UnknownSignature,
    AmbiguousResolutionError,
)
from bourbaki.introspection.generic_dispatch_helpers import PicklableWithType
from bourbaki.introspection.types import get_constructor_for
from .exceptions import IOUndefinedForType, TypedIOValueError

T = TypeVar("T")
Empty = Parameter.empty
Doc = Union[CallableDocs, ParamDocs, ParamDoc]

NARGS_OPTIONS = (ZERO_OR_MORE, ONE_OR_MORE, OPTIONAL, None)
CLI_PREFIX_CHAR = "-"
KEY_VAL_JOIN_CHAR = "="


######################
# Metavar formatting #
######################


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


##############################
# CLI Option/argument naming #
##############################


def to_cmd_line_name(s: str, negative_flag=False):
    name = s.replace("_", "-").strip("-")
    if negative_flag:
        name = "no-" + name
    return name


def cmd_line_arg_names(name, positional=False, prefix_char=None, negative_flag=False):
    if not positional:
        if prefix_char is None:
            # --option, use '-'
            prefix_char = CLI_PREFIX_CHAR
        names = (
            # 1 '-' for option names with len <= 1, 2 for long option names
            (prefix_char * min(len(name), 2))
            + to_cmd_line_name(name, negative_flag),
        )
    else:
        names = (name,)
    return names


def get_dest_name(args, prefix_chars=CLI_PREFIX_CHAR):
    cs = prefix_chars
    try:
        dest = next(
            argname.lstrip(cs) for argname in args if len(argname.lstrip(cs)) > 1
        )
    except StopIteration:
        dest = args[0].lstrip(cs)
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


def name_of(x):
    return getattr(x, "__name__", getattr(type(x), "__name__", str(x)))


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


###################
# Parsing helpers #
###################


def to_instance_of(value, type_: Type[T]) -> T:
    """Use a type as its own constructor on an input value; allows injecting custom subclasses
    e.g. of simple builtin types by binding the `type_` arg when resolving a parser for the type."""
    if type(value) is type_:
        return value
    return type_(value)


class basic_decoder:
    """For binding the `type_` arg of a parser, e.g. `to_instance_of`, at parser resolution time.
    Note that `func` must accept a `type_` keyword arg (as `to_instance_of` does)."""

    def __init__(self, func):
        self.func = func

    def __call__(self, type_, *args):
        """"""
        return partial(self.func, type_=get_constructor_for(type_))


##############################
# General functional helpers #
##############################


def cached_property(method):
    """compute the getter once and store the result in the instance dict under the same name,
    so it isn't computed again"""
    attr = method.__name__
    sentinel = object()

    def newmethod(self):
        value = self.__dict__.get(attr, sentinel)
        if value is sentinel:
            value = method(self)
            self.__dict__[attr] = value
        return value

    return property(newmethod)


def singleton(cls):
    return cls()


def identity(x):
    return x


def maybe_map(f, it, exc=Exception):
    for i in it:
        try:
            res = f(i)
        except exc:
            # we use this for union parsing. as long as at least one parse/encode succeeds,
            # we don't care what exceptions are raised before
            pass
        else:
            yield res


class Missing(list):
    # we make this a list subclass to allow argparse append actions to take place
    @classmethod
    def missing(cls, value):
        if isinstance(value, cls):
            # missing if nothing appended yet
            return not value
        elif isinstance(value, type):
            return issubclass(value, cls)
        return False


def parse_or_fail(
    func: Callable, type_: Type[T], exc_class: Type[TypedIOValueError], value: Any
) -> T:
    try:
        return func(value)
    except Exception as e:
        raise exc_class(type_, value, e)


class GenericIOTypeLevelSingleDispatch(GenericTypeLevelSingleDispatch):
    def __init__(
        self,
        name: str,
        isolated_bases: Optional[List[Type]] = None,
        resolve_exc_class: Type[IOUndefinedForType] = IOUndefinedForType,
        call_exc_class: Optional[Type[TypedIOValueError]] = TypedIOValueError,
    ):
        super().__init__(name, isolated_bases=isolated_bases)
        self.call_exc_class = call_exc_class
        self.resolve_exc_class = resolve_exc_class

    def resolve(self, sig, *, debug: bool = False):
        try:
            f = super().resolve(sig, debug=debug)
        except UnknownSignature:
            raise self.resolve_exc_class(sig[0])
        except AmbiguousResolutionError as e:
            raise e
        else:
            return f


class GenericIOParserTypeLevelSingleDispatch(GenericIOTypeLevelSingleDispatch):
    """Inject custom exceptions into the resolution process and at the call site of the resolved parsing function.
    resolve_exc_class should subclass IOUndefinedForType with the same constructor signature, and
    call_exc_class should subclass TypedIOValueError with the same constructor signature"""

    def __call__(self, type_, **kwargs):
        func = super().__call__(type_, **kwargs)
        if self.call_exc_class is None:
            return func
        return partial(parse_or_fail, func, type_, self.call_exc_class)


#####################################
# I/O helpers for importable values #
#####################################


class TypeCheckInput(PicklableWithType):
    decode = staticmethod(identity)

    def __init__(self, type_, *args, decoder: Optional[Callable] = None):
        super().__init__(type_, *args)
        if decoder is not None:
            self.decode = decoder

    def __call__(self, value):
        parsed = self.decode(value)
        if not isinstance_generic(parsed, self.type_):
            raise TypeError(
                "Parsed value {!r} is not an instance of {!s}".format(
                    parsed, self.type_
                )
            )
        return parsed


TypeCheckImport = partial(TypeCheckInput, decoder=import_object)
TypeCheckImportType = partial(TypeCheckInput, decoder=import_type)


class TypeCheckOutput(PicklableWithType):
    encode = staticmethod(identity)

    def __init__(self, type_, *args, encoder: Optional[Callable] = None):
        super().__init__(type_, *args)
        if encoder is not None:
            self.encode = encoder

    def __call__(self, value):
        if not isinstance_generic(value, self.type_):
            raise TypeError(
                "Expected to encode value of type {!s}; got {!s}".format(
                    self.type_, type(value)
                )
            )
        return self.encode(value)


class TypeCheckExport(TypeCheckOutput):
    def __call__(self, value):
        path = super().__call__(value)
        if import_object(path) is not value:
            raise ValueError(
                "classpath {} does not refer to the same object as {}".format(
                    path, value
                )
            )
        return path


TypeCheckExport = partial(TypeCheckExport, encoder=function_classpath)
TypeCheckExportType = partial(TypeCheckExport, encoder=parameterized_classpath)
