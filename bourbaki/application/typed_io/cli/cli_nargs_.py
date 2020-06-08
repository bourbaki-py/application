# coding:utf-8
import typing
from typing import Optional, Union
from argparse import ZERO_OR_MORE, ONE_OR_MORE, OPTIONAL
from urllib.parse import ParseResult as URL
from bourbaki.introspection.types import (
    NonStrCollection,
    is_named_tuple_class,
    get_named_tuple_arg_types,
)
from bourbaki.introspection.generic_dispatch import UnknownSignature
from ..utils import maybe_map, GenericIOTypeLevelSingleDispatch
from ..exceptions import (
    CLIIOUndefinedForType,
    CLIIOUndefinedForNestedCollectionType,
    CLIIOUndefinedForNestedTupleType,
    CLIAmbiguousUnionType,
)

APPEND = "append"

NoneType = type(None)


class CLINargsAction(typing.NamedTuple):
    """Record type for representing specification of argparse's `nargs`, and optionally `action` parameters"""
    nargs: Optional[Union[int, str]]
    action: Optional[str] = None

    @property
    def normalized_nargs(self):
        if self.nargs == ONE_OR_MORE:
            return ZERO_OR_MORE
        return self.nargs

    @property
    def is_nested(self):
        return self.action == APPEND

    @property
    def is_variable_length_collection(self):
        return self.action is not None or (self.nargs is not None and not isinstance(self.nargs, int))

    @property
    def is_variable_length(self):
        return self.is_variable_length_collection or self.nargs == OPTIONAL

    def __add__(self, other: 'CLINargsAction'):
        other = to_cli_nargs_action(other)
        if self.action != other.action:
            raise ValueError(
                "Can't add CLINargs with different parser actions: {} != {}".format(self.action, other.action)
            )

        if not isinstance(self.nargs, str):
            # handle ONE_OR_MORE, OPTIONAL, etc. cases from the left side
            other, self = self, other

        if self.nargs == ONE_OR_MORE:
            return CLINargsAction(ONE_OR_MORE, self.action)
        elif self.nargs in (ZERO_OR_MORE, OPTIONAL):
            nargs = ZERO_OR_MORE if other.nargs in (ZERO_OR_MORE, OPTIONAL) else ONE_OR_MORE
            return CLINargsAction(nargs, self.action)
        else:
            return CLINargsAction(
                (1 if self.nargs is None else self.nargs) + (1 if other.nargs is None else other.nargs),
                self.action,
            )

    def __radd__(self, other):
        # allows calling sum() on an iterable of CLINargsAction, since the implicit start is 0
        return self + other


def to_cli_nargs_action(nargs: Optional[Union[int, str, CLINargsAction]] = None) -> CLINargsAction:
    if isinstance(nargs, CLINargsAction):
        return nargs
    return CLINargsAction(nargs)


# nargs for argparse.ArgumentParser


class GenericTypeLevelCLINargsSingleDispatch(GenericIOTypeLevelSingleDispatch):
    def __call__(self, *args, **kwargs) -> CLINargsAction:
        result = super().__call__(*args, **kwargs)
        return to_cli_nargs_action(result)


cli_nargs = GenericTypeLevelCLINargsSingleDispatch(
    "cli_nargs",
    isolated_bases=[typing.Union],
    resolve_exc_class=CLIIOUndefinedForType,
)


# base case for all unregistered types
cli_nargs.register(typing.Any, as_const=True)(CLINargsAction(None))

# urllib.parse.ParseResult is a namedtuple type
cli_nargs.register_all(URL, as_const=True)(CLINargsAction(None))

# byte types are subclasses of Collection but we parse them from hex strings
cli_nargs.register(typing.ByteString, as_const=True)(CLINargsAction(None))


@cli_nargs.register(NonStrCollection)
def collection_nargs(t, v=typing.Any, *args):
    value_nargs = cli_nargs(v)
    if value_nargs.action is not None:
        raise CLIIOUndefinedForNestedCollectionType(t[(v, *args)])
    # all collections other than str
    if value_nargs.nargs is None:
        return CLINargsAction(ZERO_OR_MORE, None)
    return CLINargsAction(value_nargs.nargs, APPEND)


@cli_nargs.register(typing.Mapping)
def mapping_nargs(t, k=typing.Any, v=typing.Any):
    key_nargs = cli_nargs(k)
    val_nargs = cli_nargs(v)
    print(key_nargs, val_nargs)
    if (key_nargs.nargs is not None) or (val_nargs.nargs is not None):
        raise CLIIOUndefinedForNestedCollectionType(t[k, v])
    return CLINargsAction(ZERO_OR_MORE)


@cli_nargs.register(typing.Tuple)
def tuple_nargs(t, *types):
    if not types and is_named_tuple_class(t):
        types = get_named_tuple_arg_types(t)
    elif types and types[-1] is Ellipsis:
        return cli_nargs(typing.List[types[0]])
    elif not types:
        return CLINargsAction(ZERO_OR_MORE)

    # namedtuple and other fixed-length tuples
    _, total_nargs = check_tuple_nargs(t, *types)
    return total_nargs


@cli_nargs.register(typing.Union)
def union_nargs(u, *types):
    types = tuple(t for t in types if t not in (NoneType, None))
    all_nargs = tuple(maybe_map(cli_nargs, types, (UnknownSignature, CLIIOUndefinedForType)))
    if len(all_nargs) == 0:
        raise CLIIOUndefinedForType(Union[types])
    if len(set(a.action for a in all_nargs)) > 1:
        raise CLIAmbiguousUnionType(Union[types])
    if len(set(a.normalized_nargs for a in all_nargs)) > 1:
        raise CLIAmbiguousUnionType(Union[types])

    return next(iter(all_nargs))


def check_tuple_nargs(tup_type, *types, allow_tail_collection: bool = True):
    if Ellipsis in types:
        # variable-length tuples
        types = [typing.List[types[0]]]

    all_nargs = tuple(cli_nargs(t) for t in types)
    if not all_nargs:
        return all_nargs, CLINargsAction(ZERO_OR_MORE)

    head_nargs = all_nargs[:-1] if allow_tail_collection else all_nargs
    if (allow_tail_collection and all_nargs[-1].is_nested) or any(a.is_variable_length for a in head_nargs):
        try:
            type_ = tup_type[types]
        except:
            type_ = tup_type
        raise CLIIOUndefinedForNestedTupleType(type_)

    total_nargs = sum(all_nargs)
    return all_nargs, total_nargs


cli_option_nargs = cli_nargs
