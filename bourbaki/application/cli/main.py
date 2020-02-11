# coding:utf-8
from typing import Iterator, Union, Tuple, Mapping, List, Set, Callable, Optional as Opt
import os
import sys
import shlex
import shutil
import operator
from pathlib import Path
from itertools import chain, repeat
from warnings import warn, filterwarnings
from collections import OrderedDict, ChainMap
from logging import Logger, DEBUG, _levelToName, getLogger
from functools import lru_cache
from inspect import Signature, Parameter
from argparse import (
    ArgumentParser,
    Namespace,
    RawDescriptionHelpFormatter,
    ONE_OR_MORE,
    ZERO_OR_MORE,
    SUPPRESS,
    _SubParsersAction,
)
from cytoolz import identity, get_in
from typing_inspect import is_generic_type

from bourbaki.introspection.classes import classpath, most_specific_constructor
from bourbaki.introspection.types import (
    deconstruct_generic,
    reconstruct_generic,
    get_param_dict,
    get_generic_origin,
    is_optional_type,
)
from bourbaki.introspection.typechecking import isinstance_generic
from bourbaki.introspection.docstrings import parse_docstring, CallableDocs

# callables.signature is an lru_cache'ed inspect.signature
from bourbaki.introspection.callables import (
    fully_concrete_signature,
    funcname,
    is_method,
)
from ..completion.completers import CompleteFiles, install_shell_completion
from ..logging import configure_default_logging, Logged, ProgressLogger
from ..logging.helpers import validate_log_level_int
from ..logging.defaults import PROGRESS, ERROR, INFO, DEFAULT_LOG_MSG_FMT
from ..config import load_config, dump_config, ConfigFormat, LEGAL_CONFIG_EXTENSIONS
from ..typed_io.utils import (
    to_cmd_line_name,
    get_dest_name,
    Missing,
    ellipsis_,
    text_path_repr,
)
from ..typed_io import TypedIO, ArgSource
from .actions import (
    InfoAction,
    PackageVersionAction,
    InstallShellCompletionAction,
    SetExecuteFlagAction,
)
from .helpers import (
    _help_kwargs_from_docs,
    _combined_cli_sig,
    _type,
    _validate_lookup_order,
    get_task,
    NamedChainMap,
    strip_command_prefix,
    update_in,
    VARIADIC_NARGS,
)
from .decorators import cli_attrs, NO_OUTPUT_HANDLER
from .signatures import CLISignatureSpec, FinalCLISignatureSpec

# only need to parse docs once for any function
parse_docstring = lru_cache(None)(parse_docstring)

LOG_LEVEL_NAMES = ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"]
SUBCOMMAND_ATTR = "subcommand"
SUBCOMMAND_PATH_ATTR = "subcommand_path"
CONFIG_FILE_ATTR = "config_file"
LOGFILE_ATTR = "logfile"
VERBOSITY_ATTR = "verbosity"
QUIET_ATTR = "quiet"
RESERVED_NAMESPACE_ATTRS = (
    CONFIG_FILE_ATTR,
    LOGFILE_ATTR,
    VERBOSITY_ATTR,
    QUIET_ATTR,
    SUBCOMMAND_ATTR,
    SUBCOMMAND_PATH_ATTR,
)
OUTPUT_GROUP_NAME = "output control"
OPTIONAL_ARG_TEMPLATE = "{}??"
MIN_VERBOSITY = 1
DEFAULT_EXECUTION_FLAG = "-x"
INSTALL_SHELL_COMPLETION_FLAG = "--install-bash-completion"
CONFIG_OPTION = "--config"
VERBOSE_FLAGS = ("-v", "--verbose")
QUIET_FLAGS = ("--quiet", "-q")
EXECUTE = False
DEFAULT_LOOKUP_ORDER = (
    ArgSource.CLI,
    ArgSource.ENV,
    ArgSource.CONFIG,
    ArgSource.DEFAULTS,
)


# exceptions


class ReservedNameError(AttributeError):
    def __init__(self, reserved, what_names, which_lookup):
        self.args = (
            "attributes {} are reserved in the parsed argument namespace; {} has attributes {}".format(
                reserved, which_lookup, what_names
            ),
        )


class RepeatedCLIKeywordArgs(ValueError):
    def __init__(self, overlap, kwargs_name):
        super().__init__(overlap, kwargs_name)

    def __str__(self):
        return "Got multiple values for keyword args {}; repeated values came from variadic option '{}'".format(
            self.args[0], self.args[1]
        )


class AmbiguousSignature(TypeError):
    pass


class CLIDefinitionWarning(UserWarning):
    pass


def setup_warn(msg):
    warn(msg, category=CLIDefinitionWarning)


# custom formatters


class WideHelpFormatter(RawDescriptionHelpFormatter):
    def __init__(self, prog, indent_increment=2, max_help_position=40, width=None):
        if width is None:
            width = shutil.get_terminal_size().columns
        super().__init__(
            prog,
            indent_increment=indent_increment,
            max_help_position=max_help_position,
            width=width,
        )


# The main CLI class and helpers


class _SubparserPathAction(_SubParsersAction):
    cmd_prefix = ()

    def add_parser(self, name: str, **kwargs) -> ArgumentParser:
        parser = super().add_parser(name, **kwargs)
        parser.cmd_prefix = (*self.cmd_prefix, name)
        return parser

    def __call__(self, parser, namespace, values, option_string, **kwargs):
        cmd = values[0]
        path = (*self.cmd_prefix, cmd)
        setattr(namespace, SUBCOMMAND_PATH_ATTR, path)
        super(_SubparserPathAction, self).__call__(
            parser, namespace, values, option_string, **kwargs
        )


class PicklableArgumentParser(ArgumentParser):
    cmd_prefix = ()

    def __init__(self, *args, **kwargs):
        kwargs["formatter_class"] = WideHelpFormatter
        super().__init__(*args, **kwargs)
        # ArgumentParser won't pickle, we have to override its registry here
        self.register("type", None, identity)
        self.register("action", "parsers", _SubparserPathAction)

    def add_subparsers(self, *args, **kwargs) -> _SubparserPathAction:
        subparsers = super().add_subparsers(*args, **kwargs)
        subparsers.cmd_prefix = self.cmd_prefix
        return subparsers

    @property
    def has_subparsers(self):
        return self._subparsers is not None

    @property
    def subparsers(self):
        if self.has_subparsers:
            return self._subparsers_action
        subparsers = self.add_subparsers(
            dest=SUBCOMMAND_ATTR, parser_class=PicklableArgumentParser
        )
        self._subparsers_action = subparsers
        return subparsers

    def get_nested_subparser(self, *cmd_path: str):
        if not cmd_path:
            return self

        cmdname = cmd_path[0]
        subparsers = self.subparsers
        if subparsers.choices and cmdname in subparsers.choices:
            subparser = subparsers.choices[cmdname]
        else:
            subparser = subparsers.add_parser(cmdname)

        return subparser.get_nested_subparser(*cmd_path[1:])


