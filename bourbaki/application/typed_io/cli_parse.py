# coding:utf-8
import typing
import decimal
import enum
import fractions
import pathlib
import datetime
import ipaddress
import collections
from urllib.parse import ParseResult as URL, urlparse
import uuid
from inspect import Parameter
from functools import lru_cache
from warnings import warn
from bourbaki.introspection.types import (
    get_named_tuple_arg_types,
    is_named_tuple_class,
    issubclass_generic,
    is_top_type,
    LazyType,
    NonStrCollection,
)
from bourbaki.introspection.callables import signature
from bourbaki.introspection.generic_dispatch import (
    GenericTypeLevelSingleDispatch,
    UnknownSignature,
    DEBUG,
)
from bourbaki.introspection.generic_dispatch_helpers import (
    CollectionWrapper,
    MappingWrapper,
    UnionWrapper,
    TupleWrapper,
    LazyWrapper,
)
from .cli_complete import cli_completer
from .cli_nargs_ import check_tuple_nargs, check_union_nargs, cli_nargs
from .cli_repr_ import cli_repr
from .exceptions import (
    CLITypedInputError,
    CLIIOUndefined,
    CLIUnionInputError,
    CLINestedCollectionsNotAllowed,
)
from .parsers import (
    parse_iso_date,
    parse_iso_datetime,
    parse_range,
    parse_regex,
    parse_regex_bytes,
    parse_bool,
    parse_path,
    EnumParser,
    FlagParser,
    TypeCheckImportType,
    TypeCheckImportFunc,
)
from .utils import (
    File,
    Empty,
    identity,
    KEY_VAL_JOIN_CHAR,
    parser_constructor_for_collection,
)

NoneType = type(None)


class InvalidCLIParser(TypeError):
    pass


def cli_split_keyval(s: str):
    i = s.index(KEY_VAL_JOIN_CHAR)
    return s[:i], s[i + 1 :]


def cli_parse_bytes(seq: typing.Sequence[str]):
    return bytes(map(int, seq))


def cli_parse_bytearray(seq: typing.Sequence[str]):
    return bytearray(map(int, seq))


def cli_parse_bool(s: typing.Union[str, bool]):
    # have to allow bools for the flag case; argparse includes an implicit boolean default in that case
    if isinstance(s, bool):
        return s
    return parse_bool(s, exc_type=CLITypedInputError)


cli_parse_methods = {
    int: int,
    bool: cli_parse_bool,
    float: float,
    str: str,
    complex: complex,
    decimal.Decimal: decimal.Decimal,
    fractions.Fraction: fractions.Fraction,
    bytes: cli_parse_bytes,
    bytearray: cli_parse_bytearray,
    range: parse_range,
    datetime.date: parse_iso_date,
    datetime.datetime: parse_iso_datetime,
    pathlib.Path: parse_path,
    typing.Pattern: parse_regex,
    typing.Pattern[bytes]: parse_regex_bytes,
    uuid.UUID: uuid.UUID,
    URL: urlparse,
    ipaddress.IPv4Address: ipaddress.IPv4Address,
    ipaddress.IPv6Address: ipaddress.IPv6Address,
    Empty: identity,
}


@lru_cache(None)
def _validate_parser(func):
    try:
        sig = signature(func)
    except ValueError:
        annotation = None
    else:
        msg = "CLI parsers must have only a single required positional arg; "
        if len(sig.parameters) == 0:
            raise InvalidCLIParser(msg + "{} takes no arguments!".format(func))

        required = [
            p
            for p in sig.parameters.values()
            if p.default is Parameter.empty
            and p.kind not in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD)
        ]

        if len(required) > 1:
            raise InvalidCLIParser(
                msg
                + "{} requires {} args with signature {}".format(
                    func, len(required), sig
                )
            )
        elif any(p.kind == Parameter.KEYWORD_ONLY for p in required):
            raise InvalidCLIParser(
                msg + "{} requires keyword args with signature {}".format(func, sig)
            )
        else:
            param = next(iter(sig.parameters.values()))
            if param.kind in (Parameter.KEYWORD_ONLY, Parameter.VAR_KEYWORD):
                raise InvalidCLIParser(
                    msg
                    + "{} takes only keyword args with signature {}".format(func, sig)
                )
            if param.kind is Parameter.VAR_POSITIONAL:
                warn(
                    "{} accepts *args for its first argument; when called as a parser, only one arg will be passed. "
                    "Is this what was intended?"
                )

        annotation = param.annotation

    return func, annotation


class CLIParserDispatch(GenericTypeLevelSingleDispatch):
    def register(
        self,
        *sig,
        debug: bool = DEBUG,
        as_const: bool = False,
        derive_nargs: bool = False,
        derive_repr: bool = False,
        derive_completer: bool = False
    ):
        """
        Register a parser for a type, and optionally, if the following are defined for the parser's single arg
        annotation type and not yet registered, register them too for the type:
        - cli_nargs
        - cli_repr
        - cli_completer
        when derive_nargs, derive_repr, derive_completer respectively are True.
        """
        dec = super().register(*sig, debug=debug, as_const=as_const)
        if not as_const:
            return dec

        def maybe_register_nargs_repr_completer(f):
            # register an inferred nargs with cli_nargs if possible
            func, type_ = _validate_parser(f)
            if type_ is not None and type_ is not Parameter.empty:
                for derive, dispatcher in [
                    (derive_nargs, cli_nargs),
                    (derive_repr, cli_repr),
                    (derive_completer, cli_completer),
                ]:
                    # if derivation is indicated and the signature is not already registered
                    if derive and sig not in dispatcher.funcs:
                        try:
                            value = dispatcher(type_)
                        except NotImplementedError:
                            pass
                        else:
                            dispatcher.register(*sig, debug=debug, as_const=True)(value)

            return dec(f)

        return maybe_register_nargs_repr_completer


