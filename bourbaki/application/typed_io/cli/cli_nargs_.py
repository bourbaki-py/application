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
    get_generic_origin,
    get_generic_args,
)
from bourbaki.introspection.generic_dispatch import (
    GenericTypeLevelSingleDispatch,
    UnknownSignature,
)
from ..utils import maybe_map, is_nested_collection
from ..exceptions import CLIIOUndefined, CLINestedCollectionsNotAllowed


NoneType = type(None)


class AmbiguousUnionNargs(CLIIOUndefined):
    def __str__(self):
        return "Types in union {} imply an ambiguous number of command line args".format(
            self.type_
        )


class NestedTupleCLINargsError(CLINestedCollectionsNotAllowed):
    def __str__(self):
        return (
            "Some type parameters of type {} require a variable number of command line args; can't parse "
            "unambiguously. Tuple types may have variadic type parameters only in the last position".format(self.type_)
        )


class NestedMappingNargsError(CLINestedCollectionsNotAllowed):
    def __str__(self):
        return (
            "Mapping types with keys or values requiring more than one command line arg can't be parsed: {}".format(
                self.type_
            )
        )


is_nested_collection_for_cli = GenericTypeLevelSingleDispatch(
    "is_nested_collection_for_cli", isolated_bases=[typing.Union],
)


@is_nested_collection_for_cli.register(typing.Any)
def is_nested_collection_for_cli_any(org: typing.Type, *args: typing.Type):
    if cli_nargs(org) in (ONE_OR_MORE, ZERO_OR_MORE):
        if args:
            inner_nargs = cli_nargs(args[0])
            return inner_nargs is not None
        return False
    else:
        return False


@is_nested_collection_for_cli.register(typing.Union)
def is_nested_collection_for_cli_union(t: typing.Type, *args: typing.Type):
     nesteds = set(is_nested_collection_for_cli(a) for a in args)
     if len(nesteds) != 1:
         raise CLIIOUndefined((t, *args))
     return next(iter(nesteds))


@is_nested_collection_for_cli.register(typing.Tuple)
def is_nested_collection_for_cli_tuple(u: typing.Type, *args: typing.Type):
    if Ellipsis in args:
        inner_nargs = cli_nargs(args[0])
        return inner_nargs is not None
    else:
        return False


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
        raise NestedTupleCLINargsError((tup_type, *types))

    if types and is_nested_collection(types[-1]):
        raise NestedTupleCLINargsError((tup_type, *types))

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


@cli_nargs.register(typing.Mapping)
def mapping_nargs(t, k=typing.Any, v=typing.Any):
    # mappings with multi-arg keys/values
    if (cli_nargs(k) is not None) or (cli_nargs(v) is not None):
        raise NestedMappingNargsError((t, k, v))
    return seq_nargs(t, k, v)


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

    # namedtuple and other fixed-length tuples
    _, nargs = check_tuple_nargs(t, *types)
    return nargs


@cli_nargs.register(typing.Union)
def union_nargs(u, *types):
    all_nargs = check_union_nargs(*types)
    return next(iter(all_nargs))


cli_option_nargs = cli_nargs
