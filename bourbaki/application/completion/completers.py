# coding:utf-8
from typing import IO, List, Tuple, Sequence, Union, Optional as Opt
from abc import ABC
import argparse
from argparse import ArgumentParser, Action, FileType, _SubParsersAction
from functools import singledispatch, lru_cache
import os
from pathlib import Path
import pkgutil
import re
from shlex import quote
import sys
from warnings import warn

from bourbaki.introspection.classes import parameterized_classpath
from bourbaki.introspection.generic_dispatch import const

from ..paths import is_newer
from .compgen_python_classpaths import (
    MODULE_FLAG,
    CALLABLE_FLAG,
    CLASS_FLAG,
    INSTANCE_FLAG,
    SUBCLASS_FLAG,
)

REPEATABLE_ACTIONS = tuple(
    cls
    for cls in vars(argparse).values()
    if isinstance(cls, type)
    and issubclass(cls, Action)
    and ("Count" in cls.__name__ or "Append" in cls.__name__)
)

BASH_COMPLETION_HELPERS_FILENAME = "bourbaki_bash_completion_helpers.sh"
BASH_COMPLETION_FUNC_NAME = "_bourbaki_complete"
COMPLETE_CHOICES_FUNC_NAME = "_bourbaki_complete_choices"
COMPLETE_FILES_FUNC_NAME = "_bourbaki_complete_files"
COMPLETE_CLASSPATHS_FUNC_NAME = "_bourbaki_complete_python_classpaths"
COMPLETE_INTS_FUNC_NAME = "_bourbaki_complete_ints"
COMPLETE_BOOLS_FUNC_NAME = "_bourbaki_complete_bools"
COMPLETE_FLOATS_FUNC_NAME = "_bourbaki_complete_floats"
COMPLETE_KEYVAL_FUNC_NAME = "_bourbaki_complete_keyval"
NO_COMPLETE_FUNC_NAME = "_bourbaki_no_complete"
KEYVAL_SEP = "="
OPTION_SEP = ","
BASH_COMPLETION_TREE_INDENT = "  "

DEFAULT_BASH_COMPLETE_OPTIONS = ("bashdefault", "filenames")
BASH_SHEBANG = "#!/usr/bin/env bash"
BASH_SOURCE_TEMPLATE = "[ -f {} ] && source {}"

BASH_COMPLETION_USER_FILENAME = ".bash_completion"
BASH_COMPLETION_USER_DIRNAME = ".bash_completion.d"
BASH_COMPLETION_FUNCTIONS = dict(
    _filedir="files and directories",
    _signals="signal names",
    _mac_addresses="known mac addresses",
    _configured_interfaces="configured network interfaces",
    _kernel_versions="available kernels",
    _available_interfaces="all available network interfaces",
    _pids="process IDs",
    _pgids="process group IDs",
    _pnames="process names",
    _uids="user IDs",
    _gids="group IDs",
    _usergroup="user or user:group format",
    _services="services",
    _modules="modules",
    _installed_modules="installed modules",
    _shells="valid shells",
    _fstypes="valid filesystem types",
    _pci_ids="PCI IDs",
    _usb_ids="USB IDs",
    _cd_devices="CD device names",
    _dvd_devices="DVD device names",
    _function="shell functions",
    _user_at_host="user@host",
    _known_hosts_real="hosts based on ssh's config and known_hosts",
)


def shellquote(s: str):
    return quote(s)


def install_shell_completion(
    parser: ArgumentParser,
    *commands: str,
    completion_options: Sequence[str] = DEFAULT_BASH_COMPLETE_OPTIONS,
    last_edit_time: Opt[Union[float, str, Path]] = None
):
    completions_file, completions_dir, helpers_file = (
        install_application_shell_completion()
    )
    cmdname = _shortest_identifier(*commands)
    custom_file = os.path.join(completions_dir, cmdname + ".sh")
    custom_file_abs = os.path.expanduser(custom_file)
    completions_file_abs = os.path.expanduser(completions_file)

    if last_edit_time is None or is_newer(last_edit_time, custom_file_abs):
        with open(custom_file_abs, "w") as outfile:
            write_bash_completion_for_parser(
                parser,
                outfile,
                commands=commands,
                completion_options=completion_options,
            )

    custom_source_command = BASH_SOURCE_TEMPLATE.format(custom_file, custom_file)
    _ensure_lines([custom_source_command], completions_file_abs)