class CommandLineInterface(PicklableArgumentParser, Logged):
    """
    Subclass of argparse.ArgumentParser which infers command line interfaces and documentation from functions and
    classes. Type annotations determine parsers for command line args and configuration values, and
    Also adds some functionality to ease use of logging, configuration, verbosity, and dry-run execution.
    """

    lookup_order = ()
    subcommands = None
    init_config_command = None
    app_cls = None
    reserved_attrs = frozenset(RESERVED_NAMESPACE_ATTRS)
    _builtin_commands_added = False
    _unsafe_pickle_attrs = frozenset(
        (
            "source_file",
            "helper_files",
            "default_logfile",
            "default_configfile",
            "_pickle_load_path",
            "_pickle_dump_path",
            "_last_edit_time",
            "_source_files",
        )
    )
    reserved_command_names = None
    _subparsers_action = None
    _main = None
    parsed = None
    _source_files = None
    _last_edit_time = Missing
    _pickle_load_path = None
    _pickle_dump_path = None

    def __init__(
        self,
        *,  # <- require keyword args
        # CLI settings
        require_options: bool = True,
        require_subcommand=False,
        implicit_flags: bool = False,
        default_metavars: Opt[Mapping[str, str]] = None,
        long_desc_as_epilog: bool = True,
        # config settings
        use_config_file: Union[bool, str] = False,
        require_config: bool = False,
        use_subconfig_for_commands: bool = True,
        parse_config_as_cli: Union[bool, str, Set[str]] = False,
        # logging
        use_logfile: Union[bool, str] = False,
        log_msg_fmt: str = DEFAULT_LOG_MSG_FMT,
        dated_logfiles: bool = False,
        logger_cls: type = ProgressLogger,
        # logging and config path locations
        default_paths_relative_to_source=False,
        # I/O
        arg_lookup_order: Tuple[ArgSource, ...] = DEFAULT_LOOKUP_ORDER,
        ignore_function_defaults: bool = False,
        typecheck: bool = False,
        output_handler: Opt[Callable] = None,
        # special features and flags
        use_multiprocessing: bool = False,
        install_bash_completion: bool = False,
        use_verbose_flag: bool = False,
        use_quiet_flag: bool = False,
        use_execution_flag: Union[bool, str, Tuple[str, ...]] = False,
        add_install_bash_completion_flag: Union[bool, str] = True,
        add_init_config_command: Union[bool, str, Tuple[str, ...]] = False,
        suppress_setup_warnings: bool = False,
        # source files
        source_file: Opt[str] = None,
        helper_files: Opt[List[str]] = None,
        # info actions
        version: Opt[Union[str, bool]] = None,
        package: Opt[str] = None,
        package_info_keys: Opt[Union[str, Tuple[str, ...]]] = None,
        # argparse.ArgumentParser init args from here; defaults should be fine in most cases
        prog: Opt[str] = None,
        usage: Opt[str] = None,
        description: Opt[str] = None,
        epilog: Opt[str] = None,
        parents=(),
        formatter_class=WideHelpFormatter,
        conflict_handler: Opt[str] = "error",
        add_help: bool = True,
        allow_abbrev: bool = True,
    ):
        """
        :param require_options: bool. Should all args be required to be passed from the CLI with an --optional arg,
            (True) or should positional args to functions be interpreted as positional args on the command line (False)?
            The default is True, as this tends to be less error prone and allows more flexibility. If you would like
            positional args however, in functions that do not accept *args, be sure to insert a bare '*' in the
            signature before any args which you would like to be --options.
        :param require_subcommand: Should the app require a subcommand to be passed? The default is False, as this is
            the behavior for simple apps that don't define subcommands. If you are using CommandLineInterface.definition
            on a class however, you should pass True.
        :param implicit_flags: Should boolean non-positional arguments always be interpreted as 0-arg command line
            --flags? In this case, an arg with a False default will be True on passing the flag from the CLI, and an arg
            with a True default will be False on passing the flag. Note however that in this latter case, a '--no-' will
            be prepended to the command line flag to improve readability and semantics.
            Note that when `require_options` is True, there are no positional args on the command line, so all
            bool-typed args are treated as flags when `implicit_flags` is True.
        :param default_metavars: optional mapping of str -> str. If this is passed, metavars for the command line help
            string are defined by first checking this mapping for the names of function args to be represented before
            falling back to the default `application.typed_io.TypedIO.cli_repr` of the type annotation. To control this
            behavior at the individual function level, use the `application.cli.cli_spec.metavars` decorator or the
            `metavars` arg to `CommandLineInterface.main` or `CommandLineInterface.subcommand`.
        :param long_desc_as_epilog: bool. When True (the default), the `description` arg for argument parsers is defined
            from the "short description" of a function or class, i.e. the portion of the docstring that ends before the
            first double line break, while the `epilog` arg is defined from the "long description" (the part of the
            docstring after the first double line break and before any :param ...: sections. When False, the `epilog`
            arg is always excluded, and the `description` is defined from a concatenation of the long and short
            descriptions.

        :param use_config_file: bool or str. If True, this indicates that a config file can be specified at the command
            line. If a str, this is treated as the default configuration file.
            (see `default_paths_relative_to_source` for path resolution semantics)
        :param require_config: bool. If True, a config file is always required. When `use_config_file` is not a str,
            this implies that a --config file will always be a required arg on the command line.
        :param use_subconfig_for_commands: Should each command get its own subsection in the config, named for the
            function it was defined from? Default is True. If False, you may specify custom subsections for commands by
            using the `application.cli.cli_spec.config_subsections` decorator or directly via the `config_subsections` arg
            to the `CommandLineInterface.main` and `CommandLineInterface.subcommand` decorators; otherwise all args for
            all commands will be taken from the top level namespace of the config.
        :param parse_config_as_cli: bool or set of str. If True, all config values will be parsed with the same parsers
            used on the command line. As configuration is usually a more flexible format than the command line, this is
            hardly ever what you want. If you wish to use the command line parsers for config for a specific set of
            named arguments, pass the set of names, and for all functions that use args with those names, configuration
            values will be parsed using their corresponding CLI parsers.
            Alternately, to control this at the function level, use the `application.cli.cli_spec.parse_config_as_cli`
            decorator or the `parse_config_as_cli` arg of `CommandLineInterface.main` and
            `CommandLineInterface.subcommand` when registering individual functions.

        :param use_logfile: bool or str. If True, a --logfile option will be added to the CLI with no default. If a str,
            a --logfile option will be added to the CLI with this as the default.
            (see `default_paths_relative_to_source` for path resolution semantics)
        :param log_msg_fmt: pass-through to `application.logging.config.configure_default_logging`. The format of logging
            output as understood by the standard library `logging` module.
        :param dated_logfiles: pass-through to `application.logging.config.configure_default_logging`. Should the
            ISO-formatted current datetime be appended to the log file name?
        :param logger_cls: The class to use for all logging. The default is `application.logging.ProgressLogger`.

        :param default_paths_relative_to_source: When this is True (default False), paths supplied for `use_logfile`
            and `use_config_file` are treated as being specified relative to `source_file` (when not absolute or
            relative to $HOME). In this case at parse time, if no command line args are passed for these, the path used
            is expanded to an absolute path, relative to `source_file`. The primary goal of this is to increase
            portability between different environments.

        :param arg_lookup_order: tuple of application.cli.ArgSource enums specifying where args to the executed command
            should be looked up, with earlier entries having higher precedence. Allows the namespace of a configuration
            file or os.environ to populate the args. Default is (CLI, ENV, CONFIG). If CLI is not in the tuple it will
            be inserted as the first entry.
        :param ignore_function_defaults: should function defaults be used as a fallback when values aren't found in any
            input sources (CLI, environment, config)? Default is False, in which case arg_lookup_order will have
            ArgSource.DEFAULTS appended before being set to the .lookup_order attribute in case it isn't present already.

        :param typecheck: bool. Should all parsed args be type-checked before the registered command function is called
            with them? Default is False. Specific args can be typchecked selectively by using the
            `application.cli.typecheck` decorator on registered functions, or passing a list to the `typecheck` arg of
            `CommandLineInterface.main` or `CommandLineInterface.subcommand`.
        :param output_handler: optional callable. Should take the return value of the invoked command/function and
            perform (usually) some IO action on it, such as saving it to disk. The return value is passed as the first
            argument and any further args will be supplied as keyword args parsed from the CLI or config.
        :param use_multiprocessing: bool. If your app uses multiprocessing, then logging will be configured to reflect
            that fact, using appropriate process-safe loggers and handlers. This is passed through to
            `application.logging.config.configure_default_logging` via the `multiprocessing` keyword arg.
        :param install_bash_completion: bool. If True, shell completions are installed automatically at the end of
            interface inference in a `CommandLineInterface.definition` decorator call, if the source file(s) have
            changed more recently than the completion definition files or the completion definition files don't yet
            exist. If you are registering individual functions with `CommandLineInterface.main` or
            `CommandLineInterface.subcommand`, this option has no effect, since it is unknown when the CLI definition
            is complete. In that case, you can manually call `CommandLineInterface.install_shell_completion` in your
            script. Also see `add_install_bash_completion_flag`.
        :param use_verbose_flag: bool. If passed, a flag is added to the command line interface using the option strings
            `application.cli.VERBOSE_FLAGS` which may be repeated to increase verbosity. This affects verbosity by
             decreasing the logging level by 10 for every repetition. At the DEBUG level (usually 4 repetitions),
             the log format also changes to reflect more information, such as source files and line numbers.
        :param use_quiet_flag: bool. If passed, a flag is added to the command line interface using the option strings
            `application.cli.QUIET_FLAGS` with the effect that when the flag is passed, console logging is suppressed.
        :param use_execution_flag: bool or str. When True or a str, a flag is added to the command line interface which
            is interpreted as specifying that file-system-altering actions may be carried out, with the default behavior
            being to skip these actions, possibly with verbose reporting as in a "dry-run" scenario. Your application
            code may look up the status of this flag via `from application import cli; if cli.EXECUTE: ...` to determine
            what action to take. The only effect that is determined by this class is that file logging is suppressed
            when the flag is passed.
        :param add_install_bash_completion_flag: bool or str. If True or a str, a flag is added to the command line
            interface which triggers installation of bash completions when it is passed. If a str, that flag is equal to
            this arg, else the default flag is `application.cli.INSTALL_SHELL_COMPLETION_FLAG`. Note that the
            'bash-completion' package may need to be installed for your OS for some completions to work; see the
            documentation for `application.completion` for more details.
        :param add_init_config_command: bool or str. When True or a str, a command is added to the command line
            interface which wraps `application.CommandLineInterface.init_config`. This command writes an empty
            configuration file (or dir) for your command line interface that can then be manually edited and passed
            to the --config option when that option is available. See `application.CommandLineInterface.init_config` for
            more details.

        :param suppress_setup_warnings: bool. During processing of these args and inference of the interface from
            annotations and docstrings, some warnings may arise. To suppress these, pass True.

        :param source_file: str, the path to the source where the CLI is defined. This can be accessed simply with the
            module-level variable __file__. This is used to determine last edit time for installation of bash completion
            or caching/inflation of the CLI to/from a pickle. E.g. if automatic installation  of shell completion was
            specified and the source was edited, the shell completions will be reinstalled.
            The base name of this file will also be completed when `install_shell_completion` is True or
            `add_install_bash_completion_flag` is True, upon installation of shell completions.
        :param helper_files: list of str. Any source files which the CLI definition source file imports from, and whose
            edit should trigger repetition of edit-sensitive operations. I.e. this arg serves the same purpose as
            source_file but allows tracking edits in other dependencies.

        :param version: optional str or bool. If str, a --version flag is added that triggers the argparse print version
            action. If bool and `package` is passed, a --version flag is added that prints the version as inferred from
            the passed package.
        :param package_info_keys: optional list of str. When `package` is passed, specifies a subset of the package
            metadata keys to display in the terminal when the --info flag is passed.
        :param package: optional str. If passed, an --info flag is added that prints the metadata for the package as
            found by `pkginfo.get_distribution` and parsed by `pkg_resources.Distribution`. The metadata is printed to
            the terminal in YAML format.

        :param prog: see argparse.ArgumentParser.
            Pass this when `install_shell_completion` is True or `add_install_bash_completion_flag` is True, to specify
            the command name that should be completed.
        :param usage: see argparse.ArgumentParser. This should usually not be passed as it will be informatively
            auto-generated from the registered main function signature.
        :param description: see argparse.ArgumentParser. When no explicitly passed, this is inferred from the docstring
            of the decorated class when `CommandLineInterface.definition` is used, or from the docstring of the
            decorated function when `CommandLineInterface.main` is used. In both cases, this is the "short description",
            i.e. all of the documentation that occurs before the first double line break.
        :param epilog: see argparse.ArgumentParser.  Like `description`, but comes from the "long description" when not
            explicitly passed, i.e. all of the documentation that occurs after the first double line break.

        :param parents: see argparse.ArgumentParser
        :param formatter_class: see argparse.ArgumentParser. We use a custom class `WideHelpFormatter` by default, which
            auto-detects the terminal width and formats the help string to fill it.
        :param conflict_handler: see argparse.ArgumentParser. Default is 'error'
        :param add_help: see argparse.ArgumentParser; default True.
        :param allow_abbrev: see argparse.ArgumentParser; default True.
        """

        super().__init__(
            prog=prog,
            usage=usage,
            description=description,
            epilog=epilog,
            parents=parents,
            prefix_chars="-",
            fromfile_prefix_chars=None,
            argument_default=SUPPRESS,
            formatter_class=formatter_class,
            conflict_handler=conflict_handler,
            add_help=add_help,
            allow_abbrev=allow_abbrev,
        )

        if suppress_setup_warnings:
            filterwarnings("ignore", category=CLIDefinitionWarning)

        if install_bash_completion or add_install_bash_completion_flag:
            if not prog:
                raise ValueError(
                    "prog (the program name) must be supplied if "
                    "add_install_bash_completion_flag/install_bash_completion=True"
                )

        if output_handler is not None and not callable(output_handler):
            raise TypeError(
                "output_handler must be callable; got {}".format(type(output_handler))
            )

        if isinstance(helper_files, str):
            helper_files = (helper_files,)
        elif helper_files is not None:
            helper_files = tuple(map(str, helper_files))

        if not isinstance(logger_cls, _type) or not issubclass(logger_cls, Logger):
            raise TypeError(
                "logger_cls must be a subclass of {}; got {}".format(Logger, logger_cls)
            )

        # make a mutable set to we can remove reserved namespace attributes as needed
        self.reserved_attrs = set(RESERVED_NAMESPACE_ATTRS)

        if use_verbose_flag:
            self._add_argument(
                *VERBOSE_FLAGS,
                action="count",
                dest=VERBOSITY_ATTR,
                default=MIN_VERBOSITY,
                help="specify the level of verbosity; repeat the flag to increase",
            )
        else:
            self.reserved_attrs.remove(VERBOSITY_ATTR)

        if use_quiet_flag:
            self._add_argument(
                *QUIET_FLAGS,
                action="store_true",
                dest=QUIET_ATTR,
                default=False,
                help="pass this flag to suppress logging to stdout; "
                "This does not effect the verbosity level",
            )
        else:
            self.reserved_attrs.remove(QUIET_ATTR)

        if isinstance(use_logfile, str):
            default_logfile = use_logfile
        else:
            default_logfile = None

        if use_logfile:
            # this will never be a required arg; if not found in config and not given a default in this init,
            # it will default to None, which logging will handle by not configuring a file handler
            self._add_argument(
                "--logfile",
                action="store",
                type=str,
                default=None,
                dest=LOGFILE_ATTR,
                help="path to a file to write logs to",
                completer=CompleteFiles("txt", "log"),
            )
        else:
            self.reserved_attrs.remove(LOGFILE_ATTR)

        if isinstance(use_config_file, str):
            default_configfile = use_config_file
        else:
            default_configfile = None

        if use_config_file or require_config:
            _help = "path to a file to read configuration from"
            if require_config and not isinstance(default_configfile, str):
                kw = dict(required=True)
            else:
                kw = dict(default=None)

            if isinstance(default_configfile, str):
                _help = _help + "; default '{}'.".format(default_configfile)

            self._add_argument(
                CONFIG_OPTION,
                type=str,
                dest=CONFIG_FILE_ATTR,
                help=_help,
                metavar=text_path_repr,
                completer=CompleteFiles(*LEGAL_CONFIG_EXTENSIONS),
                **kw,
            )
        else:
            self.reserved_attrs.remove(CONFIG_FILE_ATTR)

        if arg_lookup_order:
            self.lookup_order = _validate_lookup_order(
                *arg_lookup_order, include_defaults=not ignore_function_defaults
            )

        if use_execution_flag:
            if isinstance(use_execution_flag, str):
                execution_flag = (use_execution_flag,)
            elif isinstance(use_execution_flag, bool):
                execution_flag = (DEFAULT_EXECUTION_FLAG,)
            else:
                # assume tuple of str
                execution_flag = tuple(use_execution_flag)

            self._add_argument(*execution_flag, action=SetExecuteFlagAction)
        else:
            global EXECUTE
            EXECUTE = True

        if package is not None:
            if version is not None and not isinstance(version, bool):
                setup_warn(
                    "both package and version were passed explicitly; the given version will be used rather "
                    "than the version parsed from package info"
                )
                self.add_argument("--version", action="version", version=version)
            elif version or version is None:
                if version is None:
                    version = True
                self.add_argument(
                    "--version",
                    action=PackageVersionAction,
                    package=package,
                    version=version,
                )
            self.add_argument(
                "--info",
                action=InfoAction,
                package=package,
                version=version,
                info_keys=package_info_keys,
            )
        elif version is not None:
            if isinstance(version, bool):
                setup_warn(
                    "version={} was passed but no package name was passed; no version can be inferred".format(
                        version
                    )
                )
            else:
                self.add_argument("--version", action="version", version=version)

        if add_install_bash_completion_flag:
            flag = (
                add_install_bash_completion_flag
                if isinstance(add_install_bash_completion_flag, str)
                else INSTALL_SHELL_COMPLETION_FLAG
            )
            self._add_argument(flag, action=InstallShellCompletionAction)

        self.version = version
        self.package = package

        self.default_paths_relative_to_source = bool(default_paths_relative_to_source)

        self.use_logfile = bool(use_logfile)
        self.dated_logfiles = bool(dated_logfiles)
        self.default_logfile = default_logfile
        self.log_msg_fmt = log_msg_fmt
        self.app_logger_cls = logger_cls

        self.use_config = (
            bool(use_config_file)
            or bool(require_config)
            or bool(add_init_config_command)
        )
        self.use_subconfig_for_commands = bool(use_subconfig_for_commands)
        self.require_config = bool(require_config)
        self.default_configfile = default_configfile

        self.parse_config_as_cli = parse_config_as_cli
        self.typecheck = typecheck
        self.output_handler = output_handler
        self.require_options = bool(require_options)

        self.use_multiprocessing = bool(use_multiprocessing)
        self.use_execution_flag = bool(use_execution_flag)
        self.require_subcommand = bool(require_subcommand)
        self.implicit_flags = bool(implicit_flags)
        self.default_metavars = (
            None if default_metavars is None else dict(default_metavars)
        )
        self.long_desc_as_epilog = bool(long_desc_as_epilog)

        self.source_file = source_file
        if source_file is not None:
            self.source_dir = os.path.dirname(source_file)
        else:
            self.source_dir = None
        self.helper_files = helper_files
        self._bash_completion = bool(install_bash_completion)
        self.use_init_config_command = bool(add_init_config_command)
        self.subcommands = {}
        self.reserved_command_names = set()
        self._builtin_commands_added = False
        self.suppress_setup_warnings = bool(suppress_setup_warnings)

        self.default_signature_spec = CLISignatureSpec(
            parse_config_as_cli=self.parse_config_as_cli,
            ignore_on_cmd_line=False if ArgSource.CLI in self.lookup_order else True,
            ignore_in_config=False if ArgSource.CONFIG in self.lookup_order else True,
            typecheck=self.typecheck,
            metavars=self.default_metavars,
            require_options=self.require_options,
        )
        if output_handler is None:
            self.default_output_signature_spec = None
        else:
            self.default_output_signature_spec = CLISignatureSpec.from_callable(
                output_handler
            ).overriding(
                self.default_signature_spec
            )  # defaults available for fallback

        if self.use_config and ArgSource.CONFIG not in self.lookup_order:
            setup_warn(
                "use of configuration was specified with at least one of use_config,"
                "require_config, or add_init_config_command, but {} is not in lookup_order; "
                "no value can ever be parsed from configuration in that instance".format(
                    ArgSource.CONFIG
                )
            )

        if self.use_init_config_command:
            if isinstance(add_init_config_command, bool):
                self.init_config_command = tuple(self.init_config.__name__.split("_"))
            else:
                if isinstance(add_init_config_command, str):
                    add_init_config_command = (add_init_config_command,)

                self.init_config_command = tuple(
                    map(to_cmd_line_name, add_init_config_command)
                )

            self.reserved_command_names.add(self.init_config_command)

    def add_builtin_commands(self):
        if self._builtin_commands_added:
            return

        if self.use_init_config_command:
            self.subcommand(
                name=self.init_config_command[-1],
                command_prefix=self.init_config_command[:-1],
                output_handler=self.dump_config,
                implicit_flags=self.implicit_flags,
                ignore_on_cmd_line=False,
                ignore_in_config=True,
                config_subsections=False,
                from_method=False,
                _builtin=True,
            )(self.init_config)

            path, subcommand = self.get_subcommand_func(self.init_config_command)

            commands_args = [
                a
                for a in subcommand.parser._actions
                if a.dest in ("only_commands", "omit_commands")
            ]
            for arg in commands_args:
                if arg.choices is None:
                    arg.choices = set()
                arg.choices.update(
                    map(
                        " ".join,
                        filter(
                            bool,
                            self.all_subcommand_names(
                                include_prefixes=True,
                                filter_=lambda cmd: bool(cmd.config_subsections),
                            ),
                        ),
                    )
                )
                arg.metavar = "CMD-NAME"
                choices_str = (
                    "{{{}}}".format(",".join(map(shlex.quote, sorted(arg.choices))))
                    if arg.choices
                    else None
                )
                help = (
                    arg.help[arg.help.index(":") + 1 :]
                    if arg.help and ":" in arg.help
                    else arg.help
                )
                arg.help = ": ".join(s for s in (choices_str, help) if s)

        self._builtin_commands_added = True
        return self

    def add_argument(self, *args, completer=None, **kwargs):
        dest = kwargs.get("dest", get_dest_name(args, self.prefix_chars))

        if dest in self.reserved_attrs:
            raise KeyError(
                "cannot add arg with options {}; namespace destination '{}' is a reserved namespace "
                "attribute for this parser".format(args, dest)
            )

        return self._add_argument(*args, completer=completer, **kwargs)

    def _add_argument(self, *args, completer=None, **kwargs):
        action = super().add_argument(*args, **kwargs)
        if completer is not None:
            action.completer = completer

        return action

    def _set_subcommand(self, *cmd_path: str, subcommand: "SubCommandFunc"):
        cmds = self.subcommands
        for name in cmd_path[:-1]:
            if name not in cmds:
                cmds[name] = None, {}
            _, cmds = cmds[name]

        cmd_name = cmd_path[-1]
        prior_subcmd, prior_subcmds = cmds.get(cmd_name, (None, {}))
        if prior_subcmd is not None and prior_subcmd is not subcommand:
            raise NameError(
                "command {} is already registered to {}".format(cmd_path, prior_subcmd)
            )

        cmds[cmd_name] = subcommand, prior_subcmds

    @property
    def default_prefix_char(self):
        return "-" if "-" in self.prefix_chars else self.prefix_chars[0]

    @property
    def cmd_name(self):
        return self.prog or os.path.split(sys.argv[0])[-1]

    def all_subcommands(
        self,
        *prefix: str,
        include_prefixes: bool = False,
        filter_: Opt[Callable[["SubCommandFunc"], bool]] = None,
    ) -> Iterator[Tuple[Tuple[str, ...], "SubCommandFunc"]]:
        def inner(
            prefix: Tuple[str, ...],
            commands: Mapping,
            include_prefixes: bool,
            filter_=None,
        ):
            for name, (cmd, subcmds) in commands.items():
                pre = (*prefix, name)
                if cmd is not None:
                    if filter_ is None or filter_(cmd):
                        yield pre, cmd
                elif include_prefixes and subcmds and len(subcmds) > 1:
                    yield pre, cmd
                yield from inner(pre, subcmds, include_prefixes)

        rootcmd = self._main
        subcommands = self.subcommands
        for pre in prefix:
            rootcmd, subcommands = subcommands[pre]

        if rootcmd is not None:
            if filter_ is None or filter_(rootcmd):
                yield prefix, rootcmd
        elif include_prefixes and subcommands and len(subcommands) > 1:
            yield prefix, rootcmd
        yield from inner(prefix, subcommands, include_prefixes, filter_)

    def all_subcommand_names(
        self,
        *prefix: str,
        include_prefixes: bool = False,
        filter_: Opt[Callable[["SubCommandFunc"], bool]] = None,
    ) -> Iterator[Tuple[str, ...]]:
        return map(
            operator.itemgetter(0),
            self.all_subcommands(
                *prefix, include_prefixes=include_prefixes, filter_=filter_
            ),
        )

    ##########################
    # main execution methods #
    ##########################

    def run(
        self,
        args=None,
        namespace=None,
        report_progress=True,
        time_units="s",
        log_level=PROGRESS,
        error_level=ERROR,
    ):
        ns = self.parse_args(args, namespace)
        cmdname, cmdfunc = self.get_subcommand_func(ns)

        if cmdname is None and not self.require_subcommand:
            # run main but _not_ as an initializer
            if self._main is None:
                # unless there is None!
                self.error(
                    "No subcommand was passed, but no main function has been registered with the "
                    "{}.main() decorator".format(type(self).__name__)
                )
            cmdfunc = self._main
            main = True
            cmdname = "MAIN"
        else:
            main = False

        app_logger = self.get_app_logger(ns)
        app_logger.debug("command is %r", cmdname)
        config = self.parse_config(ns, app_logger) if self.use_config else None

        # if self is defined from a class and the command is not a reserved/builtin command,
        if (
            (not main)
            and (self.app_cls is not None)
            and (cmdname not in self.reserved_command_names)
        ):
            # perform any initialization logic; if main == True, this will be done below at func.execute()
            app_obj = self._main.execute(ns, config, handle_output=False)
        else:
            app_obj = None

        if not report_progress:
            result = cmdfunc.execute(ns, config, app_obj)
        else:
            with get_task(
                app_logger,
                cmdname,
                log_level=log_level,
                error_level=error_level,
                time_units=time_units,
            ):
                result = cmdfunc.execute(ns, config, app_obj)

        return result

    def parse_args(self, args=None, namespace=None):
        if self.require_subcommand and not self.subcommands:
            self.error(
                "This parser requires a subcommand but none have been defined; use the {}.subcommand() "
                "decorator on a function in your script to define one, or define your CLI via a class".format(
                    type(self).__name__
                )
            )

        self.add_builtin_commands()
        ns = super().parse_args(args, namespace=namespace)
        return self.validate_namespace(ns)

    def expand_default_path(self, path):
        path = os.path.expanduser(path)
        if os.path.isabs(path):
            return path
        elif self.default_paths_relative_to_source:
            return os.path.abspath(os.path.join(self.source_dir, path))
        else:
            return os.path.abspath(path)

    def validate_namespace(self, ns):
        if self.require_subcommand and self.get_subcommand(ns) is None:
            self.error(
                "A subcommand is required: one of {}".format(
                    tuple(self.subcommands or ())
                )
            )
        return ns

    @staticmethod
    def get_subcommand(ns=None):
        return getattr(ns, SUBCOMMAND_PATH_ATTR, None)

    def get_subcommand_func(
        self, ns: Union[Tuple[str, ...], Namespace]
    ) -> Tuple[Tuple[str, ...], "SubCommandFunc"]:
        if isinstance(ns, Namespace):
            cmd_path = self.get_subcommand(ns)
        else:
            cmd_path = ns

        cmd = None
        if cmd_path is not None:
            cmd_path = tuple(cmd_path)
            subcmds = self.subcommands
            for name in cmd_path:
                cmd, subcmds = subcmds[name]

        return cmd_path, cmd

    def get_app_logger(self, ns):
        verbosity = getattr(ns, VERBOSITY_ATTR, MIN_VERBOSITY)
        quiet = getattr(ns, QUIET_ATTR, False)
        log_level_ix = min(verbosity, len(LOG_LEVEL_NAMES) - 1)
        log_level = LOG_LEVEL_NAMES[log_level_ix]

        logpath = None
        if self.use_logfile and EXECUTE:
            logpath = getattr(ns, LOGFILE_ATTR, None)
            if logpath is not None:
                logpath = os.path.abspath(logpath)
            elif isinstance(self.default_logfile, str):
                logpath = self.expand_default_path(self.default_logfile)

        self.configure_logging(
            log_level=log_level,
            logfile=logpath,
            quiet=quiet,
            use_multiprocessing=self.use_multiprocessing,
        )

        rootlogger = getLogger()
        self.logger.debug(
            "configured root logger with effective level %s and handlers %r",
            _levelToName[rootlogger.getEffectiveLevel()],
            rootlogger.handlers,
        )

        app_logger = self.app_logger_cls.manager.getLogger(self.cmd_name)
        self.logger.debug(
            "configured app logger with effective level %s and handlers %r",
            _levelToName[app_logger.getEffectiveLevel()],
            app_logger.handlers,
        )

        return app_logger

    def configure_logging(
        self,
        log_level: Union[int, str],
        logfile: Opt[str] = None,
        quiet: bool = False,
        use_multiprocessing: bool = False,
    ):
        log_level_int = validate_log_level_int(log_level)

        configure_default_logging(
            console=not quiet,
            filename=logfile,
            file_level=log_level,
            console_level=log_level,
            verbose_format=(log_level_int < INFO),
            dated_logfiles=self.dated_logfiles,
            multiprocessing=use_multiprocessing,
            disable_existing_loggers=True,
        )

        self.logger.setLevel(log_level_int)

    def parse_config(self, ns, logger=None):
        if logger is None:
            logger = self.logger

        config_file = getattr(ns, CONFIG_FILE_ATTR, None)

        if config_file is None and self.use_config:
            if isinstance(self.default_configfile, str):
                config_file = self.expand_default_path(self.default_configfile)
                if not os.path.exists(config_file):
                    config_file = None
        elif config_file is not None:
            config_file = os.path.abspath(config_file)

        if config_file is None and self.require_config:
            self.error(
                "A config file is required but none was passed and no default was specified"
            )

        no_ext = (
            (not os.path.splitext(config_file)[1])
            if isinstance(config_file, (str, Path))
            else False
        )

        if config_file is not None:
            # file must exist; this will raise if not
            logger.debug("parsing config from {}".format(config_file))
            config = load_config(config_file, namespace=False, disambiguate=no_ext)
        else:
            config = None

        if config is not None:
            logger.debug("parsed config:\n%r", config)

        return config

    ##############################
    # command definition methods #
    ##############################

    def subcommand(
        self,
        command_prefix=None,
        config_subsections=None,
        implicit_flags=None,
        ignore_on_cmd_line=None,
        ignore_in_config=None,
        parse_config_as_cli=None,
        parse_env=None,
        parse_order=None,
        typecheck=None,
        output_handler=None,
        named_groups=None,
        require_options=None,
        name=None,
        from_method=False,
        metavars=None,
        tvar_map=None,
        _main=False,
        _builtin=False,
    ):
        if _main and require_options is None:
            require_options = True

        if implicit_flags is None:
            implicit_flags = self.implicit_flags

        def dec(
            f,
            command_prefix=command_prefix,
            output_handler=output_handler,
            config_subsections=config_subsections,
        ):
            # args provided here override those specified with decorators on the function, which override this
            # command line interface's global defaults
            if output_handler is None:
                output_handler = cli_attrs.output_handler(f, None)

            if output_handler is None:
                if _main and self.require_subcommand:
                    output_handler = NO_OUTPUT_HANDLER
                    output_sig_spec = None
                else:
                    output_handler = self.output_handler
                    output_sig_spec = self.default_output_signature_spec
            else:
                output_sig_spec = CLISignatureSpec.from_callable(
                    output_handler
                ).overriding(self.default_signature_spec)

            if config_subsections is None:
                config_subsections = cli_attrs.config_subsections(f, None)
                if config_subsections is None:
                    if self.use_subconfig_for_commands:
                        # bool
                        config_subsections = self.use_config
                    else:
                        config_subsections = [()]

            if command_prefix is None:
                command_prefix = cli_attrs.command_prefix(f)

            sig_spec = CLISignatureSpec(
                ignore_on_cmd_line=ignore_on_cmd_line,
                ignore_in_config=ignore_in_config,
                parse_config_as_cli=parse_config_as_cli,
                typecheck=typecheck,
                metavars=metavars,
                named_groups=named_groups,
                parse_env=parse_env,
                parse_order=parse_order,
                require_options=require_options,
            ).overriding(CLISignatureSpec.from_callable(f), self.default_signature_spec)

            subcmd = SubCommandFunc(
                f,
                name=name,
                signature_spec=sig_spec,
                output_signature_spec=output_sig_spec,
                command_prefix=command_prefix,
                config_subsections=config_subsections,
                output_handler=output_handler,
                implicit_flags=implicit_flags,
                lookup_order=self.lookup_order,
                argparser_cmd_name=self.cmd_name,
                from_method=from_method,
                tvar_map=tvar_map,
                suppress_setup_warnings=self.suppress_setup_warnings,
                _main=_main,
            )

            if (
                self.reserved_command_names
                and not _builtin
                and subcmd.cmd_prefix in self.reserved_command_names
            ):
                raise NameError(
                    "cannot use command prefix {} for subcommand '{}'; it is reserved for builtin functionality".format(
                        subcmd.cmd_prefix, name
                    )
                )

            subcmd.parser = self.add_arguments_from(subcmd)
            return subcmd

        return dec

    def main(
        self,
        config_subsections=None,
        implicit_flags=None,
        ignore_on_cmd_line=None,
        ignore_in_config=None,
        parse_config_as_cli=None,
        parse_order=None,
        typecheck=None,
        output_handler=None,
        named_groups=None,
        name=None,
        from_method=False,
        metavars=None,
        tvar_map=None,
    ):
        return self.subcommand(
            config_subsections=config_subsections,
            implicit_flags=implicit_flags,
            require_options=True,
            ignore_on_cmd_line=ignore_on_cmd_line,
            ignore_in_config=ignore_in_config,
            parse_config_as_cli=parse_config_as_cli,
            typecheck=typecheck,
            output_handler=output_handler,
            named_groups=named_groups,
            parse_order=parse_order,
            metavars=metavars,
            name=name,
            from_method=from_method,
            tvar_map=tvar_map,
            _main=True,
        )

    def definition(self, app_cls: type):
        """class decorator for generating subcommands via a class.
        This should only be called once per instance."""
        if not isinstance(app_cls, _type):
            t = type(self)
            raise TypeError(
                "{} instances can only be used to decorate classes; if you would like to customize "
                "behavior for specific subcommands, use {}.subcommand or {}.main as decorators for "
                "functions".format(classpath(t), t.__name__, t.__name__)
            )

        app_cls_ = get_generic_origin(app_cls)
        self.app_cls = app_cls_

        if getattr(app_cls_, "__doc__", None):
            if self.description is None or self.epilog is None:
                docs = parse_docstring(app_cls_.__doc__)
                help_kw = _help_kwargs_from_docs(
                    docs, long_desc_as_epilog=self.long_desc_as_epilog, help_=False
                )
                for name, value in help_kw.items():
                    if getattr(self, name, None) is None:
                        setattr(self, name, value)

        tvar_map = get_param_dict(app_cls)

        # the class constructor is main
        self.main(name="__init__", from_method=False, tvar_map=tvar_map)(app_cls)

        # methods are subcommands
        for name, f in app_cls_.__dict__.items():
            if not callable(f):
                continue
            if cli_attrs.noncommand(f):
                continue
            if name.startswith("_"):
                # don't register implicitly private methods
                continue
            if not is_method(app_cls, name):
                # don't configure CLI commands for classmethods and staticmethods
                if not self.suppress_setup_warnings:
                    setup_warn(
                        "currently only basic methods are supported as subcommands in a class def context "
                        "but callable '{}' = {} defined in {}'s namespace is of type {}".format(
                            name, f, app_cls, type(f)
                        )
                    )
                continue

            self.subcommand(name=name, from_method=True, tvar_map=tvar_map)(f)

        if self.description is None:
            self.description = app_cls.__doc__

        self.add_builtin_commands()

        if self._bash_completion:
            self.install_shell_completion()

        return app_cls

    def add_arguments_from(self, subcmd_func: "SubCommandFunc") -> ArgumentParser:
        cmd_path = (*subcmd_func.cmd_prefix, subcmd_func.cmd_name)

        if not subcmd_func._main:
            subparsers = self.get_nested_subparser(*subcmd_func.cmd_prefix).subparsers
            docs = subcmd_func.docs
            if docs is None:
                parser = subparsers.add_parser(subcmd_func.cmd_name)
            else:
                help_kw = _help_kwargs_from_docs(
                    docs, long_desc_as_epilog=self.long_desc_as_epilog
                )
                parser = subparsers.add_parser(subcmd_func.cmd_name, **help_kw)

            self._set_subcommand(*cmd_path, subcommand=subcmd_func)
        else:
            parser = self.add_argument_group("main arguments")

            if self.description is None:
                self.description = subcmd_func.docs.short_desc
                if self.epilog is None:
                    self.epilog = subcmd_func.docs.long_desc

            self._main = subcmd_func

        subcmd_func.add_arguments_to(parser)
        return parser

    #######################
    # Source file helpers #
    #######################

    def source_files(self):
        if self._source_files is not None:
            return self._source_files
        sourcepath = self.get_sourcepath()

        helpers = []
        for helper in self.helper_files or ():
            if helper is not None:
                path = os.path.abspath(helper)
                if not os.path.exists(path):
                    setup_warn(
                        "helper file {} was specified but doesn't exist".format(helper)
                    )
                else:
                    helpers.append(path)

        paths = [sourcepath, *helpers] if sourcepath else helpers
        self._source_files = paths
        return paths

    def get_sourcepath(self):
        if self.source_file is None:
            import __main__ as main

            sourcepath = getattr(main, "__file__", None)
            if sourcepath is not None:
                sourcepath = os.path.abspath(sourcepath)
                if not os.path.exists(sourcepath):
                    setup_warn(
                        "source file {} was looked up on __main__ but doesn't exist".format(
                            sourcepath
                        )
                    )
        else:
            sourcepath = os.path.abspath(self.source_file)
        return sourcepath

    def last_edit_time(self):
        if self._last_edit_time is not Missing:
            return self._last_edit_time

        sources = self.source_files()
        time = None if not sources else max(os.stat(path).st_mtime for path in sources)
        self._last_edit_time = time
        return time

    ####################
    # Shell completion #
    ####################

    def install_shell_completion(self):
        if self.source_file is None:
            names = (self.prog,)
        else:
            names = (self.prog, os.path.basename(self.source_file))

        self.logger.debug("Installing bash completion for command `{}`".format(names))
        install_shell_completion(self, *names, last_edit_time=self.last_edit_time())

    ##################
    # pickle methods #
    ##################

    def __getstate__(self):
        state = super().__getstate__()
        app_cls = state.get("app_cls", None)
        if app_cls is not None:
            state["app_cls"] = deconstruct_generic(app_cls)
        state.pop(
            "_source_files", None
        )  # could change in a new context if relative paths or ~/ are used
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        app_cls = state.get("app_cls", None)
        if app_cls is not None:
            app_cls = reconstruct_generic(app_cls)
            self.app_cls = app_cls

    ########################
    # special CLI commands #
    ########################

    def empty_config(
        self,
        only_required_args=False,
        literal_defaults=True,
        only_commands: Set[Tuple[str, ...]] = None,
        omit_commands: Set[Tuple[str, ...]] = None,
    ):
        config = {}
        MAIN = ()
        for name, subcommand in chain([(MAIN, self._main)], self.all_subcommands()):
            if (
                only_commands is not None
                and name not in only_commands
                and name is not MAIN
            ):
                continue
            if omit_commands is not None and name in omit_commands:
                continue
            if not subcommand.config_subsections:
                continue

            subsection = subcommand.config_subsections[0]

            if name != MAIN:
                self.logger.info(
                    "computing empty configuration for command '{}', subsection {}".format(
                        " ".join(name), subsection
                    )
                )
            else:
                self.logger.info(
                    "computing empty configuration for main args"
                    + (
                        ", subsection {}".format(subsection)
                        if subsection
                        else " at top level"
                    )
                )

            subconf = subcommand.empty_config(
                only_required_args=only_required_args, literal_defaults=literal_defaults
            )
            self.logger.info("%r", subconf)
            update_in(config, subcommand.config_subsections[0], subconf)

        return config

    def init_config(
        self,
        *,
        only_required_args: bool = False,
        literal_defaults: bool = True,
        only_commands: Opt[Set[str]] = None,
        omit_commands: Opt[Set[str]] = None,
    ):
        """
        Initialize a configuration for this app.

        :param only_required_args: should only required arguments be given and empty config value?
        :param literal_defaults: should literal default values be written to the config?
        :param only_commands: only write configuration for these commands
        :param omit_commands: omit configuration for these commands
        """
        # this is added as a CLI command if specified in the constructor
        self.logger.info("constructing empty configuration")
        if only_commands:
            self.logger.info(
                "only producing configuration for commands {}".format(only_commands)
            )
        elif omit_commands:
            self.logger.info("omitting commands {}".format(omit_commands))

        # expand subcommand prefixes
        if only_commands is not None:
            only_commands = set(
                chain.from_iterable(
                    self.all_subcommand_names(*c.split()) for c in only_commands
                )
            )
        if omit_commands is not None:
            omit_commands = set(
                chain.from_iterable(
                    self.all_subcommand_names(*c.split()) for c in omit_commands
                )
            )

        config = self.empty_config(
            only_required_args=only_required_args,
            literal_defaults=literal_defaults,
            only_commands=only_commands,
            omit_commands=omit_commands,
        )
        self.logger.debug("new config has keys {}".format(config.keys()))
        return config

    def dump_config(
        self,
        config: Mapping,
        path: Opt[Path] = None,
        *,
        as_dir: bool = False,
        format: Opt[ConfigFormat] = None,
        use_default_path: bool = False,
    ):
        """
        Optionally save the configuration to a file, or print to stdout if no path is provided.

        :param config: the configuration to dump (usually a JSON-serializable python object)
        :param path: path to the file (or dir) to write the configuration to. '-' implies stdout; note that in this case
            a format must also be specified, since it cannot be inferred from the filename.
        :param as_dir: should the config be written to a dir? (one file per subsection)
        :param format: the file extension to use for the configuration; determines the markup language used.
           Note: the .ini format is constrained to 1-level nesting and cannot represent values needing more than this
        :param use_default_path: use the default config file path for this app.
        """
        if use_default_path:
            if path is not None:
                raise ValueError(
                    "Cannot supply both a path and specify default_path=True"
                )
            if os.path.exists(self.default_configfile):
                msg = "Config file already exists at default location {}".format(
                    self.default_configfile
                )
                warn(msg)
                if input("Overwrite (y/n)? ").strip().lower() == "y":
                    path = self.default_configfile
                else:
                    exc = FileExistsError(msg)
                    self.logger.error(str(exc))
                    raise exc
            else:
                path = self.default_configfile

        file = sys.stdout if path is None or str(path) == "-" else path

        self.logger.info(
            "writing new configuration to {}{}".format(
                file, "" if format is None else " with {} format".format(format.name)
            )
        )

        try:
            dump_config(config, file, ext=format, as_dir=as_dir)
        except Exception as e:
            self.logger.error("could not dump config to {}: {}".format(file, e))
            raise e


