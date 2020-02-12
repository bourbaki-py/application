# coding:utf-8
from logging import NOTSET, DEBUG, INFO, WARNING, ERROR, CRITICAL

# Useful default configurations

MAX_REPR_LEN = (
    24
)  # the max string len used for representing args in verbose function call
# signature logging

DEFAULT_PROGRESS_LOG_LEVEL = "INFO"

FULL_PATH_LOGGER_NAMING = (
    False
)  # use the fully qualified class path in the names of class/function
# loggers? Module name is already included in the default log format,
# which makes it an automatically accessible field in a log file parse

DEFAULT_LOG_DATE_FMT = "%y-%m-%d %H:%M:%S"

VERBOSE_LOG_MSG_FMT = "%(name)s:%(processName)s - %(filename)s:%(funcName)s:%(lineno)d - %(asctime)s,%(msecs)d - %(levelname)s:%(levelno)d - %(message)s"
DEFAULT_LOG_MSG_FMT = (
    "%(name)s - %(asctime)s,%(msecs)d - %(levelname)s:%(levelno)d - %(message)s"
)
DEFAULT_LOG_MSG_MP_FMT = "%(name)s:%(processName)s - %(asctime)s,%(msecs)d - %(levelname)s:%(levelno)d - %(message)s"


DEFAULT_ROOT_LOG_LEVEL = "INFO"
DEFAULT_CONSOLE_LOG_LEVEL = "INFO"
DEFAULT_FILE_LOG_LEVEL = "INFO"
DEFAULT_SMTP_LOG_LEVEL = "ERROR"
DEFAULT_SMTP_LOG_FLUSH_LEVEL = "CRITICAL"


METALOG_LEVEL = (
    "METALOG"
)  # level for CountingLogger to use when writing its own log message counts, set above
METALOG = NOTSET + (DEBUG - NOTSET) // 2
PROGRESS_LEVEL = "PROGRESS"  # level above info for reporting long-running job progress
PROGRESS = 25

TRACE_LEVEL = (
    "TRACE"
)  # for super fine-grained logging, e.g. of function signatures and return values
TRACE = 1

DEFAULT_FORMATTER_CONFIG = {
    "format": DEFAULT_LOG_MSG_FMT,
    "datefmt": DEFAULT_LOG_DATE_FMT,
}

DEFAULT_CONSOLE_HANDLER_CONFIG = {
    "class": "logging.StreamHandler",
    "formatter": "default",
    "level": DEFAULT_CONSOLE_LOG_LEVEL,
}

DEFAULT_CONSOLE_HANDLER_MP_CONFIG = {
    "class": "bourbaki.application.logging.handlers.MultiProcStreamHandler",
    "formatter": "default",
    "level": DEFAULT_CONSOLE_LOG_LEVEL,
}

# note that the file handler config needs a filename and optionally a maxBytes int
DEFAULT_FILE_HANDLER_CONFIG = {
    "class": "logging.handlers.RotatingFileHandler",
    "formatter": "default",
    "level": DEFAULT_FILE_LOG_LEVEL,
    "filename": None,
    "maxBytes": None,
}

DEFAULT_FILE_HANDLER_MP_CONFIG = {
    "class": "bourbaki.application.logging.handlers.MultiProcRotatingFileHandler",
    "formatter": "default",
    "level": DEFAULT_FILE_LOG_LEVEL,
    "filename": None,
    "maxBytes": None,
}

# note that the smtp handler config needs a capacity, mailhost, toaddrs
DEFAULT_SMTP_HANDLER_CONFIG = {
    "class": "bourbaki.application.logging.handlers.BufferingSMTPHandler",
    "formatter": "default",
    "level": DEFAULT_SMTP_LOG_LEVEL,
    "mailhost": None,
    "credentials": None,
    "toaddrs": None,
    "capacity": None,
    "secure": None,
    "flushLevel": DEFAULT_SMTP_LOG_FLUSH_LEVEL,
}

DEFAULT_SMTP_HANDLER_MP_CONFIG = {
    "class": "bourbaki.application.logging.handlers.MultiProcBufferingSMTPHandler",
    "formatter": "default",
    "level": DEFAULT_SMTP_LOG_LEVEL,
    "mailhost": None,
    "credentials": None,
    "toaddrs": None,
    "capacity": None,
    "secure": None,
    "flushLevel": DEFAULT_SMTP_LOG_FLUSH_LEVEL,
}

empty_config_dict = {
    "version": 1,
    "formatters": {},
    "handlers": {},
    "root": {"level": DEFAULT_CONSOLE_LOG_LEVEL},
}