cli_parser = CLIParserDispatch(__name__, isolated_bases=[typing.Union])


@cli_parser.register(typing.Any)
def cli_parser_any(t, *args):
    if is_top_type(t):
        return identity
    raise CLIIOUndefined((t, *args))


@cli_parser.register(typing.Callable)
class TypeCheckImportFuncCLI(TypeCheckImportFunc):
    exc_cls = CLITypedInputError


@cli_parser.register(typing.Type)
class TypeCheckImportTypeCLI(TypeCheckImportType):
    exc_cls = CLITypedInputError


class GenericCLIParserMixin:
    getter = cli_parser
    get_reducer = staticmethod(parser_constructor_for_collection)


@cli_parser.register(typing.Collection)
class CollectionCLIParser(GenericCLIParserMixin, CollectionWrapper):
    def __init__(self, coll_type, val_type=object):
        if issubclass_generic(val_type, NonStrCollection):
            raise CLINestedCollectionsNotAllowed((coll_type, val_type))
        super().__init__(coll_type, val_type)


@cli_parser.register(typing.Collection[NonStrCollection])
class NestedCollectionCLIParser(GenericCLIParserMixin, CollectionWrapper):
    def __init__(self, coll_type, val_type=object):
        super().__init__(coll_type, val_type)


@cli_parser.register(typing.Mapping)
class MappingCLIParser(GenericCLIParserMixin, MappingWrapper):
    constructor_allows_iterable = True

    def __init__(self, coll_type, key_type=object, val_type=object):
        if issubclass_generic(key_type, NonStrCollection) or issubclass_generic(
            val_type, NonStrCollection
        ):
            raise CLINestedCollectionsNotAllowed((coll_type, key_type, val_type))
        super().__init__(coll_type, key_type, val_type)
        coll_type = self.reduce
        if issubclass(coll_type, (collections.Counter, collections.ChainMap)):
            self.constructor_allows_iterable = False

    def __call__(self, args):
        keyvals = map(cli_split_keyval, args)
        if not self.constructor_allows_iterable:
            return self.reduce(dict(self.call_iter(keyvals)))
        return super().__call__(keyvals)


@cli_parser.register(typing.Union)
class UnionCLIParser(GenericCLIParserMixin, UnionWrapper):
    reduce = staticmethod(next)
    tolerate_errors = (CLIIOUndefined, UnknownSignature)
    exc_class = CLIUnionInputError

    def __init__(self, u, *types):
        check_union_nargs(*types)
        super().__init__(u, *types)

    def __call__(self, arg):
        if arg is None and self.is_optional:
            return arg
        return super().__call__(arg)


@cli_parser.register(typing.Tuple)
class TupleCLIParser(GenericCLIParserMixin, TupleWrapper):
    _collection_cls = CollectionCLIParser
    _nargs = None
    _entry_nargs = None
    require_same_len = False

    def __new__(cls, t, *types):
        if is_named_tuple_class(t):
            types = get_named_tuple_arg_types(t)

        self = TupleWrapper.__new__(cls, t, *types)
        if Ellipsis in types:
            return self

        self._entry_nargs, self._nargs = check_tuple_nargs(t, *types)
        self.require_same_len = all(n in (None, 1) for n in self._entry_nargs)
        return self

    def iter_chunks(self, args):
        ix = 0
        for n in self._entry_nargs:
            if n is None:
                yield args[ix]
                ix += 1
            elif isinstance(n, int):
                yield args[ix : ix + n]
                ix += n
            else:
                yield args[ix:]
                ix = None

    def call_iter(self, arg):
        return (f(a) for f, a in zip(self.funcs, self.iter_chunks(arg)))


@cli_parser.register(LazyType)
class LazyCLIParser(GenericCLIParserMixin, LazyWrapper):
    pass


@cli_parser.register_all(enum.Enum, enum.IntEnum)
def cli_enum_parser(enum_):
    return EnumParser(enum_).cli_parse


@cli_parser.register_all(enum.Flag, enum.IntFlag)
def cli_flag_parser(enum_):
    return FlagParser(enum_).cli_parse


# File subclasses are their own parsers
cli_parser.register(File)(identity)


cli_parser.register_from_mapping(cli_parse_methods, as_const=True)


cli_option_parser = GenericTypeLevelSingleDispatch(
    "cli_option_parser", isolated_bases=cli_parser.isolated_bases
)


@cli_option_parser.register(typing.Collection[NonStrCollection])
class CollectionCLIOptionParser(GenericCLIParserMixin, CollectionWrapper):
    pass
