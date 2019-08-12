# coding:utf-8
from typing import IO, List, Tuple, Sequence, Union, Optional as Opt
from abc import ABC
from argparse import ArgumentParser, Action, FileType, _SubParsersAction
from functools import singledispatch, lru_cache
import os
from pathlib import Path
import re
from shlex import quote
import sys

from bourbaki.introspection.classes import parameterized_classpath

from ..paths import is_newer
from .compgen_python_classpaths import MODULE_FLAG, CALLABLE_FLAG, CLASS_FLAG, INSTANCE_FLAG, SUBCLASS_FLAG


APPUTILS_BASH_COMPLETION_HELPERS_FILENAME = "application_bash_completion_helpers.sh"
APPUTILS_BASH_COMPLETION_FUNC_NAME = "_application_complete"
APPUTILS_COMPLETE_CHOICES_FUNC_NAME = "_application_complete_choices"
APPUTILS_COMPLETE_FILES_FUNC_NAME = "_application_complete_files"
APPUTILS_COMPLETE_CLASSPATHS_FUNC_NAME = "_application_complete_python_classpaths"
APPUTILS_COMPLETE_INTS_FUNC_NAME = "_application_complete_ints"
APPUTILS_COMPLETE_BOOLS_FUNC_NAME = "_application_complete_bools"
APPUTILS_COMPLETE_FLOATS_FUNC_NAME = "_application_complete_floats"
APPUTILS_COMPLETE_UNION_FUNC_NAME = "_application_complete_union"
APPUTILS_NO_COMPLETE_FUNC_NAME = "_application_no_complete"
APPUTILS_BASH_COMPLETION_TREE_INDENT = "  "

DEFAULT_BASH_COMPLETE_OPTIONS = ("bashdefault", "filenames")
BASH_SHEBANG = "#!/usr/bin/env bash"
BASH_SOURCE_TEMPLATE = '[ -f "{}" ] && source {}'

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
    if re.search(r"\s", s):
        return quote(s)
    return s


def _classpath(cls: Union[type, str]):
    return "{}.{}".format(cls.__module__, cls.__qualname__) if isinstance(cls, type) else cls


def install_shell_completion(parser: ArgumentParser, *commands: str,
                             completion_options: Sequence[str]=DEFAULT_BASH_COMPLETE_OPTIONS,
                             last_edit_time: Opt[Union[float, str, Path]]=None):
    completions_file, completions_dir, helpers_file = install_application_shell_completion()
    cmdname = _shortest_identifier(*commands)
    custom_file = os.path.join(completions_dir, cmdname + ".sh")

    if last_edit_time is None or is_newer(last_edit_time, custom_file):
        with open(custom_file, 'w') as outfile:
            write_bash_completion_for_parser(parser, outfile, commands=commands, completion_options=completion_options)

    custom_source_command = BASH_SOURCE_TEMPLATE.format(custom_file, custom_file)
    _ensure_lines([custom_source_command], completions_file)


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
            return self._shell_func_name or ''
        try:
            return "{} {}".format(self._shell_func_name, ' '.join(map(quote, self.args)))
        except Exception as e:
            print(tuple(map(str, self.args)))
            raise e

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
        return [name.lstrip('_') for name in BASH_COMPLETION_FUNCTIONS]

    @lru_cache(None)
    def __getattr__(self, item: str):
        func_name = '_' + item
        bash_completion_cls = type("BashCompletion{}".format(func_name), (FixedShellFunctionComplete,),
                                   dict(_shell_func_name=func_name))
        return bash_completion_cls


BashCompletion = _BashCompletionCompleters()


class CompleteFiles(Complete):
    _shell_func_name = APPUTILS_COMPLETE_FILES_FUNC_NAME

    def __init__(self, *exts: str):
        self.args = tuple(e.lstrip('.') for e in exts)


class CompleteDirs(CompleteFiles):
    def __init__(self):
        # from bash completion docs: "If `-d', complete only on directories"
        super().__init__('-d')


class CompleteFilesAndDirs(CompleteFiles):
    def __init__(self, *exts: str):
        super().__init__('-d', *exts)


class CompletePythonClassPaths(FixedShellFunctionComplete):
    _shell_func_name = APPUTILS_COMPLETE_CLASSPATHS_FUNC_NAME

    def __init__(self, *module_prefixes: str):
        super().__init__(*module_prefixes)


class _CompletePythonPathsWithPrefixes(CompletePythonClassPaths):
    _flag = None

    def __init__(self, *prefixes):
        super().__init__(self._flag, *prefixes)


class _CompletePythonPathsWithTypes(CompletePythonClassPaths):
    _flag = None

    def __init__(self, *superclasses):
        super().__init__(self._flag, *(parameterized_classpath(cls) for cls in superclasses))


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
    _shell_func_name = APPUTILS_COMPLETE_CHOICES_FUNC_NAME

    def __init__(self, *choices: str):
        super().__init__(*choices)


class CompleteEnum(CompleteChoices):
    def __init__(self, enum):
        super().__init__(*(e.name for e in enum))


class CompleteInts(FixedShellFunctionComplete):
    _shell_func_name = APPUTILS_COMPLETE_INTS_FUNC_NAME


class CompleteBools(FixedShellFunctionComplete):
    _shell_func_name = APPUTILS_COMPLETE_BOOLS_FUNC_NAME


class CompleteFloats(FixedShellFunctionComplete):
    _shell_func_name = APPUTILS_COMPLETE_FLOATS_FUNC_NAME


