# coding:utf-8
from itertools import chain
from typing import Type, Optional
from bourbaki.introspection.types import (
    NonStrCollection,
    is_named_tuple_class,
    get_named_tuple_arg_types,
)
from inspect import Parameter
from .cli_nargs_ import cli_nargs, is_nested_collection_for_cli
from .utils import (
    KEY_VAL_JOIN_CHAR,
    to_str_cli_repr,
    PicklableWithType,
    PositionalMetavarFormatter,
)
NoneType = type(None)

# nargs for argparse.ArgumentParser

def cli_metavar(
    param: Parameter,
    type_: Optional[Type] = None,
    metavar: Optional[str] = None,
    positional=False,
):
    if type_ is None:
        type_ = param.annotation

    kind = param.kind

    if metavar is None:
        if param.kind == Parameter.VAR_KEYWORD:
            metavar = "NAME{}{}".format(
                KEY_VAL_JOIN_CHAR, name.upper().rstrip("S")
            )
        elif is_named_tuple_class(type_per_option):
            metavar = tuple(
                to_str_cli_repr(k.upper(), cli_nargs(v))
                for k, v in type_per_option.__annotations__.items()
            )
        elif positional:
            metavar = name.upper()
        else:
            metavar = type_str
            type_str = None

    single_metavar_types = (str, type(None))
    if not isinstance(metavar, single_metavar_types):
        metavar = tuple(chain.from_iterable((t,) if isinstance(t, str) else t for t in metavar))

    if not isinstance(type_str, single_metavar_types):
        # tuple types
        type_str = " ".join(type_str)

    if positional and not isinstance(metavar, single_metavar_types):
        # hack to deal with the fact that argparse handles fixed-length positionals differently than
        # fixed-length options when formatting help strings
        metavar = PositionalMetavarFormatter(
            *(metavar or ()), name=name.upper()
        )


def flatten(obj):
    def inner(obj):
        if isinstance(obj, (list, tuple)):
            yield from chain.from_iterable(map(inner, obj))
        else:
            yield obj
    return list(inner(obj))
