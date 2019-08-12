#coding:utf-8
from typing import Tuple, Dict, Callable, Union
from inspect import Signature, Parameter, signature, getmro
from itertools import chain
from logging import Logger, addLevelName, getLoggerClass
from typing import Optional
from . import defaults
from .config import LogLevel, instance_naming_opts
from .helpers import validate_log_level
from .loggers import printLogger, ProgressLogger

addLevelName(defaults.TRACE, defaults.TRACE_LEVEL)


class WithLoggerMixin:
    __logger__ = None
    __logger_cls__ = None
    __log_name__ = None
    __log_level__ = defaults.DEFAULT_CONSOLE_LOG_LEVEL

    @property
    def logger(self):
        logger = self.__dict__.get('__logger__', None)
        if logger is None:
            # construct an instance logger
            instance_name = self.__log_name__
            logger_cls = self.__logger_cls__ or getLoggerClass()
            logger = logger_cls.manager.getLogger(instance_name)
            if logger is not type(self).logger and self.__log_level__ is not None:
                # set an instance level if different than class level
                logger.setLevel(self.__log_level__)
            self.__logger__ = logger
        return logger

    @logger.setter
    def logger(obj, logger):
        assert isinstance(logger, Logger), ("class logger must be an instance of logging.Logger, not {}"
                                            .format(type(logger)))

        obj.__logger__ = logger


# this would ideally bring the metaclass LoggedMeta along for the ride, but in case anyone wants to use it
# to implement the same interface without the potential hiccups of metaclasses, here it is.
# This has the nice side-effect of requiring users of LoggedMeta and its machinery to be explicit that they're using
# a metaclass
class Logged(WithLoggerMixin):
    __verbose__ = defaults.VERBOSE_INSTANCE_INITS
    __instance_naming__ = defaults.DEFAULT_INSTANCE_NAMING
    __name_keyword__ = defaults.DEFAULT_LOG_NAME_KEYWORD
    __last_instance_id__ = None

    def __getstate__(self):
        self.logger.debug("Getting state for pickling/copying")
        # can't pickle RThreadLock objects!
        state = self.__dict__.copy()
        state.pop("__logger__", None)
        self.logger.debug("Got state dict with keys {}".format(sorted(state.keys())))
        return state


missing = object()


