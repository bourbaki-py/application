# coding:utf-8
import os
import re
from pathlib import Path
from io import StringIO, BytesIO, IOBase
from typing import Union
from functools import partial
from cytoolz import valmap
from .namespace import Namespace

FileTypes = (IOBase,)
FileType = Union[FileTypes]
_path_checkers = dict(
    f=os.path.isfile, d=os.path.isdir, dir=os.path.isdir, file=os.path.isfile
)

DEFAULT_FILENAME_DATE_FMT = (
    "%Y-%m-%d_%H:%M:%S"
)  # Format for dates appended to files or dirs.
# This will lexsort in temporal order.
DEFAULT_FILENAME_N_DIGITS = 6


def ensure_dir(dir_):
    try:
        if not os.path.exists(dir_):
            os.mkdir(dir_)
        return dir_
    except FileExistsError:
        if os.path.isfile(dir_):
            raise NotADirectoryError("{} exists but is not a directory".format(dir_))
        return None


def get_file(file_or_path, mode=None, allow_dir=False):
    """if a file object is passed, return it unaltered, with a flag indicating that the file should not be closed
    by the caller (the opener may have other uses for it). In this case, if mode is also passed, it is checked against
    the existing file's mode and a ValueError is thrown if they disagree.

    If a string is passed, it is treated as a path and a file at that location is opened and returned with a flag
    indicating that the file should be closed by the caller.
    """
    if not isinstance(file_or_path, FileTypes):
        if isinstance(file_or_path, (str, Path)) and os.path.isdir(file_or_path):
            if not allow_dir:
                raise IsADirectoryError(
                    "allow_dir=False but {} is a directory".format(file_or_path)
                )
            else:
                close = False
                file = Path(file_or_path)
        else:
            close = True
            if mode:
                file = open(file_or_path, mode)
            else:
                file = open(file_or_path)
    else:
        close = False
        file = file_or_path

        if mode is not None:
            if hasattr(file, "mode") and mode != file.mode:
                raise ValueError(
                    "mode {} was requested, but the given file has mode {}".format(
                        mode, file.mode
                    )
                )
            elif isinstance(file, StringIO) and "b" in mode:
                raise ValueError(
                    "mode {} was requested, but the given file is a {}, which supports only text IO".format(
                        mode, type(file)
                    )
                )
            elif isinstance(file, BytesIO) and "b" not in mode:
                raise ValueError(
                    "mode {} was requested, but the given file is a {}, which supports only binary IO".format(
                        mode, type(file)
                    )
                )

    return file, close


def is_newer(file1, file2):
    if file2 is None:
        return True
    mtime1 = os.stat(file1).st_mtime
    if isinstance(file2, (str, bytes, Path)):
        mtime2 = os.stat(file2).st_mtime
    elif isinstance(file2, (float, int)):
        mtime2 = file2
    else:
        raise TypeError(
            "file2 must be str, pathlib.Path, None, float, or int; got {}".format(
                type(file2)
            )
        )
    return mtime1 > mtime2


def abspath_expanduser(path):
    return os.path.abspath(os.path.expanduser(path))


def dir_prefix_and_ext(prefix, ext=None):
    dir_ = os.path.dirname(prefix)
    if ext is None:
        prefix, ext = os.path.splitext(os.path.basename(prefix))
        if prefix.startswith(".") and ext == "":
            prefix, ext = ext, prefix
    else:
        prefix = os.path.basename(prefix)

    return dir_, prefix, ext


def path_with_ext(file_path, ext=None, disambiguate=False):
    file_path, ext_ = _path_with_ext(file_path, ext)
    if not ext_ and not ext:
        if disambiguate:
            file_path, ext_ = _path_with_ext(disambiguate_path(file_path), ext)
        else:
            raise ValueError(
                "no extension specified for file path {}; try passing one manually via the "
                "`ext` arg or specify `disambiguate=True`".format(file_path)
            )
    else:
        ext_ = ext or ext_

    return file_path, ext_


def _path_with_ext(path, ext=None):
    name, ext_ = os.path.splitext(path)
    if ext_:
        if ext is not None and ext_ != ext:
            raise ValueError(
                "ambiguous extension; config_file has extension {} while ext is {}".format(
                    ext_, ext
                )
            )

    ext_ = ext or ext_
    p, e = name + ext_, ext_
    return p, e


def disambiguate_path(file_path):
    """Find the unique file with path `file_path`, excluding extensions. If there is no such file, raise
    FileNotFoundError"""
    dir_, name, ext = dir_prefix_and_ext(file_path)
    dir_ = dir_ or None  # don't allow empty string for dir
    paths = [path for path in os.listdir(dir_) if os.path.splitext(path)[0] == name]

    if len(paths) == 0:
        raise FileNotFoundError(
            "No file with any extension found at {}".format(file_path)
        )
    elif len(paths) != 1:
        raise FileNotFoundError(
            "Amiguous config path {}; multiple matches found: {}".format(
                file_path, paths
            )
        )
    p = os.path.join(dir_ or "", paths[0])
    return p


def prepend_dir(base_dir, paths, namespace=True):
    join = partial(os.path.join, base_dir)

    if isinstance(paths, Namespace):
        paths = paths.__dict__
        namespace = True

    if isinstance(paths, dict):
        paths = valmap(join, paths)
        if namespace:
            paths = Namespace(**paths)
    else:
        paths = list(map(join, paths))

    return paths


def matching_dirs_in(path, pat=None):
    """return a list of dirs in path (a dir) whose name match regex pattern pat"""
    return _matching_paths_in(path, "d", pat)


def matching_files_in(path, pat=None):
    """return a list of files in path (a dir) whose name match regex pattern pat"""
    return _matching_paths_in(path, "f", pat)


def _matching_paths_in(path, type_, pat=None):
    pat = re.compile(pat) if isinstance(pat, str) else pat
    ix = [None, "d", "f"].index(type_)
    fs = next(os.walk(path))[ix]
    gen = (os.path.join(path, f) for f in fs)
    if pat is not None:
        gen = filter(pat.search, gen)
    return list(gen)
