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
    is_top_type,
    LazyType,
    NonStrCollection,
    get_constructor_for,
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
from ..exceptions import (
    CLITypedInputError,
    CLIIOUndefinedForType,
    CLIIOUndefinedForNestedCollectionType,
)
from ..base_parsers import (
    parse_iso_date,
    parse_iso_datetime,
    parse_range,
    parse_regex,
    parse_regex_bytes,
    parse_bool,
    EnumParser,
    FlagParser,
)
from ..utils import (
    TypeCheckImportType,
    TypeCheckImport,
    Empty,
    identity,
    KEY_VAL_JOIN_CHAR,
    GenericIOTypeLevelSingleDispatch,
)
from ..file_types import File, IOParser

NoneType = type(None)


class InvalidCLIParser(TypeError):
    pass


def cli_split_keyval(s: str):
    return s.split(KEY_VAL_JOIN_CHAR, maxsplit=1)


def cli_parse_bytes(seq: typing.Sequence[str]):
    return bytes(map(int, seq))


def cli_parse_bytearray(seq: typing.Sequence[str]):
    return bytearray(map(int, seq))


def cli_parse_bool(s: typing.Union[str, bool]):
    # have to allow bools for the flag case; argparse includes an implicit boolean default in that case
    if isinstance(s, bool):
        return s
    return parse_bool(s)


cli_parse_by_constructor = {
    int,
    float,
    str,
    complex,
    decimal.Decimal,
    fractions.Fraction,
    pathlib.Path,
    ipaddress.IPv4Address,
    ipaddress.IPv6Address,
    uuid.UUID,
    File,
}

cli_parse_methods = {
    bool: cli_parse_bool,
    bytes: cli_parse_bytes,
    bytearray: cli_parse_bytearray,
    range: parse_range,
    datetime.date: parse_iso_date,
    datetime.datetime: parse_iso_datetime,
    typing.Pattern: parse_regex,
    typing.Pattern[bytes]: parse_regex_bytes,
    URL: urlparse,
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


class CLIParserDispatch(GenericIOTypeLevelSingleDispatch):
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
            underivable = [
                name
                for name, flag in [("nargs", derive_nargs), ("repr", derive_repr), ("completer", derive_completer)]
                if flag
            ]
            if underivable:
                warn("Can't derive {} when as_const = False; skipping derivations".format("/".join(underivable)))
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


cli_parser = CLIParserDispatch(
    __name__,
    isolated_bases=[typing.Union],
    resolve_exc_class=CLIIOUndefinedForType,
    call_exc_class=CLITypedInputError,
)


#########################
# Files and importables #
#########################


cli_parser.register(typing.Callable)(TypeCheckImport)

cli_parser.register(typing.Type)(TypeCheckImportType)

cli_parser.register(typing.IO)(IOParser)


###################################################################
# Special case - top type - assume str and pass through unchanged #
###################################################################


@cli_parser.register(typing.Any)
class CLINoParse:
    def __init__(self, type_, *args):
        if is_top_type(type_):
            warn(
                "Values passed from the command line for unannotated arguments or arguments annotated "
                "as a top type (object/typing.Any) will always be passed to python functions as strings"
            )
        else:
            raise TypeError(type_ if not args else type_[args])

    def __call__(self, arg: str):
        return arg


######################
# Collection parsers #
######################


@cli_parser.register(typing.Collection)
class CollectionCLIParser(CollectionWrapper):
    getter = cli_parser
    get_reducer = staticmethod(get_constructor_for)

    def __init__(self, coll_type, val_type=object):
        if cli_action(val_type) is not None:
            # nested collections with append action
            raise CLIIOUndefinedForNestedCollectionType(coll_type[val_type])
        super().__init__(coll_type, val_type)


@cli_parser.register(typing.Mapping)
class MappingCLIParser(MappingWrapper):
    constructor_allows_iterable = True
    getter = cli_parser
    get_reducer = staticmethod(get_constructor_for)

    def __init__(self, coll_type, key_type=object, val_type=object):
        if (cli_nargs(key_type) is not None) or (cli_nargs(val_type) is not None):
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
class UnionCLIParser(UnionWrapper):
    getter = cli_parser
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
class TupleCLIParser(TupleWrapper):
    getter = cli_parser
    get_reducer = staticmethod(get_constructor_for)

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
class LazyCLIParser(LazyWrapper):
    getter = cli_parser


@cli_parser.register_all(enum.Enum, enum.IntEnum)
def cli_enum_parser(enum_type):
    return EnumParser(enum_type).cli_parse


@cli_parser.register_all(enum.Flag, enum.IntFlag)
def cli_flag_parser(enum_type):
    return FlagParser(enum_type).cli_parse


# these types all have
cli_parser.register_from_mapping(cli_parse_methods, as_const=True)

# these types are all their own parsers
cli_parser.register_all(*cli_parse_by_constructor)(identity)
