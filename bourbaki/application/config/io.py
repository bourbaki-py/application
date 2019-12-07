# coding:utf-8
from typing import IO, Any, Mapping, Sequence, Union, Optional as Opt
import os
import argparse
from enum import Enum
from pathlib import Path
from functools import partial
from logging import getLogger
from collections import ChainMap
import yaml
import toml
import ujson as json
from bourbaki.introspection.prettyprint import has_identifier_keys
from ..namespace import namespace_recursive
from ..paths import get_file, ensure_dir, path_with_ext
from .python import load_python, dump_python, MAX_PY_WIDTH
from .ini import load_ini, dump_ini
from .exceptions import ConfigNotSerializable

NoneType = type(None)
logger = getLogger(__name__)

# config formatting constants

LEGAL_CONFIG_EXTENSIONS = {".yml", ".yaml", ".json", ".toml", ".py", ".ini"}
EMPTY_CONFIG_VALUE = "________"
# Force indentation for small collections for readability
YAML_DUMP_KWARGS = dict(default_flow_style=False, width=MAX_PY_WIDTH, indent=2)

loaders = {
    ".yml": yaml.safe_load,
    ".yaml": yaml.safe_load,
    ".json": json.load,
    ".toml": toml.load,
    ".py": load_python,
    ".ini": load_ini,
}
loader_kw = {}

dumpers = {
    ".yml": yaml.safe_dump,
    ".yaml": yaml.safe_dump,
    ".json": json.dump,
    ".toml": toml.dump,
    ".py": dump_python,
    ".ini": dump_ini,
}
dumper_kw = {
    ".json": dict(indent=2),
    ".yml": YAML_DUMP_KWARGS,
    ".yaml": YAML_DUMP_KWARGS,
}


class ConfigFormat(Enum):
    yaml = yml = ".yml"
    toml = ".toml"
    json = ".json"
    ini = ".ini"
    py = ".py"


class UnknownConfigExtension(ValueError):
    def __init__(self, ext):
        super().__init__(ext)
        self.ext = ext

    def __str__(self):
        return "Unknown config extension: {}; legal choices are {}".format(
            repr(self.ext), tuple(sorted(LEGAL_CONFIG_EXTENSIONS))
        )


class UnknownConfigLoadExtension(UnknownConfigExtension):
    def __str__(self):
        return super().__str__() + "; cannot load"


class UnknownConfigDumpExtension(UnknownConfigExtension):
    def __str__(self):
        return super().__str__() + "; cannot dump"


def normalize_ext(ext):
    return "." + ext.lstrip(".")


def _register_config_io(exts, default_kw, func_registry, kw_registry):
    exts = list(map(normalize_ext, exts))

    def dec(f):
        for ext in exts:
            func_registry[ext] = f
            if default_kw:
                kw_registry[ext] = default_kw
            LEGAL_CONFIG_EXTENSIONS.add(ext)
        return f

    return dec


def register_load_config(*exts: str, **default_kw):
    """
    examples:

    @register_load_config(".jsonl", ".jsonlines", linebreak='\n')
    def load_json_lines(file_handle, linebreak):
        return list(map(json.loads, map(str.strip, file_handle.read().split(linebreak))))

    OR

    register_load_config(".yaml")(yaml.safe_load)
    """
    return _register_config_io(exts, default_kw, loaders, loader_kw)


def register_dump_config(*exts: str, **default_kw):
    """
    examples:

    @register_dump_config(".jsonl", ".jsonlines")
    def dump_json_lines(iterable, file_handle):
        for obj in iterable:
            print(json.dumps(obj, file=file_handle))

    OR

    register_dump_config(".yaml", indent=4)(yaml.safe_dump)
    """
    return _register_config_io(exts, default_kw, dumpers, dumper_kw)


def allow_unsafe_yaml():
    global loaders, dumpers
    for ext in (".yml", ".yaml"):
        loaders[ext] = yaml.load
    for ext in (".yml", ".yaml"):
        dumpers[ext] = yaml.dump


def require_safe_yaml():
    global loaders, dumpers
    for ext in (".yml", ".yaml"):
        loaders[ext] = yaml.safe_load
    for ext in (".yml", ".yaml"):
        dumpers[ext] = yaml.safe_dump


