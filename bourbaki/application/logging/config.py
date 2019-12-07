# coding:utf-8
from typing import Union, Dict, Mapping, Any, Optional
import os
import io
import sys
from pathlib import Path
from warnings import warn
from logging import Logger, StreamHandler
from _io import TextIOWrapper
from logging import NOTSET, DEBUG, INFO, WARNING, ERROR, CRITICAL
from logging.config import dictConfig
from datetime import datetime
from .helpers import validate_log_level_int, validate_log_level_str
from .regexes import log_fields
from .defaults import (
    DEFAULT_FILE_HANDLER_CONFIG,
    DEFAULT_CONSOLE_HANDLER_CONFIG,
    DEFAULT_SMTP_HANDLER_CONFIG,
)
from .defaults import (
    DEFAULT_FILE_HANDLER_MP_CONFIG,
    DEFAULT_CONSOLE_HANDLER_MP_CONFIG,
    DEFAULT_SMTP_HANDLER_MP_CONFIG,
)
from .defaults import (
    DEFAULT_LOG_DATE_FMT,
    DEFAULT_LOG_MSG_FMT,
    DEFAULT_LOG_MSG_MP_FMT,
    VERBOSE_LOG_MSG_FMT,
)
from bourbaki.application.config import load_config
from bourbaki.application.paths import DEFAULT_FILENAME_DATE_FMT
from .defaults import (
    DEFAULT_FILE_LOG_LEVEL,
    DEFAULT_CONSOLE_LOG_LEVEL,
    DEFAULT_SMTP_LOG_LEVEL,
    empty_config_dict,
)


__doc__ = """
    Application-level logging configuration functions
    example, to configure logging globally, run the following at the start of a script:
    
    logfile = "/path/to/my/log_dir/MyApp.log"
    
    logconfig = default_config(logfile, console=TRUE)  # here we specify that we log to a file and the console
    configure_logging(logconfig, dated_logfiles=False)  # here we specify that log files will not have run times
                                                        # appended to their names
    
    # now any class that gets a logger as a child of the root logger
    # will have a logger attached that logs to the correct places, e.g.:
    
    class MyClass(Logged):
        __instance_naming__ = 'int'
        __verbose__ = True  # log constructor errors
        
        def __init__(self, *args):
            # a DEBUG-level statement is logged prior to entering this function thanks to the __verbose__ flag
            # and an ERROR-level statement will be logged if it fails
            self.args = args
    
    my_instance = MyClass(1, 2, 3)
    my_instance.logger.info("hello!")
    
    will print something like this to the console and/or log file:
    
    MyClass-1: <line no> <datetime> DEBUG - initializing new instance
    MyClass-1: <line no> <datetime> INFO - hello!
    """

LogLevel = Union[str, int]
IOSpec = Union[str, TextIOWrapper]

instance_naming_opts = ("int", "hex", "keyword", None)


def make_log_format(fields, sep=" - "):
    """
    Build a custom log format, as accepted by the logging module, from a list of field names.
    :param fields: list or tuple of str - names of fields to use in log messages
    :param sep: str - separator to put between fields. Default is ' - '
    :return: a log format string usable to configure log formatters
    """
    assert all(f in log_fields for f in fields), "Only fields from {} are valid".format(
        tuple(log_fields)
    )
    return sep.join("%({}){}".format(f, log_fields[f]) for f in fields)


def configure_default_logging(
    filename=None,
    console=True,
    verbose_format=False,
    smtp_credentials=None,
    smtp_to_addrs=None,
    smtp_mailhost=None,
    smtp_tls_credentials=(),
    smtp_buffer_capacity=10,
    file_level=DEFAULT_FILE_LOG_LEVEL,
    console_level=DEFAULT_CONSOLE_LOG_LEVEL,
    smtp_level=DEFAULT_SMTP_LOG_LEVEL,
    multiprocessing=False,
    dated_logfiles=False,
    disable_existing_loggers=False,
):
    """
    Batteries-included default configuration in one line.

    :param filename: Optional path to a file to log to, if file logging is desired
    :param console: boolean indicating whether to log to the console
    :param level: string ("DEBUG". "INFO", "WARN", "ERROR", "CRITICAL") or int (0-50)
        (or a custom level registered in an imported package, i.e. logging defines "PROGRESS" > "INFO")
        The lowest level of any log message that will be printed to file or console.
    :param dated: bool - append datetime to log filename? Default is False.
    :return: None; this configures logging globally in the logging module
    """
    if verbose_format:
        fmt = VERBOSE_LOG_MSG_FMT
    else:
        fmt = DEFAULT_LOG_MSG_FMT if not multiprocessing else DEFAULT_LOG_MSG_MP_FMT

    conf = default_config(
        filename,
        console,
        format=fmt,
        smtp_credentials=smtp_credentials,
        smtp_to_addrs=smtp_to_addrs,
        smtp_mailhost=smtp_mailhost,
        smtp_tls_credentials=smtp_tls_credentials,
        smtp_buffer_capacity=smtp_buffer_capacity,
        file_log_level=file_level,
        console_log_level=console_level,
        smtp_log_level=smtp_level,
        multiprocessing=multiprocessing,
        disable_existing_loggers=disable_existing_loggers,
        dated_logfiles=dated_logfiles,
    )

    configure_custom(conf)


