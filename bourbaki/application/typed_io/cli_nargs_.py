# coding:utf-8
import typing
from argparse import ZERO_OR_MORE
import decimal
import fractions
from bourbaki.introspection.types import NonStrCollection, is_named_tuple_class, get_named_tuple_arg_types
from bourbaki.introspection.generic_dispatch import GenericTypeLevelSingleDispatch, UnknownSignature
from .utils import maybe_map
from .exceptions import CLIIOUndefined


NoneType = type(None)

NestedCollectionTypes = (typing.Collection[NonStrCollection],
                         typing.Tuple[NonStrCollection, ...],
                         typing.Mapping[NonStrCollection, typing.Any],
                         typing.Mapping[typing.Any, NonStrCollection])


class AmbiguousUnionNargs(CLIIOUndefined):
    def __str__(self):
        return ("Types in union {} imply an ambiguous number of command line args"
                .format(self.type_))


class NestedCollectionsCLIArgError(CLIIOUndefined):
    def __str__(self):
        return ("Some type parameters sequence type {} require more than one command line arg; can't parse "
                "unambiguously".format(self.type_))


def check_union_nargs(*types):
    types = [t for t in types if t not in (NoneType, None)]
    all_nargs = tuple(maybe_map(cli_nargs, types, (UnknownSignature, CLIIOUndefined)))
    if len(set(all_nargs)) > 1:
        raise AmbiguousUnionNargs((typing.Union, *types))
    if len(all_nargs) == 0:
        raise CLIIOUndefined((typing.Union, *types))
    return all_nargs


def check_tuple_nargs(t, *types):
    all_nargs = tuple(cli_nargs(t) for t in types if t is not Ellipsis)
    if any(a not in (1, None) for a in all_nargs):
        raise NestedCollectionsCLIArgError((t, *types))
    return all_nargs


# nargs for argparse.ArgumentParser

cli_nargs = GenericTypeLevelSingleDispatch("cli_nargs", isolated_bases=[typing.Union])

cli_nargs.register_all(decimal.Decimal, fractions.Fraction, as_const=True)(None)


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


@cli_nargs.register(typing.Tuple)
def tuple_nargs(t, *types):
    if not types and is_named_tuple_class(t):
        types = get_named_tuple_arg_types(t)
    elif not types or types[-1] is Ellipsis:
        _ = check_tuple_nargs(t, *types)
        return ZERO_OR_MORE

    _ = check_tuple_nargs(t, *types)
    return len(types)


@cli_nargs.register(typing.Union)
def union_nargs(u, *types):
    all_nargs = check_union_nargs(*types)
    return next(iter(all_nargs))
