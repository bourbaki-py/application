# coding:utf-8
import os
import multiprocessing
from itertools import zip_longest
from logging import Logger
from bourbaki.ioutils.pickleutils import pickle_dump
from bourbaki.hardware import report_hardware_status


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
        raise TypeError("You must pass a logging.Logger instance for logger; got {}".format(type(logger)))

    if init is None:
        init = init_logger
        initargs = (logger,)
    else:
        if not callable(init):
            raise TypeError("init must be a callable to be executed at the initialization of a process")
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
                    raise ValueError("if args are tuples, they must be 2-tuples of (args_tuple, kwargs_dict)")
            if isinstance(a, dict):
                args, kwargs = (), a
            elif isinstance(a, list):
                args, kwargs = a, {}
            elif a is None:
                args, kwargs = (), {}

            results.append(f(*args, **kwargs))

        return results


class report_and_persist:
    """
    chunks = EqualSlices(things_to_run_inference_on, size=100000)

    with mp.Pool(nproc) as pool:
        inference_chunks = pool.starmap(report_and_persist(infer, len(chunks), savedir="results/"),
                                        enumerate(chunks))
                                        )
    """

    def __init__(self, f, total_tasks=None, *, hardware_report=False, warn_mem_threshold=2e9,
                 savedir=None, persist_func=pickle_dump, ext='.pkl'):
        self.f = f
        self.total = total_tasks
        self.hardware_report = hardware_report
        self.warn_mem_threshold = warn_mem_threshold

        if not os.path.exists(savedir):
            os.mkdir(savedir)
        self.savedir = savedir
        self.persist = persist_func
        self.ext = ext

    def __call__(self, i, args):
        if self.hardware_report:
            report_hardware_status(warn_mem_threshold=self.warn_mem_threshold)

        if not isinstance(args, tuple):
            result = self.f(args)
        else:
            result = self.f(*args)

        if self.savedir:
            self.persist(result, os.path.join(self.savedir, "{}{}".format(str(i).rjust(6, "0"), self.ext)))

        print("finished job {}{}"
              .format(i,
                      " of {}".format(self.total)
                      if self.total is not None else ''
                      )
              )

        return result