def install_application_shell_completion():
    # install the custom function in custom_file in this dir,
    completions_dir = get_user_bash_completion_dir()
    # then source it in here
    completions_file = get_user_bash_completion_path()
    # and also make sure the helpers are up-to-date here
    helpers_file = get_application_bash_completion_helpers_path()
    # only copies if the source version is modified more recently than the extant version
    _install_shell_completion_helpers(helpers_file)
    # ensure the source command is present
    helpers_source_command = BASH_SOURCE_TEMPLATE.format(helpers_file, helpers_file)
    _ensure_lines([helpers_source_command], completions_file)
    return completions_file, completions_dir, helpers_file


class Complete(ABC):
    args = None
    _shell_func_name = None

    def __str__(self):
        if not self.args:
            return self._shell_func_name or ""

        args = map(shellquote, map(str, self.args))
        try:
            if not self._shell_func_name:
                return " ".join(args)
            else:
                return "{} {}".format(self._shell_func_name, " ".join(args))
        except Exception as e:
            warn("Couldn't represent {} as a shell command: {}".format(repr(self), e))

    def __repr__(self):
        return "{}({})".format(self.__class__.__name__, ", ".join(map(repr, self.args)))

    def to_bash_call(self):
        return str(self)


class RawShellFunctionComplete(Complete):
    def __init__(self, shell_function: str, *args: str):
        self._shell_func_name = shell_function
        self.args = args


class FixedShellFunctionComplete(Complete):
    def __init__(self, *args: str):
        self.args = args


class _BashCompletionCompleters:
    """Constuct completers from the `bash_completion` bash module, which are highly developed and heavily tested.
    This uses simple .attribute access using '_'-stripped bash_completion shell function names."""

    def __dir__(self):
        return [name.lstrip("_") for name in BASH_COMPLETION_FUNCTIONS]

    @lru_cache(None)
    def __getattr__(self, item: str):
        func_name = "_" + item
        if func_name not in BASH_COMPLETION_FUNCTIONS:
            warn(
                "'{}' is not registered as a know bash completion function".format(
                    func_name
                )
            )

        # always const, so that cli_completer.register(some_type)(BashCompletion.some_completer_name) just works
        bash_completion_cls = const(RawShellFunctionComplete(func_name))
        return bash_completion_cls


BashCompletion = _BashCompletionCompleters()


class CompleteFiles(Complete):
    _shell_func_name = COMPLETE_FILES_FUNC_NAME

    def __init__(self, *exts: str):
        self.args = tuple(e.lstrip(".") for e in exts)


class CompleteDirs(CompleteFiles):
    def __init__(self):
        # from bash completion docs: "If `-d', complete only on directories"
        super().__init__("-d")


class CompleteFilesAndDirs(CompleteFiles):
    def __init__(self, *exts: str):
        super().__init__("-d", *exts)


class CompletePythonClassPaths(FixedShellFunctionComplete):
    _shell_func_name = COMPLETE_CLASSPATHS_FUNC_NAME

    def __init__(self, *module_prefixes: str):
        super().__init__(*module_prefixes)


class _CompletePythonPathsWithPrefixes(CompletePythonClassPaths):
    _flag = None

    def __init__(self, *prefixes):
        super().__init__(self._flag, *prefixes)


class _CompletePythonPathsWithTypes(CompletePythonClassPaths):
    _flag = None

    def __init__(self, *superclasses):
        super().__init__(
            self._flag,
            *(parameterized_classpath(cls).replace(" ", "") for cls in superclasses)
        )


class CompletePythonClasses(_CompletePythonPathsWithPrefixes):
    _flag = CLASS_FLAG


class CompletePythonModules(_CompletePythonPathsWithPrefixes):
    _flag = MODULE_FLAG


class CompletePythonCallables(_CompletePythonPathsWithPrefixes):
    _flag = CALLABLE_FLAG


class CompletePythonInstances(_CompletePythonPathsWithTypes):
    _flag = INSTANCE_FLAG


class CompletePythonSubclasses(_CompletePythonPathsWithTypes):
    _flag = SUBCLASS_FLAG