class LoggedMeta(type, WithLoggerMixin):
    """
    Metaclass for creating logged classes
    logging-related args can be passed to the metaclass at the top of a class declaration

    example:

    class MyClass(metaclass=LoggedMeta, instance_naming="int"):
        def __init__(self, *args):
            # at this point, the class __new__ has been called and the instance 'self' has a logger
            self.logger.debug("initializing a {} with args {}".format(__class__, args))

    my_instance = MyClass(1, 2, 3)
    my_instance.logger.info("hello!")
    """

    def __new__(mcs, name, bases, namespace,
                level: Optional[LogLevel]=missing,
                use_full_path: bool=False,
                instance_naming: Optional[Union[str, Callable[[object], str]]]=missing,
                name_keyword: str=missing,
                logger_cls: Optional[type]=ProgressLogger,
                verbose: bool=missing):
        """
        Metaclass that gives types/classes and each of their instances a logger (potentially with an
            instance-specific name, depending on the value of instance_naming).

        :param level: the logging level as passed to logging.Logger. messages below this level will be ignored
        :param use_full_path: bool indicating whether to use the full classpath for naming, or just the
            class name. Full class paths can be long and can clutter log files but may help when classes
            have ambiguous names
        :param instance_naming: str or None or callable, one of the following:
            "int": simply use a unique integer to identify new instances, starting from 1
            "hex": use the hexadecimal of the id() function, as used by standard __repr__ method
            "keyword": use a keyword arg from the call to the class constructor
                (this is used implicitly when a value is passed for the name_keyword arg)
            None: don't log from instances separately; just use the class-level logger.
            callable: apply the callable to the named args passed to the constructor to yield a name.
        :param name_keyword: a keyword to use to set the names of instances in the class constructor. This is only used
            when instance_naming is "keyword". This value is appended to the class logger's name following a dash.
            Default is 'log_name'.
        """
        # add Logged as a superclass to allow access to the logger property, allowing lazy logger instantiation
        if Logged not in chain.from_iterable(map(getmro, bases)):
            bases = (Logged, *bases)

        for val, attr in [
            (level, '__log_level__'),
            (instance_naming, '__instance_naming__'),
            (name_keyword, '__name_keyword__'),
            (verbose, '__verbose__'),
            (logger_cls, '__logger_cls__')
        ]:
            # prevents superclass attribute changes from affecting the class - flatten all attr refs from the
            # superclass hierarchy above
            namespace[attr] = namespace_bases_getattr(namespace, bases, attr) if val is missing else val

        validate_log_level(namespace['__log_level__'])
        instance_naming = namespace['__instance_naming__']
        assert instance_naming in instance_naming_opts or callable(instance_naming), \
               "instance_naming must be callable or one of {}; got {}".format(instance_naming_opts, instance_naming)

        name_keyword = namespace['__name_keyword__']
        extra_kw = {name_keyword: str} if instance_naming == 'keyword' else None
        logname = name if not use_full_path else '.'.join((namespace['__module__'], name))
        sig = init_sig(namespace, bases, extra_kw=extra_kw)

        namespace.update(
            __log_name__=logname,
            __last_instance_id__=None,
            # this allows informative introspection in interactive environments such as IPython
            __signature__=sig,
        )

        # construct the class and return it
        cls = type.__new__(mcs, name, bases, namespace)
        return cls

    def __call__(cls: Logged, *args, **kwargs):
        # control instance creation - this is called when you construct an instance of a class
        # this usually happens after logging has been configured, so messages will be faithfully logged
        init_success_msg = "Initialized new instance successfully"
        init_failure_msg = "Instance initialization failed"

        # property lookup on the metaclass, possibly instantiating the logger for the first time
        cls_logger = cls.logger

        if cls.__verbose__:
            cls_logger.debug("constructor called with args ({})".format(call_repr(*args, **kwargs)))
        # create the instance; at this point the class has a logger, which can be used in the cls.__new__ body if needed
        if cls.__new__ is object.__new__:
            obj = cls.__new__(cls)
            new_called = False
        else:
            obj = cls.__new__(cls, *args, **kwargs)
            new_called = True
        cls_logger.debug("Created new instance successfully")
        if new_called:
            cls_logger.debug(init_success_msg)

        naming_convention = cls.__instance_naming__

        if naming_convention is None:
            # then we just use the class logger's name
            instance_name = cls_logger.name
        else:
            if naming_convention == "keyword":
                instance_name = kwargs.get(cls.__name_keyword__)

                if instance_name is None:
                    instance_name = cls_logger.name
                    cls_logger.warning("No name passed to constructor keyword {}; using class logger name"
                                       .format(cls.__name_keyword__))
                else:
                    instance_name = cls_logger.name + str(instance_name)
            elif naming_convention == "int":
                # get and increment the last instance id from the class
                last_id = cls.__last_instance_id__ or 0
                new_id = last_id + 1
                cls.__last_instance_id__ = new_id
                # and name a new instance as '<class log name>-<int id>'
                instance_name = cls_logger.name + "-" + str(new_id)
            elif naming_convention == "hex":
                # use the builtin hex id as implemented by the default __repr__ method
                instance_name = cls_logger.name + "-" + hex(id(obj))
            elif callable(naming_convention):
                sig = signature(cls.__init__)
                params = sig.bind(obj, *args, **kwargs).arguments
                naming_sig = signature(naming_convention)
                new_kw = {k: a for k, a in params.items() if k in naming_sig.parameters}
                instance_name = naming_convention(**new_kw)
            else:
                err_msg = "a logging class's __instance_naming__ attribute must be in {} or callable; got {}" \
                    .format(instance_naming_opts, naming_convention)
                cls_logger.error(err_msg)
                raise ValueError(err_msg)

        setattr(obj, '__log_name__', instance_name)

        init_success_msg += " with log name '{}'".format(instance_name)
        init_failure_msg += " for instance with log name '{}'".format(instance_name)

        # now the instance can construct a logger; it can be used in the instance initialization
        if not new_called:
            try:
                if cls.__init__ is object.__init__:
                    cls.__init__(obj)
                else:
                    cls.__init__(obj, *args, **kwargs)
            except Exception as e:
                cls_logger.error(init_failure_msg, exc_info=True)
                raise e
            else:
                cls_logger.debug(init_success_msg)

        return obj


def short_repr(obj):
    s = repr(obj)
    if len(s) <= defaults.MAX_REPR_LEN:
        return s
    else:
        return s[:defaults.MAX_REPR_LEN // 2] + ' ... ' + s[len(s) - (defaults.MAX_REPR_LEN // 2):len(s)]


def call_repr(*args, **kwargs):
    # print the call signature of a function as it was entered
    return ', '.join(chain(map(short_repr, args),
                           map(lambda tup: tup[0] + "=" + short_repr(tup[1]), kwargs.items())))


def bases_getattr(bases, attr, default=None):
    if not bases:
        return default
    return getattr(bases[0], attr, bases_getattr(bases[1:], attr, default))


def namespace_bases_getattr(namespace, bases, attr, default=None):
    return namespace.get(attr, bases_getattr(bases, attr, default))


def init_sig(namespace: dict, bases: Tuple[type], extra_kw: Optional[Union[Tuple[str], Dict[str, type]]]=None):
    init = namespace_bases_getattr(namespace, bases, '__init__')
    sig = signature(init)
    oldparams = list(sig.parameters.values())[1:]  # throw away 'self' arg for the class signature

    if oldparams and oldparams[-1].kind is Parameter.VAR_KEYWORD:
        varkw = oldparams[-1:]
        oldparams = oldparams[:-1]
    else:
        varkw = []

    if not extra_kw:
        newparams = []
    elif isinstance(extra_kw, tuple):
        newparams = [Parameter(k, kind=Parameter.KEYWORD_ONLY) for k in extra_kw]
    else:
        newparams = [Parameter(k, kind=Parameter.KEYWORD_ONLY, annotation=t) for k, t in extra_kw.items()]

    newsig = Signature(oldparams + newparams + varkw, return_annotation=sig.return_annotation)
    return newsig
