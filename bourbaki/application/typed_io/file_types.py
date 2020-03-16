# coding:utf-8
from typing import IO
from argparse import FileType
import io
import encodings
import sys
from functools import lru_cache
from bourbaki.introspection.types import PseudoGenericMeta

READ_MODES = {"r", "rb", "r+", "rb+", "a+", "ab+", "wb+"}
WRITE_MODES = {"w", "wb", "w+", "wb+", "a", "ab", "a+", "ab+", "rb+", "x", "xb"}
FILE_MODES = READ_MODES.union(WRITE_MODES)


#############################
# File Types for Annotation #
#############################


class _FileHandleConstructor(PseudoGenericMeta):
    @lru_cache(None)
    def __getitem__(cls, mode_enc) -> type:
        if isinstance(mode_enc, tuple):
            mode, encoding = mode_enc
        else:
            mode, encoding = mode_enc, None

        if cls.mode is not None or cls.encoding is not None:
            raise TypeError(
                "Can't subscript File more than once; tried to subscript {} with {}".format(
                    repr(cls), mode_enc
                )
            )
        mode, encoding, is_binary, base = _file_args(mode, encoding)
        new_cls = BinaryFile if is_binary else TextFile
        mcs = type(cls)
        return type.__new__(
            mcs,
            new_cls.__name__,
            (new_cls, base),
            dict(__args__=(mode, encoding), __origin__=File),
        )

    def __repr__(cls):
        tname = cls.__name__
        if cls.encoding:
            return "{}[{}, {}]".format(tname, repr(cls.mode), repr(cls.encoding))
        if cls.mode:
            return "{}[{}]".format(tname, repr(cls.mode))
        else:
            return tname

    @property
    def readable(cls):
        return cls.mode in READ_MODES

    @property
    def writable(cls):
        return cls.mode in WRITE_MODES

    @property
    def binary(cls):
        return "b" in cls.mode

    @property
    def mode(cls):
        if not cls.__args__:
            return None
        return cls.__args__[0]

    @property
    def encoding(cls):
        if not cls.__args__:
            return None
        return cls.__args__[1]

    def __instancecheck__(cls, instance):
        return isinstance(instance, cls.__bases__)


class File(metaclass=_FileHandleConstructor):
    encoding = None
    mode = None

    def __new__(cls, path) -> IO:
        # argparse.FileType has the nice feature of treating '-' as stdin/stdout and raising nice errors
        return FileType(cls.mode, encoding=cls.encoding)(path)


class TextFile(File):
    def __new__(cls, path) -> IO[str]:
        return super().__new__(cls, path)


class BinaryFile(File):
    def __new__(cls, path) -> IO[bytes]:
        return super().__new__(cls, path)


def is_binary_mode(mode):
    return "b" in mode and mode in FILE_MODES


def is_write_mode(mode):
    return mode in WRITE_MODES


def is_read_mode(mode):
    return mode in READ_MODES


def _file_args(mode, encoding):
    mode = normalize_file_mode(mode)

    if is_binary_mode(mode):
        is_binary = True

        if encoding is not None:
            raise ValueError(
                "binary mode {} can't be specified with an encoding; got encoding={}".format(
                    repr(mode), repr(encoding)
                )
            )

        if is_read_mode(mode) and is_write_mode(mode):
            base = io.BufferedRandom
        elif is_read_mode(mode):
            base = io.BufferedReader
        else:
            base = io.BufferedWriter
    else:
        is_binary = False
        base = io.TextIOWrapper
        encoding = normalize_encoding(encoding)

    return mode, encoding, is_binary, base


def normalize_encoding(enc):
    if enc is None:
        return sys.getdefaultencoding()
    enc_ = encodings.search_function(enc)
    if not enc_:
        raise ValueError(
            "{} is not a valid text encoding; see encodings.aliases.aliases for the set of legal "
            "values".format(enc)
        )
    return enc_.name


def normalize_file_mode(mode):
    if mode not in FILE_MODES:
        raise ValueError(
            "{} is not a valid file mode; choose one of {}".format(
                mode, tuple(FILE_MODES)
            )
        )
    return mode