class CompleteChoices(FixedShellFunctionComplete):
    _shell_func_name = COMPLETE_CHOICES_FUNC_NAME

    def __init__(self, *choices: str):
        super().__init__(*choices)


class CompleteEnum(CompleteChoices):
    def __init__(self, enum):
        super().__init__(*(e.name for e in enum))


class CompleteInts(FixedShellFunctionComplete):
    _shell_func_name = COMPLETE_INTS_FUNC_NAME


class CompleteBools(FixedShellFunctionComplete):
    _shell_func_name = COMPLETE_BOOLS_FUNC_NAME


class CompleteFloats(FixedShellFunctionComplete):
    _shell_func_name = COMPLETE_FLOATS_FUNC_NAME


class _NoComplete(FixedShellFunctionComplete):
    _shell_func_name = NO_COMPLETE_FUNC_NAME


NoComplete = _NoComplete()


class _MultiComplete(Complete):
    sep = None
    unique = False

    def __init__(self, *completers: Complete):
        self.completers = completers

    def __str__(self):
        collect = set if self.unique else iter
        return self.sep.join(collect(map(str, self.completers)))

    def __repr__(self):
        return "{}{}".format(self.__class__.__name__, repr(tuple(self.completers)))


class CompleteKeyValues(_MultiComplete):
    sep = " {} ".format(KEYVAL_SEP * 3)
    _shell_func_name = COMPLETE_KEYVAL_FUNC_NAME

    def __init__(self, key_completer, val_completer, *args):
        if args:
            warn(
                "got {} extra args for CompleteKeyValues; {} will be ignored".format(
                    len(args), repr(args)
                )
            )
        if key_completer is None:
            key_completer = NoComplete
        if val_completer is None:
            val_completer = NoComplete
        super().__init__(key_completer, val_completer)

    def __str__(self):
        return " ".join([self._shell_func_name, super().__str__()])


class CompleteTuple(_MultiComplete):
    sep = "; "


class CompleteUnion(_MultiComplete):
    sep = " && "
    unique = True


def write_bash_completion_for_parser(
    parser: ArgumentParser,
    file: IO[str],
    commands: Sequence[str],
    completion_options: Opt[Union[str, Sequence[str]]] = None,
    shebang: Opt[str] = BASH_SHEBANG,
):
    if isinstance(commands, str):
        commands = [commands]

    if completion_options:
        optionstr = (
            " -o ".join(completion_options)
            if not isinstance(completion_options, str)
            else completion_options
        )
        optionstr = "-o {} ".format(optionstr)
    else:
        optionstr = ""

    def print_(*line):
        print(*line, file=file)
        print(*line, file=sys.stderr)

    print("WRITING LINES TO {}:".format(file.name), file=sys.stderr)
    if shebang:
        print_(shebang)
    print_("")

    name = _shortest_identifier(*commands)
    completion_funcname = "_complete_{}".format(name)

    print_("{}() {{".format(completion_funcname))
    print_('{} """'.format(BASH_COMPLETION_FUNC_NAME))
    print_cli_def_tree(parser, file=file)
    print_('"""')
    print_("}\n")

    for cmd in commands:
        line = "complete {}-F {} {}".format(optionstr, completion_funcname, cmd)
        print_(line)

    print_()


def print_cli_def_tree(
    parser: Union[ArgumentParser, _SubParsersAction],
    file: IO[str] = sys.stdout,
    indent: str = "",
):
    args, options, commands = gather_args_options_subparsers(parser)

    def print_(*line):
        print(*line, file=file)
        print(*line, file=sys.stderr)

    for a in args:
        print_("{}- {}".format(indent, completion_spec(a, positional=True)))

    for a in options:
        print_(
            "{}{} {}".format(
                indent,
                OPTION_SEP.join(a.option_strings),
                completion_spec(a, positional=False),
            )
        )

    for name, c in commands:
        print_("{}{}".format(indent, name))
        print_cli_def_tree(c, file, indent=indent + BASH_COMPLETION_TREE_INDENT)


def gather_args_options_subparsers(
    parser: ArgumentParser
) -> Tuple[List[Action], List[Action], List[Tuple[str, Action]]]:
    args = []
    options = []
    commands = []
    for action in parser._actions:
        if action.option_strings:
            options.append(action)
        elif isinstance(action, _SubParsersAction):
            if action.choices:
                for tup in action.choices.items():
                    commands.append(tup)
        else:
            args.append(action)

    return args, options, commands


