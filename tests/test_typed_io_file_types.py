# coding:utf-8
import io
import os
import tempfile

import pytest

from bourbaki.application.typed_io.file_types import File, TextFile, BinaryFile, READ_MODES, WRITE_MODES


@pytest.mark.parametrize(
    "fileclass1,fileclass2",
    [
        (File, File),
        (File["r"], File),
        (File["w"], File),
        (File["rb"], File),
        (File["wb"], File),
        (BinaryFile, File),
        (TextFile, File),
        (File["r"], TextFile),
        (File["w"], TextFile),
        (File["r", "utf-8"], io.TextIOWrapper),
        (File["w", "ascii"], io.TextIOWrapper),
        (File["rb"], BinaryFile),
        (File["wb"], BinaryFile),
        (File["rb"], io.BufferedReader),
        (File["wb"], io.BufferedWriter),
        (File["rb+"], BinaryFile),
        (File["rb+"], io.BufferedRandom),
        (File["r+", "utf16"], TextFile),
        (File["r+", "utf16"], io.TextIOWrapper),
    ],
)
def test_file_issubclass(fileclass1, fileclass2):
    assert issubclass(fileclass1, fileclass2)
    if fileclass1 != fileclass2:
        assert not issubclass(fileclass2, fileclass1)


@pytest.mark.parametrize(
    "file,fileclass", [(io.BytesIO(), File["wb"]), (io.StringIO(), File["w+"])]
)
def test_file_isinstance(file, fileclass):
    assert isinstance(file, fileclass)


@pytest.mark.parametrize("mode", list(READ_MODES))
def test_open_file_isinstance_by_read_mode(mode):
    path = tempfile.mktemp()
    with open(path, "w") as f:
        # create file
        pass
    with open(path, mode) as f:
        assert isinstance(f, File[mode])
    assert isinstance(f, File[mode])
    os.remove(path)


@pytest.mark.parametrize("mode", list(WRITE_MODES))
def test_open_file_isinstance_by_write_mode(mode):
    path = tempfile.mktemp()
    if "x" not in mode:
        with open(path, "w") as f:
            # create file
            pass
    with open(path, mode) as f:
        assert isinstance(f, File[mode])
    assert isinstance(f, File[mode])
    os.remove(path)