class SubCommandFunc(Logged):
    __log_level__ = DEBUG
    parser = None

    def __init__(
        self,
        func: Callable,
        *,
        name=None,
        signature_spec: Opt[CLISignatureSpec] = None,
        output_signature_spec: Opt[CLISignatureSpec] = None,
        lookup_order=None,
        command_prefix=None,
        config_subsections=None,
        output_handler=None,
        implicit_flags=False,
        argparser_cmd_name=None,
        suppress_setup_warnings=False,
        tvar_map=None,
        from_method=False,
        _main=False,
    ):
        if name is None:
            func_name = funcname(func)
            if func_name is None:
                raise AttributeError(
                    "functions for subcommands must have __name__ attributes; {} does not; "
                    "try using a def rather than a lambda expression / funtools.partial, or pass a "
                    "name arg explicitly".format(func)
                )
        else:
            func_name = name

        if isinstance(command_prefix, str):
            command_prefix = (command_prefix,)
        elif command_prefix is None:
            command_prefix = ()

        lookup_order = _validate_lookup_order(*lookup_order, include_defaults=False)
        cmd_name = to_cmd_line_name(strip_command_prefix(command_prefix, func_name))
        command_prefix = tuple(map(to_cmd_line_name, command_prefix))

        func_for_docs = (
            most_specific_constructor(func)
            if (isinstance(func, type) or is_generic_type(func))
            else func
        )
        try:
            docs = parse_docstring(func_for_docs)
        except AttributeError:
            docs = None

        if signature_spec is None:
            signature_spec = CLISignatureSpec()

        if output_handler is NO_OUTPUT_HANDLER:
            output_handler = None

        main_sig = fully_concrete_signature(
            func, from_method=from_method, tvar_map=tvar_map
        )

        warn_missing = None if suppress_setup_warnings else setup_warn
        final_spec = signature_spec.configure(main_sig, warn_missing=warn_missing)

        if output_handler is not None:
            # from_method = True because we skip the first arg
            output_sig = fully_concrete_signature(
                output_handler, from_method=True, tvar_map=tvar_map
            )
            if output_signature_spec is None:

                def maybe_bool(x, *values):
                    return x if x in values else None

                if output_signature_spec is None:
                    output_signature_spec = CLISignatureSpec.from_callable(
                        output_handler
                    )
                # allow all-inclusive (boolean) values to supercede those specified locally on the output handler
                output_signature_spec = CLISignatureSpec(
                    ignore_in_config=maybe_bool(signature_spec.ignore_in_config, True),
                    ignore_on_cmd_line=maybe_bool(
                        signature_spec.ignore_on_cmd_line, True
                    ),
                    require_options=maybe_bool(signature_spec.require_options, True),
                ).overriding(output_signature_spec)

            final_output_spec = output_signature_spec.configure(output_sig)

            overlap = final_output_spec.parsed.intersection(final_spec.parsed)
            if overlap:
                raise NameError(
                    "Names {} are specified to be parsed from the signatures of both the function {}"
                    "and its output handler {}".format(
                        tuple(overlap), func, output_handler
                    )
                )

            try:
                output_docs = parse_docstring(output_handler)
            except AttributeError:
                output_docs = None
            else:
                docs = CallableDocs(
                    short_desc=docs.short_desc,
                    long_desc="\n".join(
                        d
                        for d in (
                            docs.long_desc,
                            output_docs.desc,
                            output_docs.long_desc,
                        )
                        if d
                    ),
                    params=chain(docs.params.values(), output_docs.params.values()),
                    returns=docs.returns,
                    raises=docs.raises + output_docs.raises,
                )

            all_parsed = final_spec.parsed.union(final_output_spec.parsed)
            all_cli_parsed = final_spec.parse_cmd_line.union(
                final_output_spec.parse_cmd_line
            )
            have_fallback = final_spec.have_fallback.union(
                final_output_spec.have_fallback
            )
            cli_sig = _combined_cli_sig(
                main_sig, output_sig, parse=all_cli_parsed, have_fallback=have_fallback
            )
            all_sigs = (main_sig, output_sig)
            named_groups = {k: set(v) for k, v in final_spec.named_groups.items()}
            for name, group in final_output_spec.named_groups.items():
                if name in named_groups:
                    named_groups[name].update(group)
                else:
                    named_groups[name] = group
        else:
            output_sig = None
            output_docs = None
            final_output_spec = None
            all_parsed = final_spec.parsed
            all_cli_parsed = final_spec.parse_cmd_line
            have_fallback = final_spec.have_fallback
            cli_sig = _combined_cli_sig(
                main_sig, parse=all_cli_parsed, have_fallback=have_fallback
            )
            all_sigs = (main_sig,)
            named_groups = final_spec.named_groups

        self._main = bool(_main)
        self.func_name = func_name
        self.cmd_prefix = command_prefix
        self.cmd_name = cmd_name
        self.__logname__ = ".".join(
            (argparser_cmd_name, *self.cmd_prefix, self.cmd_name)
        )
        self.docs = docs
        self.output_docs = output_docs
        self.func = func
        self.output_handler = output_handler
        self.from_method = bool(from_method)

        # options
        self.implicit_flags = bool(implicit_flags)
        self.lookup_order = lookup_order

        self.named_groups = named_groups
        self.arg_to_group_name = dict(
            chain.from_iterable(
                zip(argnames, repeat(groupname))
                for groupname, argnames in named_groups.items()
            )
        )

        def all_parsed_params():
            params = chain.from_iterable(sig.parameters.items() for sig in all_sigs)
            return ((name, param) for name, param in params if name in all_parsed)

        # signature info
        self.cli_signature = cli_sig
        self.main_signature = main_sig
        self.main_signature_spec = final_spec
        self.output_signature = output_sig
        self.output_signature_spec = final_output_spec
        self.have_fallback = have_fallback
        self.parsed = all_parsed

        # defaults for params that can be parsed from the command line
        defaults = {}
        for name, p in all_parsed_params():
            if p.default is not Parameter.empty:
                defaults[name] = p.default
            elif p.kind == Parameter.VAR_POSITIONAL:
                defaults[name] = ()
            elif p.kind == Parameter.VAR_KEYWORD:
                defaults[name] = {}

        self.defaults = defaults
        self.typed_io = OrderedDict(
            [
                (name, TypedIO.from_parameter(param))
                for name, param in all_parsed_params()
            ]
        )

        if config_subsections in (False, None):
            self.config_subsections = None
        elif config_subsections is True:
            # preserve _'s on __init__ for main function
            self.config_subsections = [
                (*command_prefix, func_name if _main else cmd_name)
            ]
        elif isinstance(config_subsections, (str, int)):
            self.config_subsections = [(config_subsections,)]
        elif isinstance(config_subsections, tuple):
            # a single section
            self.config_subsections = [config_subsections]
        else:
            # a list of sections
            self.config_subsections = [
                (t,) if isinstance(t, (str, int)) else tuple(t)
                for t in config_subsections
            ]

    @property
    def cmd_path(self):
        return (*self.cmd_prefix, self.cmd_name)

    @property
    def parse_config(self):
        if self.output_signature_spec is None:
            return self.main_signature_spec.parse_config
        return self.main_signature_spec.parse_config.union(
            self.output_signature_spec.parse_config
        )

    @property
    def parse_cmd_line(self):
        if self.output_signature_spec is None:
            return self.main_signature_spec.parse_cmd_line
        return self.main_signature_spec.parse_cmd_line.union(
            self.output_signature_spec.parse_cmd_line
        )

    @property
    def parse_env(self):
        if self.output_signature_spec is None:
            return self.main_signature_spec.parse_env
        return ChainMap(
            self.main_signature_spec.parse_env, self.output_signature_spec.parse_env
        )

    @property
    def parse_order(self):
        if self.output_signature_spec is None:
            return self.main_signature_spec.parse_order
        return (
            self.output_signature_spec.parse_order
            + self.main_signature_spec.parse_order
        )

    @property
    def parse_config_as_cli(self):
        if self.output_signature_spec is None:
            return self.main_signature_spec.parse_config_as_cli
        return self.main_signature_spec.parse_config_as_cli.union(
            self.output_signature_spec.parse_config_as_cli
        )

    def add_arguments_to(self, parser: ArgumentParser):
        named_groups = {
            name: parser.add_argument_group(name) for name in self.named_groups
        }

        positional_args = []
        for name, param in self.cli_signature.parameters.items():
            group_name = self.arg_to_group_name.get(name)
            group = parser if group_name is None else named_groups[group_name]
            spec = (
                self.main_signature_spec
                if name in self.main_signature_spec.parse_cmd_line
                else self.output_signature_spec
            )

            io_methods = self.typed_io[name]
            action = io_methods.add_argparse_arg(
                group,
                param,
                allow_positionals=not spec.require_options,
                implicit_flags=self.implicit_flags,
                has_fallback=name in spec.have_fallback,
                metavar=spec.metavars,
                docs=self.docs,
            )
            nargs = io_methods.cli_nargs
            if action.positional:
                positional_args.append((name, param.annotation, nargs))

        if positional_args:
            # one trailing variable-length positional is OK
            bad_positional_args = [
                tup for tup in positional_args[:-1] if tup[-1] in VARIADIC_NARGS
            ]
            if bad_positional_args:
                if positional_args[-1][-1] in VARIADIC_NARGS:
                    bad_positional_args.append(positional_args[-1])
                raise ValueError(
                    "The parameters {} of function {} are all positional, but have variable-length "
                    "command line args {}; parsing cannot be performed unambiguously.".format(
                        ", ".join(
                            "{}:{}".format(n, t) for n, t, _ in bad_positional_args
                        ),
                        self.func_name,
                        tuple(n for _, _, n in bad_positional_args),
                    )
                )

    def get_conf(self, config):
        if config is None:
            return None

        conf = None
        parse_config = self.parse_config

        if self.config_subsections:
            confs = []
            for section in self.config_subsections:
                conf_ = get_in(section, config, Missing)

                if conf_ is not Missing:
                    if not isinstance(conf_, Mapping):
                        raise TypeError(
                            "config subsections for function arguments must be str->value mappings; got {} "
                            "for command {} in section {} of the config".format(
                                type(conf_), self.__name__, section
                            )
                        )
                    confs.append(conf_)

            if len(confs) > 1:
                conf = ChainMap(*confs)
            elif not confs:
                conf = {}
            else:
                conf = confs[0]

            if conf and parse_config:
                conf = {k: v for k, v in conf.items() if k in parse_config}

        return conf

    def get_env(self):
        parse_env = self.parse_env
        if not parse_env:
            return None
        return {
            arg_name: os.environ[env_name]
            for arg_name, env_name in parse_env.items()
            if env_name in os.environ
        }

    def execute(self, namespace, config, instance=None, handle_output=True):
        args, kwargs, output_args, output_kwargs = self.prepare_args_kwargs(
            namespace, config, handle_output=handle_output
        )

        if self.from_method:
            # method
            value = self.func(instance, *args, **kwargs)
        else:
            # bare function
            value = self.func(*args, **kwargs)

        if handle_output and self.output_handler is not None:
            _ = self.output_handler(value, *output_args, **output_kwargs)

        return value

    def prepare_args_kwargs(self, argparse_namespace, config=None, handle_output=True):
        conf = self.get_conf(config)
        env = self.get_env()
        cli = (
            argparse_namespace.__dict__
            if isinstance(argparse_namespace, Namespace)
            else argparse_namespace
        )
        cli = {name: value for name, value in cli.items() if not Missing.missing(value)}

        lookup = {
            ArgSource.CLI: cli,
            ArgSource.ENV: env,
            ArgSource.CONFIG: conf,
            ArgSource.DEFAULTS: self.defaults,
        }
        sources = []
        for source in self.lookup_order:
            ns = lookup[source]
            if ns:
                sources.append((source, ns))

        namespace = NamedChainMap(*sources)
        self.logger.debug(
            "parsing args for command %r from sources %r in order %r",
            self.func_name,
            namespace.names,
            self.parse_order,
        )

        handle_output = handle_output and self.output_handler is not None

        # prepare the raw values to be parsed
        if handle_output:
            output_values, output_missing = self._prepare_raw_values(
                namespace, self.output_signature_spec
            )
        else:
            output_values, output_missing = [], []
        main_values, main_missing = self._prepare_raw_values(
            namespace, self.main_signature_spec
        )

        if output_missing or main_missing:
            missing_ = output_missing + main_missing
            raise ValueError(
                "could not find value for args {} of command `{}` in any of {}".format(
                    missing_,
                    self.cmd_name,
                    tuple(source.value for source in self.lookup_order),
                )
            )

        # We make the assumption that output handling args will generally be lighter to process than input args;
        # e.g. mainly file handles, credentials, flags. Thus we parse them first.
        if handle_output:
            output_args, output_kwargs = self._parse_raw_values(
                output_values, self.output_signature_spec, self.output_signature
            )
        else:
            output_args, output_kwargs = None, None
        main_args, main_kwargs = self._parse_raw_values(
            main_values, self.main_signature_spec, self.main_signature
        )

        return main_args, main_kwargs, output_args, output_kwargs

    def _parse_raw_values(
        self,
        values: List[Tuple[str, ArgSource, object]],
        spec: FinalCLISignatureSpec,
        sig: Signature,
    ):
        final_args = ()
        final_kw = {}
        kwargs_name = None
        final_kwargs = None
        typed_io = self.typed_io
        parse_config_as_cli = spec.parse_config_as_cli
        typecheck = spec.typecheck
        params = sig.parameters

        for name, source, value in values:
            self.logger.debug(
                "parsing arg %r from %s with value %r", name, source.value, value
            )
            tio = typed_io[name]
            param = params[name]

            if source == ArgSource.CONFIG and name in parse_config_as_cli:
                parser = tio.parser_for_source(ArgSource.CLI)
            else:
                parser = tio.parser_for_source(source)

            parsed = parser(value)
            self.logger.debug(
                "parsed value %r for arg %r from %s", parsed, name, source.value
            )

            if name in typecheck and param.annotation is not Parameter.empty:
                if not isinstance_generic(parsed, tio.type_):
                    try:
                        raise TypeError(
                            "parsed value {} for arg {} is not an instance of {}".format(
                                repr(parsed), repr(name), param.annotation
                            )
                        )
                    except Exception as e:
                        self.logger.error(str(e))
                        raise e

            kind = param.kind
            if kind == Parameter.VAR_POSITIONAL:
                # only use *args for the args to start, then extend named positionals with these below
                final_args = parsed
            elif kind == Parameter.VAR_KEYWORD:
                final_kwargs = parsed
            else:
                final_kw[name] = parsed

        if final_kwargs:
            overlap = tuple(k for k in final_kwargs if k in final_kw)
            if overlap:
                raise RepeatedCLIKeywordArgs(overlap, kwargs_name)

        if spec.positional_names:
            final_args = (
                *(final_kw.pop(n, params[n].default) for n in spec.positional_names),
                *final_args,
            )

        if final_kwargs:
            final_kw.update(final_kwargs)

        self.logger.debug("Parsed all values successfully for signature %s", sig)
        return final_args, final_kw

    @staticmethod
    def _prepare_raw_values(
        namespace: NamedChainMap, spec: FinalCLISignatureSpec
    ) -> Tuple[List[Tuple[str, ArgSource, object]], List[str]]:
        sentinel = object()
        values, missing_ = [], []
        for name in filter(spec.parsed.__contains__, spec.parse_order):
            source, value = namespace.get_with_name(name, sentinel)
            if value is sentinel:
                missing_.append(name)
            else:
                values.append((name, source, value))

        return values, missing_

    def empty_config(self, only_required_args=False, literal_defaults=False):
        conf = {}
        typed_io = self.typed_io
        all_params = (
            self.main_signature.parameters.items()
            if self.output_signature is None
            else chain(
                self.main_signature.parameters.items(),
                self.output_signature.parameters.items(),
            )
        )
        parse_config_as_cli = self.parse_config_as_cli
        parse_config = self.parse_config
        for name, param in all_params:
            if name not in parse_config:
                continue

            has_default = param.default is not Parameter.empty
            if has_default and only_required_args:
                continue

            # for the purposes of a representative config value, None doesn't count as a default
            has_nonnull_default = has_default and param.default is not None

            tio = typed_io[name]
            if name in parse_config_as_cli:
                # can't cli-encode a value, so even if literal_defaults is True, we leave this as a type repr
                val = tio.cli_repr
                if tio.cli_nargs in (ZERO_OR_MORE, ONE_OR_MORE):
                    if isinstance(val, str):
                        val = [val, ellipsis_]
                    elif not isinstance(val, list):  # tuples
                        val = list(val)
            elif literal_defaults and has_nonnull_default:
                val = tio.config_encoder(param.default)
            else:
                val = tio.config_repr

            if is_optional_type(tio.type_) and has_default:
                name = OPTIONAL_ARG_TEMPLATE.format(name)

            conf[name] = val

        return conf

    def __getstate__(self):
        state = super().__getstate__()
        for key in ("cli_signature", "main_signature", "output_signature"):
            sig = state.pop(key)
            state[key] = Signature(
                [
                    p.replace(annotation=deconstruct_generic(p.annotation))
                    for p in sig.parameters.values()
                ]
            )
        return state

    def __setstate__(self, state):
        for key in ("cli_signature", "main_signature", "output_signature"):
            sig = state.pop(key)
            state[key] = Signature(
                [
                    p.replace(annotation=reconstruct_generic(p.annotation))
                    for p in sig.parameters.values()
                ]
            )
        self.__dict__.update(state)