def completion_spec(action: Action, positional=False) -> str:
    if isinstance(action, REPEATABLE_ACTIONS):
        nreps = "+" if action.required else "*"
    elif positional:
        nreps = None
    else:
        nreps = "1" if action.required else "?"

    nargs = action.nargs if action.nargs is not None else 1
    completer = get_completer(action) if nargs != 0 else None
    repstr = "{}{}".format(nargs, "" if nreps is None else "({})".format(nreps))
    return (
        "{} {}".format(repstr, bash_call_str(completer))
        if completer is not None
        else repstr
    )


def get_completer(action: Action) -> Opt[Union[str, List[str], Complete]]:
    if action.choices:
        completer = CompleteChoices(*action.choices)
    else:
        completer = getattr(action, "completer", None)
        if completer is None and action.nargs != 0:
            completer = completer_argparser_from_type(action.type)

    return completer


@singledispatch
def completer_argparser_from_type(t):
    # this handles any user-monkey-patched types with 'completer/_completer' attribute
    return getattr(t, "_completer", getattr(t, "completer", None))


@completer_argparser_from_type.register(FileType)
def completer_from_type_argparse_file(t):
    return CompleteFiles()


@singledispatch
def bash_call_str(completer: Union[str, Complete]):
    return str(completer)


@bash_call_str.register(list)
def bash_call_str_args_list(args):
    return " ".join(map(shellquote, args))


def get_user_bash_completion_path() -> str:
    name = str(Path("~") / BASH_COMPLETION_USER_FILENAME)
    absolute = os.path.expanduser(name)
    if os.path.exists(absolute) and not os.path.isfile(absolute):
        raise FileExistsError(
            "{} is not a file but is required to be by application bash completion"
        )
    elif not os.path.exists(absolute):
        # touch the file
        with open(absolute, "a"):
            pass
    return name


def get_user_bash_completion_dir() -> str:
    name = str(Path("~") / BASH_COMPLETION_USER_DIRNAME)
    absolute = os.path.expanduser(name)
    if not os.path.exists(absolute):
        os.mkdir(absolute)
    elif not os.path.isdir(absolute):
        raise NotADirectoryError(
            "{} is not a directory but is required to be by application bash completion"
        )

    return name


def get_application_bash_completion_helpers_path() -> str:
    completions_dir = get_user_bash_completion_dir()
    return str(Path(completions_dir) / BASH_COMPLETION_HELPERS_FILENAME)


def _shortest_identifier(*commands: str):
    def to_identifier(name):
        return re.sub(r"[^.\w]", "_", name)

    return min(map(to_identifier, commands), key=len)


def _ensure_lines(lines, textfile: str):
    textfile = os.path.expanduser(textfile)
    print("ENSURING LINES ARE PRESENT IN {}:".format(textfile), file=sys.stderr)
    print("\n".join(lines), file=sys.stderr)
    print(file=sys.stderr)
    missing = set(lines)
    present = set()

    if os.path.exists(textfile):
        with open(textfile, "r") as outfile:
            for line in map(str.strip, outfile):
                if line in missing:
                    present.add(line)
                    missing.remove(line)
        # ensure consistent order here
        to_write = [l for l in lines if l in missing]
    else:
        to_write = lines

    if to_write:
        print("WRITING LINES TO {}:".format(textfile), file=sys.stderr)
        with open(textfile, "a") as outfile:
            for line in to_write:
                print(line, file=outfile)
                print(line, file=sys.stderr)
        print(file=sys.stderr)


def _install_shell_completion_helpers(completions_helpers_file):
    source = pkgutil.get_data('bourbaki.application.completion', BASH_COMPLETION_HELPERS_FILENAME).strip()
    completions_helpers_file_absolute = os.path.expanduser(completions_helpers_file)

    with open(completions_helpers_file_absolute, "rb+") as outfile:
        old_source = outfile.read().strip()
        if source != old_source:
            print("REINSTALLING BASH COMPLETION HELPERS AT {}".format(completions_helpers_file_absolute), file=sys.stderr)
            outfile.seek(0)
            outfile.truncate()
            outfile.write(source)
