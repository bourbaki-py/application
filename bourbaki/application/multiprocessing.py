# coding:utf-8
import os
import multiprocessing
from itertools import zip_longest
from logging import Logger


def get_nproc(n):
    if not n:
        return None
    elif not isinstance(n, int):
        raise TypeError("if truthy, n must be an integer")

    ncores = os.cpu_count()
    if n > 0:
        nproc = min(n, ncores)
    elif n < 0:
        nproc = max(1, ncores + n + 1)
    elif n == 0:
        raise ValueError("nproc must be positive or negative; got 0")

    return nproc


def init_logger(logger_: Logger):
    proc = multiprocessing.current_process()
    global logger
    logger = logger_
    logger.info("process {} initialized successfully".format(proc))


def get_pool(nproc, logger, init=None):
    """Put a logger in the global namespaces of your processes at init.
    Make sure your logger's handler is process-safe, e.g. application.logging.MultiProcStreamHandler or
    application.logging.MultiProcRotatingFileHandler"""
    if not isinstance(logger, Logger):
        raise TypeError(
            "You must pass a logging.Logger instance for logger; got {}".format(
                type(logger)
            )
        )

    if init is None:
        init = init_logger
        initargs = (logger,)
    else:
        if not callable(init):
            raise TypeError(
                "init must be a callable to be executed at the initialization of a process"
            )
        init = apply_all(init_logger, init)
        initargs = [[logger]]

    return multiprocessing.Pool(nproc, initializer=init, initargs=initargs)


class apply_all:
    """Acts as a wrapper function to apply all of a sequence of functions a the initialization of a process worker."""

    def __init__(self, *funcs):
        self.fs = tuple(funcs)

    def __call__(self, *args):
        """pass one (args, kwargs) tuple or kwargs dict for each function to act on. If less args are supplied than
        there are functions, the tail functions are called without arguments. If more tuples are supplied than there
        are functions, an error is thrown"""

        results = []
        for f, a in zip_longest(self.fs, args, fillvalue=((), {})):
            if isinstance(a, tuple):
                if len(a) == 2:
                    args, kwargs = a
                    if args is None:
                        args = ()
                    if kwargs is None:
                        kwargs = {}
                else:
                    raise ValueError(
                        "if args are tuples, they must be 2-tuples of (args_tuple, kwargs_dict)"
                    )
            if isinstance(a, dict):
                args, kwargs = (), a
            elif isinstance(a, list):
                args, kwargs = a, {}
            elif a is None:
                args, kwargs = (), {}

            results.append(f(*args, **kwargs))

        return results