def _config_io(
    load: bool, obj: Any, file: IO, ext: str, kw: Opt[Mapping[str, Any]] = None
):
    if load:
        func_registry, kw_registry, exc_type, args = (
            loaders,
            loader_kw,
            UnknownConfigLoadExtension,
            (file,),
        )
    else:
        func_registry, kw_registry, exc_type, args = (
            dumpers,
            dumper_kw,
            UnknownConfigDumpExtension,
            (obj, file),
        )

    try:
        io_func = func_registry[ext]
    except KeyError:
        raise exc_type(ext)
    else:
        defaults = kw_registry.get(ext)
        kws = [d for d in (kw, defaults) if d]
        if not kws:
            result = io_func(*args)
        else:
            result = io_func(*args, **ChainMap(*kws))

    return result


def _load_config(file: IO, ext: str, kw: Opt[Mapping[str, Any]] = None):
    return _config_io(True, None, file, ext, kw)


def _dump_config(obj: Any, file: IO, ext: str, kw: Opt[Mapping[str, Any]] = None):
    return _config_io(False, obj, file, ext, kw)


def _load_config_dir(config_file, ext=None):
    load = partial(load_config, namespace=False, ext=ext, disambiguate=False)
    filenames = os.listdir(config_file)
    stripped_names = [os.path.splitext(p)[0] for p in filenames]
    qualified_names = [os.path.join(config_file, p) for p in filenames]
    return dict(zip(stripped_names, map(load, qualified_names)))


def load_config(
    config_file: Union[str, Path, IO],
    ext: Opt[str] = None,
    disambiguate: bool = False,
    namespace: bool = False,
    **load_kw
):
    # try to get a name for the file to dispatch on
    if isinstance(config_file, (Path, str)):
        if os.path.isdir(config_file) and disambiguate:
            # load config for each file in the dir
            conf = _load_config_dir(config_file, ext=ext)
            if namespace:
                conf = namespace_recursive(conf)
            return conf
        else:
            # try to load later for a single path
            filename = str(config_file)
    else:
        # try for an open file handle with name attribute (not all have it)
        try:
            filename = config_file.name
        except AttributeError:
            filename = None

    # Then we haven't parsed from a directory; continue with a file
    # if passed, ext determines the serialization protocol used, otherwise it is inferred from config_file
    if ext is None:
        if filename is None:
            raise ValueError(
                "To load config from filename {}, you must pass `ext` to specify the "
                "serialization protocol".format(config_file)
            )

        filename, ext = path_with_ext(filename, ext, disambiguate=disambiguate)
    else:
        filename = config_file if filename is None else filename

    file, close = get_file(filename, "r")

    if close:
        with file:
            conf = _load_config(file, ext, load_kw)
    else:
        conf = _load_config(file, ext, load_kw)

    if namespace:
        conf = namespace_recursive(conf)

    return conf


def dump_config(
    conf: Union[Mapping, Sequence, argparse.Namespace],
    config_file: Union[str, Path, IO],
    ext: Opt[Union[ConfigFormat, str]] = None,
    disambiguate: bool = False,
    as_dir: bool = False,
    allow_dir: bool = False,
    **dump_kw
):
    if not isinstance(conf, (Mapping, Sequence)):
        raise ConfigNotSerializable(
            "conf must be a Mapping or Sequence type; got {}".format(type(conf))
        )

    if isinstance(ext, ConfigFormat):
        ext = ext.value

    if as_dir:
        if ext is None:
            raise ValueError("must provide an extension when as_dir=True")
        if not isinstance(config_file, (Path, str)):
            raise TypeError(
                "cannot determine a directory from config_file arg of type {}; pass a str or pathlib.Path".format(
                    type(config_file)
                )
            )
        ensure_dir(config_file)
        allow_dir = True
    elif isinstance(config_file, (Path, str)):
        config_file, ext = path_with_ext(config_file, ext, disambiguate)
    elif ext is None:
        try:
            fname = config_file.name
        except AttributeError:
            pass
        else:
            ext = os.path.splitext(fname)[-1]

        if not ext:
            raise ValueError(
                "Could not infer config extension from file {}".format(config_file)
            )

    # file is an open file handle if not a dir, else a Path
    file, close = get_file(config_file, "w", allow_dir=allow_dir)

    if isinstance(file, Path):
        # directory
        if not isinstance(conf, Mapping) or not has_identifier_keys(conf):
            raise ConfigNotSerializable(
                "Can only dump config of type Mapping[str, Any] with identifier keys to a "
                "directory; got {}".format(type(conf))
            )
        for name, subconf in conf.items():
            dump_config(
                subconf, file / name, ext=ext, as_dir=False, allow_dir=True, **dump_kw
            )
    elif close:
        # file
        with file:
            _dump_config(conf, file, ext, dump_kw)
    else:
        # file
        _dump_config(conf, file, ext, dump_kw)
