# coding:utf-8
import typing
from argparse import ZERO_OR_MORE, ONE_OR_MORE
import decimal
import fractions
from urllib.parse import ParseResult as URL
from bourbaki.introspection.types import (
    NonStrCollection,
    is_named_tuple_class,
    get_named_tuple_arg_types,
)
from bourbaki.introspection.generic_dispatch import (
    GenericTypeLevelSingleDispatch,
    UnknownSignature,
)
from .utils import maybe_map
from .exceptions import CLIIOUndefined


NoneType = type(None)

NestedCollectionTypes = (
    typing.Mapping[NonStrCollection, typing.Any],
    typing.Mapping[typing.Any, NonStrCollection],
)


class AmbiguousUnionNargs(CLIIOUndefined):
    def __str__(self):
        return "Types in union {} imply an ambiguous number of command line args".format(
            self.type_
        )


class NestedCollectionsCLIArgError(CLIIOUndefined):
    def __str__(self):
        return (
            "Some type parameters of sequence type {} require more than one command line arg; can't parse "
            "unambiguously".format(self.type_)
        )


def check_union_nargs(*types):
    types = [t for t in types if t not in (NoneType, None)]
    all_nargs = tuple(maybe_map(cli_nargs, types, (UnknownSignature, CLIIOUndefined)))
    if len(set(all_nargs)) > 1:
        raise AmbiguousUnionNargs((typing.Union, *types))
    if len(all_nargs) == 0:
        raise CLIIOUndefined((typing.Union, *types))
    return all_nargs


def check_tuple_nargs(tup_type, *types, allow_tail_collection: bool = True):
    if Ellipsis in types:
        types = [typing.List[types[0]]]
    all_nargs = tuple(cli_nargs(t) for t in types)
    head_nargs = all_nargs[:-1] if allow_tail_collection else all_nargs
    if any(((a is not None) and (not isinstance(a, int))) for a in head_nargs):
        raise NestedCollectionsCLIArgError((tup_type, *types))

    if not all_nargs:
        total_nargs = 0
    elif allow_tail_collection:
        tail_nargs = all_nargs[-1]
        if tail_nargs == ONE_OR_MORE:
            total_nargs = ONE_OR_MORE
        elif tail_nargs == ZERO_OR_MORE:
            total_nargs = ONE_OR_MORE if head_nargs else ZERO_OR_MORE
        else:
            total_nargs = sum(1 if n is None else n for n in all_nargs)
    else:
        total_nargs = sum(1 if n is None else n for n in all_nargs)

    return all_nargs, total_nargs


# nargs for argparse.ArgumentParser

cli_nargs = GenericTypeLevelSingleDispatch("cli_nargs", isolated_bases=[typing.Union])

cli_nargs.register_all(decimal.Decimal, fractions.Fraction, URL, as_const=True)(None)


@cli_nargs.register(typing.Any)
def default_nargs(*args, **kwargs):
    # single string arg unless otherwise overridden below
    return None


@cli_nargs.register(NonStrCollection)
def seq_nargs(*types):
    # all collections other than str
    return ZERO_OR_MORE


@cli_nargs.register_all(NestedCollectionTypes)
def nested_collections_cli_error(t, *args):
    # collections of collections
    raise NestedCollectionsCLIArgError((t, *args))


@cli_nargs.register(typing.Collection[NonStrCollection])
@cli_nargs.register(typing.Tuple[NonStrCollection, ...])
def nested_option_nargs(t, *types):
    if len(types) > 1 and not (len(types) == 2 and types[1] is Ellipsis):
        raise CLIIOUndefined(t, *types)
    return cli_nargs(types[0])


@cli_nargs.register(typing.Tuple)
def tuple_nargs(t, *types):
    if not types and is_named_tuple_class(t):
        types = get_named_tuple_arg_types(t)
    elif types and types[-1] is Ellipsis:
        return cli_nargs(typing.List[types[0]])
    elif not types:
        return ZERO_OR_MORE
    else:
        _, nargs = check_tuple_nargs(t, *types)
        return nargs

    _, nargs = check_tuple_nargs(t, *types)
    return nargs


@cli_nargs.register(typing.Union)
def union_nargs(u, *types):
    all_nargs = check_union_nargs(*types)
    return next(iter(all_nargs))


cli_option_nargs = cli_nargs

cli_action = GenericTypeLevelSingleDispatch(
    "cli_action", isolated_bases=[typing.Union, typing.Tuple]
)


@cli_action.register(typing.Union)
def cli_action_any(u, *ts):
    actions = set(map(cli_action, (t for t in ts if t is not NoneType)))
    if len(actions) > 1:
        raise CLIIOUndefined(u, *ts)
    return next(iter(actions))


cli_action.register(typing.Any, as_const=True)(None)
cli_action.register(typing.Collection[NonStrCollection], as_const=True)("append")