class _NoComplete(FixedShellFunctionComplete):
    _shell_func_name = APPUTILS_NO_COMPLETE_FUNC_NAME


NoComplete = _NoComplete()


class CompleteUnion(FixedShellFunctionComplete):
    _shell_func_name = APPUTILS_COMPLETE_UNION_FUNC_NAME

    def __init__(self, *completers: Complete):
        self.completers = completers
        super().__init__(*map(repr, map(str, completers)))


def write_bash_completion_for_parser(parser: ArgumentParser, file: IO[str], commands: Sequence[str],
                                     completion_options: Opt[Union[str, Sequence[str]]]=None,
                                     shebang: Opt[str]=BASH_SHEBANG):
    if isinstance(commands, str):
        commands = [commands]

    if completion_options:
        optionstr = ' -o '.join(completion_options) if not isinstance(completion_options, str) else completion_options
        optionstr = '-o {} '.format(optionstr)
    else:
        optionstr = ''

    def print_(*line):
        print(*line, file=file)
        print(*line, file=sys.stderr)

    print("WRITING LINES TO {}:".format(file.name), file=sys.stderr)
    if shebang:
        print_(shebang)
    print_('')

    name = _shortest_identifier(*commands)
    completion_funcname = "_complete_{}".format(name)

    print_('{}() {{'.format(completion_funcname))
    print_('{} """'.format(APPUTILS_BASH_COMPLETION_FUNC_NAME))
    print_cli_def_tree(parser, file=file)
    print_('"""')
    print_("}\n")

    for cmd in commands:
        line = "complete {}-F {} {}".format(optionstr, completion_funcname, cmd)
        print_(line)

    print_()


def print_cli_def_tree(parser: Union[ArgumentParser, _SubParsersAction],
                       file: IO[str]=sys.stdout, indent: str=''):
    args, options, commands = gather_args_options_subparsers(parser)
    def print_(*line):
        print(*line, file=file)
        print(*line, file=sys.stderr)

    for a in args:
        print_('{}- {}'.format(indent, completion_spec(a)))

    for a in options:
        for o in a.option_strings:
            print_('{}{} {}'.format(indent, o, completion_spec(a)))

    for name, c in commands:
        print_("{}{}".format(indent, name))
        print_cli_def_tree(c, file, indent=indent + APPUTILS_BASH_COMPLETION_TREE_INDENT)


def gather_args_options_subparsers(parser: ArgumentParser) -> \
        Tuple[List[Action], List[Action], List[Tuple[str, Action]]]:
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


def completion_spec(action: Action) -> str:
    nargs = action.nargs if action.nargs is not None else 1
    completer = get_completer(action)
    return "{} {}".format(nargs, bash_call_str(completer)) if completer is not None else str(nargs)


def get_completer(action: Action) -> Union[str, Complete]:
    completer = getattr(action, "completer", None)
    if completer is None:
        if action.choices:
            completer = CompleteChoices(*action.choices)
        elif action.nargs != 0:
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
    return ' '.join(map(shellquote, args))


def get_application_completions_helper_path() -> str:
    completions_dir = get_user_bash_completion_dir()
    return os.path.join(completions_dir, APPUTILS_BASH_COMPLETION_HELPERS_FILENAME)


def get_user_bash_completion_path() -> str:
    name = os.path.expanduser(str(Path("~") / BASH_COMPLETION_USER_FILENAME))
    if os.path.exists(name) and not os.path.isfile(name):
        raise FileExistsError("{} is not a file but is required to be by application bash completion")
    elif not os.path.exists(name):
        # touch the file
        with open(name, 'a'):
            pass
    return name


def get_user_bash_completion_dir() -> str:
    name = os.path.expanduser(str(Path("~") / BASH_COMPLETION_USER_DIRNAME))
    if not os.path.exists(name):
        os.mkdir(name)
    elif not os.path.isdir(name):
        raise NotADirectoryError("{} is not a directory but is required to be by application bash completion")

    return name


def get_application_bash_completion_helpers_path() -> str:
    completions_dir = get_user_bash_completion_dir()
    return os.path.expanduser(str(Path("~") / completions_dir / APPUTILS_BASH_COMPLETION_HELPERS_FILENAME))


def _shortest_identifier(*commands: str):
    def to_identifier(name):
        return re.sub(r'[^.\w]', '_', name)

    return min(map(to_identifier, commands), key=len)


def _ensure_lines(lines, textfile: str):
    print("ENSURING LINES ARE PRESENT IN {}:".format(textfile), file=sys.stderr)
    print("\n".join(lines), file=sys.stderr)
    print(file=sys.stderr)
    missing = set(lines)
    present = set()

    if os.path.exists(textfile):
        with open(textfile, 'r') as outfile:
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
    source = os.path.join(os.path.dirname(__file__), APPUTILS_BASH_COMPLETION_HELPERS_FILENAME)

    if not os.path.exists(completions_helpers_file):
        msg = "INSTALLING APPUTILS COMPLETION HELPERS in {}"
    elif os.stat(source).st_mtime > os.stat(completions_helpers_file).st_mtime:
        # probably a new version; should be updated
        msg = "REINSTALLING APPUTILS COMPLETION HELPERS in {}"
    else:
        return

    print(msg.format(completions_helpers_file), file=sys.stderr)
    with open(source, "r") as infile:
        with open(completions_helpers_file, "w") as outfile:
            for line in infile:
                outfile.write(line)
