#coding:utf-8
from logging import getLogger, setLoggerClass

# Import commonly used things into the top-level namespace for quick import
from . import config, defaults, interface, timing, loggers, analysis
from .interface import Logged, LoggedMeta
from .config import (configure_default_logging, configure_debug_logging, configure_custom_logging,
                     enable_console_logging, disable_console_logging)
from .defaults import (DEFAULT_LOG_MSG_FMT, DEFAULT_LOG_DATE_FMT,
                       DEFAULT_CONSOLE_LOG_LEVEL, DEFAULT_FILE_LOG_LEVEL)
from .timing import timed_context, TimedTaskContext
from .analysis import log_file_to_df
from .loggers import CallableLogger, ProgressLogger, SwissArmyLogger, printLogger
from .handlers import (MemoryHandler, SMTPHandler, BufferingSMTPHandler, MultiProcHandler,
                       MultiProcBufferingSMTPHandler, MultiProcStreamHandler, MultiProcRotatingFileHandler)


def get_default_logger(name, level=DEFAULT_FILE_LOG_LEVEL, filename=None,
                       dated_logfiles=False):
    """
    Return a logger with the given name, logging to stderr and optionally
    a specified filename.

    Warning: this configures logging with the default configuration as
    a side effect. If you intend to apply a custom configuration, the
    logger returned may be orphaned and/or disabled; you should use
    `configure_default` or `configure_custom`, followed by `getLogger`,
    in that case.
    :param name: the name for the logger. `__file__` is a standard choice
      for a script logger, and `__name__` works within a Jupyter notebook
      session, but isn't very informative - a custom name is better in
      that case
    :param level: The logging level of the root logger through which all
      log messages pass. Set this to "DEBUG" if you want verbose messages.
      Defaults to "INFO".
    :param filename: optional path to a file to log to. Without this, no
      log messages are persisted to disk. Messages logged to this file
      can be loaded as a pandas Dataframe at a later time with
      `log_file_to_df(filename, datetime_index=True/False)`.
    :return: a logging.Logger
    """
    configure_default_logging(filename=filename, level=level, dated_logfiles=dated_logfiles)
    logger = getLogger(name)
    return logger