def configure_debug_logging(
    filename=None, dated_logfiles=True, disable_existing_loggers=False
):
    """
    Batteries-included debug-level logging configuration in one line.
    All loggers are set to 'DEBUG' log level and log to console as well as a file, if
    a filename is specified.

    :param filename: Optional path to a file to log to, if file logging is desired
    :param dated: bool - append datetime to log filename? Default is True, to create a
      new timestamped file for a fresh run.
    :return: None; this configures logging globally in the logging module
    """
    conf = default_config(
        filename=filename,
        console=True,
        file_log_level=DEBUG,
        console_log_level=DEBUG,
        dated_logfiles=dated_logfiles,
        disable_existing_loggers=disable_existing_loggers,
    )

    configure_custom(conf)


def configure_custom(
    config: Union[str, Dict[str, Any]], disable_existing_loggers: Optional[bool] = None
):
    """
    Configure the global logging properties for a run of an application

    :param config: dictionary as passed to logging.config.dictConfig
        OR a file path, which case the config dict is read from a file (.yml or .json)
    :param disable_existing_loggers: boolean. When logging.config.dictConfig is called, it disables
        all existing loggers by default. When this is False, they are re-enabled after the configuration
        to allow pre-configured loggers to continue logging to their specified locations
    :return: None; this configures logging globally in the logging module
    """
    if isinstance(config, (str, Path, io.IOBase)):
        config = load_config_from_file(config)

    elif not isinstance(config, Mapping):
        raise ValueError(
            "config must be a path to a config file or a dictionary as accepted by "
            "logging.config.dictConfig"
        )

    if (
        disable_existing_loggers is not None
        and config.get("disable_existing_loggers") != disable_existing_loggers
    ):
        config = config.copy()
        config["disable_existing_loggers"] = disable_existing_loggers

    dictConfig(config)


configure_custom_logging = configure_custom


def load_config_from_file(filename) -> Dict[str, Any]:
    conf = load_config(filename)

    if not isinstance(conf, dict):
        warn(
            "Warning: the loaded config does not appear to be a key-value mapping; a call to "
            "logging.config.dictConfig or configure_logging will fail."
        )

    return conf


