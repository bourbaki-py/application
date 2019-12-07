#!/usr/bin/env python
# coding:utf-8
from logging import setLoggerClass
from bourbaki.application.logging.loggers import CountingLogger, SwissArmyLogger


class _TestLogger(SwissArmyLogger):
    def _log(self, level, msg, *a, **kw):
        msg = " ".join((nextcounter(), msg or ""))
        super()._log(level, msg, *a, **kw)


setLoggerClass(_TestLogger)
# mpl_logger = getLogger('matplotlib')
# mpl_logger.disabled = True

import os
import pickle
from itertools import chain
from collections import Counter
from warnings import warn
import pytest
from bourbaki.application.logging import LoggedMeta, getLogger, configure_debug_logging
from bourbaki.application.logging.defaults import (
    METALOG,
    DEFAULT_LOG_MSG_FMT,
    DEFAULT_LOG_DATE_FMT,
)
from bourbaki.application.logging.analysis import log_line_regex, log_file_to_df

global TestLoggedClass
MSG_COUNTER = 0
MSG_TYPES = ("debug", "info", "warn", "warning", "error", "critical")


def nextcounter():
    global MSG_COUNTER
    MSG_COUNTER += 1
    return str(MSG_COUNTER).zfill(4)


def get_test_instance(log_name: str):
    return TestLoggedClass("a", "few", "args", log_name=log_name)


@pytest.fixture(scope="module")
def logfile():
    path = "/tmp/test.log"
    return path


@pytest.fixture(scope="module")
def this_logfile(logfile):
    # paths = get_dated_files(logfile)
    # path = paths[-1]
    # yield path
    # # os.remove(path)
    return logfile


@pytest.fixture(scope="module")
def log_pickle_file():
    pickle_file = "/tmp/test_df.pkl"
    yield pickle_file
    os.remove(pickle_file)


@pytest.fixture
def test_pickle_path():
    path = "/tmp/test_instance.pkl"
    yield path
    os.remove(path)


@pytest.fixture
def logger():
    logger = getLogger(__name__)
    return logger


def test_setup(logfile):
    configure_debug_logging(
        filename=logfile, dated_logfiles=False, disable_existing_loggers=True
    )

    global TestLoggedClass, _TestLogger

    class TestLoggedClass(
        metaclass=LoggedMeta,
        level="DEBUG",
        use_full_path=False,
        verbose=True,
        logger_cls=_TestLogger,
        instance_naming="keyword",
    ):
        def talk(self, *args, **kwargs):
            logger = self.logger
            logger.info(
                "I'm a class instance and my args are {} and my kwargs are {}".format(
                    args, kwargs
                )
            )
            logger.warning("logged class Test Warning")
            logger.error("logged class TEST ERROR")


def parsed_message_counts(df):
    parsed_msgs = df.shape[0]
    parsed_multiline = (df.message.str.count("\n") > 0).sum()
    parsed_exceptions = (~df.stackTrace.isnull()).sum()
    msgtypes = dict(sorted(Counter(df.levelname).items()))
    return parsed_msgs, parsed_multiline, parsed_exceptions, msgtypes


def all_message_counts():
    msg, multi, err, msgtypes = 0, 0, 0, Counter()
    for log in chain(_TestLogger.manager.loggerDict.values()):
        if hasattr(log, "name"):
            print(log, log.name, log.__class__)
        if isinstance(log, _TestLogger):
            msg += log.total
            multi += log.multiline
            err += log.stacktraces
            msgtypes += log.levelcounts
    print(msg, multi, err, msgtypes)
    return msg, multi, err, dict(sorted(msgtypes.items()))


def log_all_counts():
    for log in chain(_TestLogger.manager.loggerDict.values()):
        if isinstance(log, CountingLogger):
            log._report_stats()


def warn_logger_disabled(logger):
    if logger.disabled:
        warn("This logger is disabled!")
        warn("The logger and its handlers are {}, {}".format(logger, logger.handlers))
        warn(
            "The parent logger and its handlers are {}, {}".format(
                logger.parent, logger.parent.handlers
            )
        )


def test_logging_multiline1(logger):
    logger.debug("This is:\n\t\t\ta multiline log message!")


def test_logged_class():
    ti1 = get_test_instance("one")
    ti2 = get_test_instance("two")

    ti1.talk(1, 2, 3, foo="bar")
    ti2.talk(list(range(10)), bar="baz")

    ti1.talk("second arg is a logger", ti1.logger)


def test_logged_class_pickle(test_pickle_path):
    ti3 = get_test_instance("three")

    with open(test_pickle_path, "wb") as f:
        pickle.dump(ti3, f)

    with open(test_pickle_path, "rb") as f:
        ti4 = pickle.load(f)

    ti4.logger.info("Still kickin'!")
    assert ti4.__logname__ == ti3.__logname__
    assert ti4.logger.name == ti3.logger.name


def test_log_exception(logger):
    try:
        1 / 0
    except:
        logger.critical("You CANNOT do that!", exc_info=True)


def test_log_multiline(logger):
    logger.debug("Here's a multiline message -\n    see, this is the second line.")


def test_logfile_dataframe_parse(this_logfile, logger):
    logger.info("Now parsing {} to a dataframe".format(this_logfile))
    logger.debug(
        "parsing using regex:\n\t%s"
        % log_line_regex(DEFAULT_LOG_MSG_FMT, DEFAULT_LOG_DATE_FMT)
    )

    # this adds some METALOG-level messages to the file
    log_all_counts()
    # which should be parsed here
    parsed_log = log_file_to_df(
        this_logfile, datetime_index=True, validate=True, raise_=False
    )

    msgid = parsed_log.message[parsed_log.levelno != METALOG].str.slice(0, 4)
    msgid = msgid[msgid.str.match(r"^[0-9]+$")].astype(int).values
    assert msgid[0] == 1
    assert msgid[-1] == MSG_COUNTER
    # assert np.all(np.diff(msgid) == 1)
    assert_parsed_equals_logged(parsed_message_counts(parsed_log), all_message_counts())

    logger.info("parsed dataframe tail:\n{}".format(str(parsed_log.tail(2))))


def test_logfile_dataframe_parse_to_pickle(this_logfile, log_pickle_file, logger):
    log_all_counts()
    parsed_log = log_file_to_df(
        this_logfile, datetime_index=True, validate=True, raise_=False
    )
    assert_parsed_equals_logged(parsed_message_counts(parsed_log), all_message_counts())

    parsed_log = log_file_to_df(
        this_logfile, datetime_index=True, validate=True, raise_=False
    )
    parsed_log.to_pickle(log_pickle_file)

    logger.info(
        "You can inspect the parsed log file using pandas.read_pickle('%s')"
        % log_pickle_file
    )


def assert_parsed_equals_logged(parsed_message_counts, all_message_counts):
    total_msgs, total_multiline, total_exceptions, total_types = all_message_counts
    parsed_msgs, parsed_multiline, parsed_exceptions, parsed_types = (
        parsed_message_counts
    )
    assert total_multiline <= parsed_multiline
    assert total_exceptions <= parsed_exceptions
    assert total_msgs <= parsed_msgs
    for k, v in parsed_types.items():
        assert v >= total_types.get(k, 0)
