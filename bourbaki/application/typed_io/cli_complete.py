# coding:utf-8
import typing
import enum
import numbers
import pathlib
from bourbaki.introspection.types import get_constraints, get_bound
from bourbaki.introspection.classes import parameterized_classpath
from bourbaki.introspection.generic_dispatch import GenericTypeLevelSingleDispatch
from bourbaki.application.completion.completers import (
    completer_argparser_from_type,
    CompletePythonClasses, CompletePythonSubclasses,
    CompletePythonCallables, CompleteFiles,
    CompleteFilesAndDirs, CompleteChoices, CompleteEnum, CompleteUnion,
    CompleteFloats, CompleteInts, CompleteBools, NoComplete,
)
from .utils import File

NoneType = type(None)


cli_completer = GenericTypeLevelSingleDispatch("cli_completer", isolated_bases=[typing.Union])

cli_completer.register_all(int, numbers.Integral, as_const=True)(CompleteInts())

cli_completer.register_all(float, numbers.Real, as_const=True)(CompleteFloats())

cli_completer.register(bool, as_const=True)(CompleteBools())

cli_completer.register(pathlib.Path, as_const=True)(CompleteFilesAndDirs())

cli_completer.register(File, as_const=True)(CompleteFiles())

cli_completer.register(typing.Callable, as_const=True)(CompletePythonCallables())

cli_completer.register(enum.Enum)(CompleteEnum)


@cli_completer.register(typing.Collection)
def completer_for_collection(coll, v=None):
    if v is None:
        return
    return cli_completer(v)


@cli_completer.register(typing.Type)
def completer_for_type(t, supertype=None):
    if supertype is None:
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


@cli_completer.register(typing.Union)
def completer_for_union(u, *types):
    types = [t for t in types if t not in (NoneType, None)]
    if len(types) == 1:
        return cli_completer(types[0])
    completers = []
    for t in types:
        try:
            comp = cli_completer(t)
        except NotImplementedError:
            comp = NoComplete

        if comp is not None:
            completers.append(comp)
    return CompleteUnion(*completers) if completers else None


# register this as a helper so that manually-defined ArgumentParsers may still have meaningful completions installed
completer_argparser_from_type.register(type)(cli_completer)
