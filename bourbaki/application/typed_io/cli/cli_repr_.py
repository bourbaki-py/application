# coding:utf-8
import typing
import enum
from itertools import repeat
from bourbaki.introspection.generic_dispatch import GenericTypeLevelSingleDispatch
from bourbaki.introspection.types import (
    issubclass_generic,
    is_named_tuple_class,
    get_named_tuple_arg_types,
    is_top_type,
    LazyType,
    NonStrCollection,
)
from .cli_nargs_ import cli_nargs
from .exceptions import CLIIOUndefined, CLINestedCollectionsNotAllowed
from .parsers import bool_constants, EnumParser
from .utils import (
    byte_repr,
    any_repr,
    classpath_function_repr,
    default_repr_values,
    repr_type,
)
from .utils import type_spec, KEY_VAL_JOIN_CHAR, to_str_cli_repr

NoneType = type(None)

bool_cli_repr = "{{{}}}".format("|".join(bool_constants))

cli_repr_values = default_repr_values.copy()
cli_repr_values.update(
    [
        (typing.ByteString, byte_repr),
        (bool, bool_cli_repr),
        (typing.Callable, classpath_function_repr),
    ]
)


cli_repr = GenericTypeLevelSingleDispatch(__name__, isolated_bases=[typing.Union])


# base generic handlers


@cli_repr.register(typing.Any)
def default_cli_repr(type_, *args):
    return any_repr if is_top_type(type_) else type_spec(type_)


@cli_repr.register(typing.Union)
def cli_repr_union(u, *types):
    def inner(types_):
        for t in types_:
            if t is NoneType or t is None:
                continue
            try:
                repr_ = cli_repr(t)
            except CLIIOUndefined:
                continue
            else:
                yield repr_

    reprs = list(inner(types))
    if not reprs:
        raise CLIIOUndefined((u, *types))
    if all(isinstance(r, str) for r in reprs):
        return "|".join(reprs)
    else:
        lens = set(len(t) for t in reprs if not isinstance(t, str))
        if len(lens) > 1:
            raise ValueError(
                "can't format CLI representation for {}; got sub-reprs {}. for a Union, the reprs "
                "of the types must all be str or tuples of a single length".format(
                    u[types], reprs
                )
            )
        maxlen = max(lens) if lens else 1
        tups = zip(*(repeat(s, maxlen) if isinstance(s, str) else s for s in reprs))
        return tuple("|".join(tup) for tup in tups)


@cli_repr.register(typing.Tuple)
def cli_repr_tuple(t, *types):
    if not types and is_named_tuple_class(t):
        types = get_named_tuple_arg_types(t)

    if types and Ellipsis not in types:
        return tuple(to_str_cli_repr(cli_repr(t), cli_nargs(t)) for t in types)
    elif not types:
        t = typing.Any
    else:
        t = types[0]

    return cli_repr(t)


@cli_repr.register(typing.Mapping)
def cli_repr_mapping(m, k, v):
    if issubclass_generic(k, NonStrCollection) or issubclass_generic(
        v, NonStrCollection
    ):
        raise CLINestedCollectionsNotAllowed((m, k, v))
    return "{k}{j}{v}".format(k=cli_repr(k), v=cli_repr(v), j=KEY_VAL_JOIN_CHAR)


# uni-typed tuples are variable-length, and sets can be parsed from sequences as well
@cli_repr.register(typing.Collection)
def cli_repr_seq(s, t=typing.Any):
    if issubclass_generic(t, NonStrCollection):
        raise CLINestedCollectionsNotAllowed((s, t))
    return cli_repr(t)


@cli_repr.register(typing.Collection[NonStrCollection])
@cli_repr.register(typing.Tuple[NonStrCollection, ...])
def cli_repr_nested_seq(s, t=typing.Any, ellipsis=Ellipsis):
    # this allows going down one level of nesting in the case of options where an append mode can parse
    return cli_repr(t)


@cli_repr.register_all(enum.Enum, enum.IntEnum)
def cli_repr_enum(enum_):
    return EnumParser(enum_).cli_repr()


cli_repr.register(typing.Type)(repr_type)


@cli_repr.register(LazyType)
def cli_repr_lazy(l, t):
    return type_spec(getattr(t, "__forward_arg__", t))


# concrete handlers

cli_repr.register_from_mapping(cli_repr_values, as_const=True)
