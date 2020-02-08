# !/usr/bin/env python
"""
Usage:
    compgen_python_classpaths.py IMPORT_PREFIX [legal_prefix1 [legal_prefix2 [...]]]
    compgen_python_classpaths.py IMPORT_PREFIX --class [legal_prefix1 [legal_prefix2 [...]]]
    compgen_python_classpaths.py IMPORT_PREFIX --callable [legal_prefix1 [legal_prefix2 [...]]]
    compgen_python_classpaths.py IMPORT_PREFIX --subclass [classpath1 [classpath2 [...]]]
    compgen_python_classpaths.py IMPORT_PREFIX --instance [classpath1 [classpath2 [...]]]
"""

from itertools import chain
import os
import sys
import typing
from typing import Union
from warnings import warn

scriptname = 'compgen_python_classpaths.py'

Module = type(sys)

issubclass_generic = None
isinstance_generic = None
typetypes = None
nontypes = tuple(
    getattr(typing, t)
    for t in ["Optional", "ClassVar", "NoReturn"]
    if hasattr(typing, t)
)

COMPLETION_DEBUG_ENV_VAR = "BOURBAKI_COMPLETION_DEBUG"

DEBUG = os.environ.get(COMPLETION_DEBUG_ENV_VAR, "").lower().strip()
if DEBUG == "true" or (DEBUG.isdigit() and DEBUG != "0"):
    warn(
        "Found environment variable {}={}; verbose output will be generated for {}".format(
            COMPLETION_DEBUG_ENV_VAR, DEBUG, scriptname
        )
    )
    DEBUG = True if not DEBUG.isdigit() else int(DEBUG)
else:
    DEBUG = False

CLASS_FLAG = "--class"
CALLABLE_FLAG = "--callable"
MODULE_FLAG = "--module"
INSTANCE_FLAG = "--instance"
SUBCLASS_FLAG = "--subclass"


# CLI dispatches to one of these functions


def complete_objpath(prefix: str = "", *legal_prefixes: str):
    _debug("Completing paths for all objects")
    yield from _complete_objpath(prefix, legal_prefixes=legal_prefixes)


def complete_callable_path(prefix: str = "", *legal_prefixes: str):
    _debug("Completing paths for callables")
    yield from _complete_objpath(
        prefix, typecheck=callable_, legal_prefixes=legal_prefixes
    )


def complete_classpath(prefix: str = "", *legal_prefixes: str):
    _debug("Completing paths for classes")
    yield from _complete_objpath(
        prefix, cls=type, typecheck=isinstance, legal_prefixes=legal_prefixes
    )


def complete_module_path(prefix: str = "", *legal_prefixes: str):
    _debug("Completing paths for modules")
    yield from _complete_objpath(
        prefix,
        include_attrs=False,
        legal_prefixes=legal_prefixes,
        include_builtins=False,
    )


def complete_instance_path(prefix: str = "", *legal_classes: str):
    _debug("Completing paths for instances of : {cls}", cls=legal_classes)
    # delayed import for speed if not needed; this only gets called at most once per interpreter launch
    global isinstance_generic
    if isinstance_generic is None:
        from bourbaki.introspection.typechecking import isinstance_generic

    if legal_classes:
        cls = _materialize_classes(*legal_classes)
        typecheck = isinstance
    else:
        cls = typecheck = None

    yield from _complete_objpath(prefix, cls=cls, typecheck=typecheck)


def complete_subclasspath(prefix: str = "", *legal_superclasses: str):
    _debug("Completing paths for subclasses of : {cls}", cls=legal_superclasses)
    # delayed import for speed if not needed; this only gets called at most once per interpreter launch
    global issubclass_generic
    if issubclass_generic is None:
        global typetypes
        from bourbaki.introspection.types import issubclass_generic, typetypes

    if legal_superclasses:
        cls = _materialize_classes(*legal_superclasses)
        typecheck = issubclass_
    else:
        cls, typecheck = type, isinstance

    yield from _complete_objpath(prefix, cls=cls, typecheck=typecheck)


# The above dispatch to this main function


def _complete_objpath(
    prefix: str,
    cls=None,
    typecheck=None,
    legal_prefixes=None,
    include_attrs=True,
    include_builtins=True,
):
    from bourbaki.introspection.imports import import_object
    import builtins

    if legal_prefixes:
        candidate_prefixes = [p for p in legal_prefixes if p.startswith(prefix)]
        if not candidate_prefixes:
            return ()
    else:
        candidate_prefixes = [prefix]

    def inner(prefix):
        parts = prefix.split(".")
        if len(parts) > 1:
            modname, suffix = ".".join(parts[:-1]), parts[-1]
            names = get_all_module_names(prefix, suffix)
            try:
                mod = import_object(modname)
            except ImportError:
                mod = None
            else:
                names = chain(names, get_submodule_names(mod, suffix, modname=modname))
                if include_attrs:
                    names = chain(
                        names,
                        get_attr_names(mod, suffix, cls, typecheck, modname=modname),
                    )
        else:
            mod = None
            names = get_all_module_names(prefix)
            if include_builtins:
                names = chain(names, get_attr_names(builtins, prefix, cls, typecheck))
        return names

    return chain.from_iterable(map(inner, candidate_prefixes))