def default_config(
    filename: Optional[str] = None,
    console: bool = True,
    file_log_level: LogLevel = DEFAULT_FILE_LOG_LEVEL,
    console_log_level: LogLevel = DEFAULT_CONSOLE_LOG_LEVEL,
    smtp_log_level: LogLevel = DEFAULT_SMTP_LOG_LEVEL,
    root_log_level: Optional[LogLevel] = None,
    smtp_credentials=None,
    smtp_to_addrs=None,
    smtp_mailhost=None,
    smtp_tls_credentials=(),
    smtp_buffer_capacity=10,
    format: str = DEFAULT_LOG_MSG_FMT,
    datefmt: str = DEFAULT_LOG_DATE_FMT,
    stream: IOSpec = "stderr",
    multiprocessing=False,
    dated_logfiles: bool = False,
    max_logfile_bytes: int = 2 ** 30,
    disable_existing_loggers: bool = True,
    check_dir: bool = True,
):
    """
    Get a dictionary for configuring logging with a file logger and a console logger.
    The console logger is by default configured at the DEBUG level, while
    the file logger only logs messages at the INFO level and above.
    All args documented here have reasonable defaults, so you need not worry about most of them.

    :param filename: where to log to on disk. If None, don't configure a file logger
    :param console: bool indicating whether to log to the terminal stdout. Default is True
    :param file_log_level: int or string indicating the logging level of the file logger (if filename is given).
        Default is "INFO"
    :param root_log_level: int or string indicating the logging level of the root logger. This acts as a filter for
        all other loggers, so use wisely. Default is "DEBUG", meaning that all messages will come through
    :param stream: either a str in ('stdout', 'stdin') or io.TextIOWrapper such as sys.stdout,
    :param format: format of logger messages, as passed to the logging.Formatter constructor
    :param datefmt: format of dates in logger messages, as passed to the logging.Formatter constructor
    :param max_logfile_bytes: max size of the log file in bytes. Default is 2**30 = 1Gb
    :param check_dir: bool indicating whether to check if the directory of the logfile exists. An exception is
        raised if not
    :return: a dict suitable for passing to logging.config.dictConfig
    """
    file_log_level = validate_log_level_int(file_log_level or NOTSET)
    smtp_log_level = validate_log_level_int(smtp_log_level or NOTSET)
    console_log_level = validate_log_level_int(console_log_level or NOTSET)
    if root_log_level is None:
        root_log_level = min([console_log_level, file_log_level, smtp_log_level])
    else:
        root_log_level = validate_log_level_int(root_log_level or NOTSET)

    # construct a copy of an empty config each time to avoid mutation problems
    config = empty_config_dict.copy()
    config["formatters"]["default"] = dict(format=format, datefmt=datefmt)
    config["root"]["level"] = root_log_level

    if console:
        console_config = (
            DEFAULT_CONSOLE_HANDLER_CONFIG.copy()
            if not multiprocessing
            else DEFAULT_CONSOLE_HANDLER_MP_CONFIG.copy()
        )
        if stream is not None:
            console_config["stream"] = get_stream_name_for_config(stream)
        console_config["level"] = console_log_level
        config["handlers"]["console"] = console_config

    if filename is not None:
        assert isinstance(filename, str), "filename must be a string, not {}".format(
            type(filename)
        )
        filename = os.path.abspath(filename)

        if check_dir:
            logdir = os.path.dirname(filename)
            assert os.path.isdir(logdir), "the directory '{}' does not exist".format(
                logdir
            )
        if max_logfile_bytes is not None:
            assert isinstance(max_logfile_bytes, int), "max_bytes must be an int"

        if dated_logfiles:
            filename = append_log_date(filename)

        fileconfig = (
            DEFAULT_FILE_HANDLER_CONFIG.copy()
            if not multiprocessing
            else DEFAULT_FILE_HANDLER_MP_CONFIG.copy()
        )

        fileconfig["level"] = file_log_level
        fileconfig["filename"] = filename
        fileconfig["maxBytes"] = max_logfile_bytes
        config["handlers"]["file"] = fileconfig

    if smtp_mailhost is not None or smtp_credentials is not None:
        smtp_config = (
            DEFAULT_SMTP_HANDLER_CONFIG.copy()
            if not multiprocessing
            else DEFAULT_SMTP_HANDLER_MP_CONFIG.copy()
        )

        if smtp_to_addrs is None:
            if isinstance(smtp_credentials, (list, tuple)):
                smtp_to_addrs = [smtp_credentials[0]]
            elif isinstance(smtp_credentials, str):
                smtp_to_addrs = [smtp_credentials]

        for name, var in [
            ("level", smtp_log_level),
            ("capacity", smtp_buffer_capacity),
            ("mailhost", smtp_mailhost),
            ("credentials", smtp_credentials),
            ("toaddrs", smtp_to_addrs),
            ("secure", smtp_tls_credentials),
        ]:
            if var is not None:
                smtp_config[name] = var

        config["handlers"]["email"] = smtp_config

    # root logger uses all handlers
    config["root"]["handlers"] = list(config["handlers"].keys())

    config["disable_existing_loggers"] = disable_existing_loggers

    return config


def enable_loggers(logger_cls=Logger):
    for logger in logger_cls.manager.loggerDict.values():
        logger.disabled = False


def disable_loggers(logger_cls=Logger):
    for logger in logger_cls.manager.loggerDict.values():
        logger.disabled = True


def all_loggers():
    def inner():
        yield Logger.root
        for log in Logger.manager.loggerDict.values():
            yield log

    return list(inner())


def logs_to_console(logger):
    def _logs_to_console(handler):
        return handler.stream.name in ("<stderr>", "<stdout>", "stderr", "stdout")

    if isinstance(logger, StreamHandler):
        return _logs_to_console(logger)
    elif isinstance(logger, Logger):
        return any(_logs_to_console(h) for h in logger.handlers)


def disable_console_logging(*loggers):
    loggers = loggers or all_loggers()
    for logger in loggers:
        if not hasattr(logger, "handlers"):
            continue
        cache = []
        handlers = []
        for handler in logger.handlers:
            if logs_to_console(handler):
                cache.append(handler)
            else:
                handlers.append(handler)
        if cache:
            logger.handlers = handlers
            logger._handler_cache = cache


def enable_console_logging(*loggers):
    loggers = loggers or all_loggers()
    for logger in loggers:
        cache = getattr(logger, "_handler_cache", None)
        if cache:
            logger.handlers.extend(cache)
            delattr(logger, "_handler_cache")


def get_stream_name_for_config(stream: IOSpec) -> Union[str, TextIOWrapper]:
    if isinstance(stream, str):
        assert stream in (
            "stdout",
            "stderr",
        ), "if stream is a string, it must be in ('stdout', 'stderr')"
    else:
        assert isinstance(
            stream, TextIOWrapper
        ), "if stream is not a string, it must be an instance of _io.TextIOWrapper"

    if stream in ("stdout", sys.stdout):
        return "ext://sys.stdout"
    elif stream in ("stderr", sys.stderr):
        return "ext://sys.stderr"
    else:
        return stream


def append_log_date(filename: str, datestr=None, sep="") -> str:
    cur_time_str = datestr or datetime.now().strftime(DEFAULT_FILENAME_DATE_FMT)
    name, ext = os.path.splitext(filename)
    return name + sep + cur_time_str + ext
