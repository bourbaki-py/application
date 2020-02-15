# coding:utf-8
# Import commonly used things into the top-level namespace for quick import
from . import config, defaults, interface, timing, loggers, analysis
from .interface import Logged, InstanceLoggerNamingConvention
from .config import (
    configure_default_logging,
    configure_debug_logging,
    configure_custom_logging,
    enable_console_logging,
    disable_console_logging,
)
from .defaults import (
    DEFAULT_LOG_MSG_FMT,
    DEFAULT_LOG_DATE_FMT,
    DEFAULT_CONSOLE_LOG_LEVEL,
    DEFAULT_FILE_LOG_LEVEL,
)
from .timing import timed_context, TimedTaskContext
from .analysis import log_file_to_df
from .loggers import CountingLogger, ProgressLogger
from .handlers import (
    MemoryHandler,
    SMTPHandler,
    BufferingSMTPHandler,
    MultiProcHandler,
    MultiProcBufferingSMTPHandler,
    MultiProcStreamHandler,
    MultiProcRotatingFileHandler,
)