# Helpers


def _debug(msg: str, **kw):
    if DEBUG:
        OKGREEN = "\033[92m"
        WARNING = "\033[93m"
        FAIL = "\033[91m"
        ENDC = "\033[0m"
        print(
            "\033[92m{}: {}\033[0m".format(
                scriptname, msg.format(**kw)
            ),
            file=sys.stderr,
        )


def callable_(o, cls=None):
    return callable(o)


def issubclass_(o, cls):
    # delayed import for speed if not needed; this only gets called at most once per interpreter launch
    if isinstance(o, (type, *typetypes)) and o not in nontypes:
        try:
            return issubclass_generic(o, cls)
        except Exception:
            return False
    else:
        return False


def _materialize_classes(*legal_superclasses: str):
    if not legal_superclasses:
        clss = None
    else:
        from bourbaki.introspection.imports import import_type
        from bourbaki.introspection.types import typetypes

        clss = []
        for name in legal_superclasses:
            try:
                cls = import_type(name)
            except (ImportError, AttributeError):
                pass
            else:
                if isinstance(cls, (type, *typetypes)):
                    clss.append(cls)
        clss = tuple(clss)

    _debug("Imported classes: {clss}", clss=clss)
    if not clss:
        return object
    return Union[clss]


def get_attr_names(mod, attr_prefix="", cls=None, typecheck=None, modname=None):
    _debug("Completing attributes on module/object {mod}", mod=mod)

    fmt_name = None if modname is None else (modname + ".{}").format

    attrs = dir(mod)

    if attr_prefix:
        _debug("Filtering to attributes with prefix {prefix}", prefix=attr_prefix)
        attrs = (a for a in attrs if a.startswith(attr_prefix))

    if typecheck is not None:
        _debug(
            "Filtering to attributes by type using {func}({cls})",
            func=typecheck,
            cls=cls,
        )
        attrs = (a for a in attrs if typecheck(getattr(mod, a, None), cls))

    yield from (map(fmt_name, attrs) if fmt_name else attrs)


def get_submodule_names(mod, suffix="", modname=None):
    file_ = getattr(mod, "__file__", None)

    if modname is None:
        modname = getattr(mod, "__name__", "")

    if file_ and os.path.basename(file_) == "__init__.py":
        dirs = getattr(mod, "__path__", [os.path.dirname(file_)])
        for dir_ in dirs:
            _debug(
                "Completing submodules of {modname} in {dir_}",
                modname=modname,
                dir_=dir_,
            )
            for name in get_module_names(dir_, suffix):
                yield ".".join([modname, name])


def get_module_names(dir_, submod_prefix=None):
    # _debug("Searching modules in {dir_}", dir_=dir_)
    for name in os.listdir(dir_):
        if name == "__init__.py":
            continue
        if submod_prefix and not name.startswith(submod_prefix):
            continue

        prefix, ext = os.path.splitext(name)
        if ext == ".py":
            yield prefix
        elif ext == ".pth":
            yield prefix.split("-")[0]
        elif ext == ".so":
            yield prefix.split(".")[0]
        elif ext == ".egg-link":
            yield prefix.replace("-", "_")
        elif ext not in (".dist-info", ".egg-info"):
            d = os.path.join(dir_, name)
            if os.path.isdir(d) and os.path.isfile(os.path.join(d, "__init__.py")):
                yield name


def get_all_module_names(prefix="", submod_prefix=None):
    _debug(
        "Listing all known modules from sys.path{prefix_note}",
        prefix_note="" if not prefix else " with prefix '%s'" % prefix,
    )
    dirs = [d for d in sys.path if os.path.isdir(d)]

    names = (name for dir_ in dirs for name in get_module_names(dir_, submod_prefix))
    names = chain(names, ("builtins",))
    if prefix:
        names = (name for name in names if name.startswith(prefix))

    yield from uniq(names)


def uniq(iter_):
    visited = set()
    for _ in iter_:
        if _ in visited:
            continue
        visited.add(_)
        yield _


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        exit(0)

    if os.getenv("APPUTILS_COMPLETION_DEBUG", "false").lower() == "true":
        DEBUG = True

    dispatch = {
        CLASS_FLAG: complete_classpath,
        SUBCLASS_FLAG: complete_subclasspath,
        INSTANCE_FLAG: complete_instance_path,
        MODULE_FLAG: complete_module_path,
        CALLABLE_FLAG: complete_callable_path,
    }

    prefix, args = argv[0], argv[1:]

    if not args:
        args = [""]
        complete = complete_objpath
    elif args[0] in dispatch:
        complete = dispatch[args[0]]
        args = args[1:]
    else:
        complete = complete_objpath

    total_completions = 0
    name = None
    for name in complete(prefix, *args):
        print(name, file=sys.stdout)
        total_completions += 1
    if total_completions == 1:
        # prevent early-stopping in the case of only 1 completion that doesn't actually meet the criteria
        for name in complete(name + ".", *args):
            print(name, file=sys.stdout)


if __name__ == "__main__":
    main()
