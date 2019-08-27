# coding:utf-8
import typing
import enum
import itertools
import numbers
import pathlib
from bourbaki.introspection.types import (get_constraints, get_bound, get_generic_args, reconstruct_generic,
                                          issubclass_generic, is_top_type, is_named_tuple_class, get_named_tuple_arg_types)
from bourbaki.introspection.classes import parameterized_classpath
from bourbaki.introspection.generic_dispatch import GenericTypeLevelSingleDispatch
from bourbaki.application.completion.completers import (
    completer_argparser_from_type,
    CompletePythonClasses, CompletePythonSubclasses, CompletePythonCallables, CompleteFiles,
    CompleteFilesAndDirs, CompleteChoices, CompleteEnum, CompleteUnion, CompleteTuple, CompleteKeyValues,
    CompleteFloats, CompleteInts, CompleteBools, NoComplete,
)
from .cli_repr_ import cli_repr
from .utils import File

NoneType = type(None)


cli_completer = GenericTypeLevelSingleDispatch("cli_completer", isolated_bases=[typing.Union])

cli_completer.register_all(int, numbers.Integral, as_const=True)(CompleteInts())

cli_completer.register_all(float, numbers.Real, as_const=True)(CompleteFloats())

cli_completer.register(bool, as_const=True)(CompleteBools())

cli_completer.register(pathlib.Path, as_const=True)(CompleteFilesAndDirs())

cli_completer.register(File, as_const=True)(CompleteFiles())

cli_completer.register(typing.Callable, as_const=True)(CompletePythonCallables())

cli_completer.register(NoneType, as_const=True)(NoComplete)

cli_completer.register(enum.Enum)(CompleteEnum)


@cli_completer.register(typing.Collection)
def completer_for_collection(coll, v=None):
    if v is None:
        return
    return cli_completer(v)


@cli_completer.register(typing.Mapping)
def completer_for_mapping(m, k=None, v=None):
    return CompleteKeyValues(cli_completer(k), cli_completer(v))


@cli_completer.register(typing.Type)
def completer_for_type(t, supertype=None):
    if supertype is None or is_top_type(supertype):
        return CompletePythonClasses()
    elif isinstance(supertype, typing.TypeVar):
        bound = get_bound(supertype)
        if bound:
            supertype = bound
        else:
            constraints = get_constraints(supertype)
            if constraints:
                return CompleteChoices(*map(parameterized_classpath, constraints))
            return CompletePythonClasses()

    return CompletePythonSubclasses(supertype)


@cli_completer.register(typing.Tuple)
def completer_for_tuple(t, *contents):
    if not contents:
        if is_named_tuple_class(t):
            contents = get_named_tuple_arg_types(t)
            return _multi_completer(CompleteTuple, *contents)
        return completer_for_collection(t)
    elif contents[-1] is Ellipsis:
        return completer_for_collection(t, *contents[:-1])
    else:
        return _multi_completer(CompleteTuple, *contents)


@cli_completer.register(typing.Union)
def completer_for_union(u, *types):
    types = [t for t in types if t not in (NoneType, None)]
    if all(issubclass_generic(t, typing.Tuple) for t in types):
        # complete a Union of tuples as a tuple of unions - a fair approximation that parses
        argtups = (get_generic_args(t) for t in types)
        unionargtups = itertools.zip_longest(*argtups, fillvalue=NoneType)
        uniontypes = (typing.Union[args] for args in unionargtups)
        return _multi_completer(CompleteTuple, *uniontypes)
    return _multi_completer(CompleteUnion, *types, remove_no_complete=True)


@cli_completer.register(typing.Any)
def completer_for_any(type_, *args):
    t = reconstruct_generic((type_, *args))
    try:
        repr_ = cli_repr(t)
    except NotImplementedError:
        return
    else:
        return CompleteChoices(repr_)


def _multi_completer(completer_cls, *types, remove_no_complete=False):
    if len(types) == 1:
        return cli_completer(types[0])

    completers = []
    for t in types:
        try:
            comp = cli_completer(t)
        except NotImplementedError:
            comp = NoComplete
        if comp is None:
            comp = NoComplete
        if remove_no_complete and isinstance(comp, type(NoComplete)):
            pass
        else:
            completers.append(comp)

    return completer_cls(*completers) if completers else None


# register this as a helper so that manually-defined ArgumentParsers may still have meaningful completions installed
completer_argparser_from_type.register(type)(cli_completer)
