# coding:utf-8
from typing import Callable
from types import MethodType
from enum import Enum
from functools import wraps
from inspect import signature
from logging import Logger, addLevelName, getLoggerClass
from . import defaults

addLevelName(defaults.TRACE, defaults.TRACE_LEVEL)

LOG_NAME_KWARG = "__logname__"


class InstanceLoggerNamingConvention(Enum):
    int = "append an incremented id to the class name for instance logger names"
    hexaddress = "append the hexadecimal memory address to the class name for instance logger names"
    keyword = (
        "use the keyword arg %s to pass in a custom instance logger name via the constructor"
        % LOG_NAME_KWARG
    )


class Logged:
    __logger__ = None
    __log_level__ = None
    __verbose__ = False
    __log_tracebacks__ = True
    __instance_naming__ = None
    __last_instance_id__ = None

    @property
    def __logname__(self):
        name = self.__dict__.get("__logname__")
        if name is None:
            convention = self.__instance_naming__
            if convention is None:
                cls = type(self)
                name = cls.__qualname__
            elif isinstance(convention, InstanceLoggerNamingConvention):
                cls = type(self)
                clsname = cls.__qualname__
                if convention is InstanceLoggerNamingConvention.int:
                    lastid = cls.__last_instance_id__ + 1
                    name = "{}-{}".format(clsname, lastid)
                    __last_instance_id__ = lastid
                elif convention is InstanceLoggerNamingConvention.hexaddress:
                    id_ = hex(id(self))
                    name = "{}@{}".format(clsname, id_)
                else:
                    # keyword option, but not passed to constructor
                    name = self.__dict__.get("__logname__", clsname)
            elif callable(convention):
                if isinstance(convention, MethodType):
                    # bound method from function defined in the namespace of the class
                    name = convention()
                else:
                    # attribute set at __init__ as function literal, or some other callable set at the class level
                    name = convention(self)
            else:
                raise TypeError(
                    "__instance_naming__ attribute must be an instance of {} or a callable; got {}".format(
                        InstanceLoggerNamingConvention, type(convention)
                    )
                )

        return name

    @__logname__.setter
    def __logname__(self, name):
        if not isinstance(name, str):
            raise TypeError("__logname__ must be a string")
        self.__dict__["__logname__"] = name
        logger = self.__dict__.get("__logger__")
        if logger is not None:
            logger.name = name

    @property
    def __logger_cls__(self):
        return getLoggerClass()

    def __init_subclass__(cls, **kwargs):
        convention = cls.__instance_naming__
        if convention is None:
            pass
        elif isinstance(convention, str):
            convention = getattr(InstanceLoggerNamingConvention, convention, None)
            if convention is None:
                raise ValueError(
                    "__instance_naming__ attribute, if a string, must be one of {}".format(
                        [c.name for c in InstanceLoggerNamingConvention]
                    )
                )
        elif not callable(convention) and not isinstance(
            convention, InstanceLoggerNamingConvention
        ):
            raise TypeError(
                "__instance_naming__ attribute must be either a callable taking a single instance of "
                "{} or an {} instance".format(cls, InstanceLoggerNamingConvention)
            )

        if cls.__verbose__ or convention is InstanceLoggerNamingConvention.keyword:
            cls.__init__ = verbose_init(cls.__init__)

        if convention is InstanceLoggerNamingConvention.int:
            cls.__last_instance_id__ = 0

        if cls.__verbose__:
            cls.__signature__ = signature(cls)

        cls.__instance_naming__ = convention

    @property
    def logger(self):
        logger = self.__dict__.get("__logger__", None)
        if logger is None:
            # construct an instance logger
            instance_name = self.__logname__
            logger_cls = self.__logger_cls__
            logger = logger_cls.manager.getLogger(instance_name)
            if self.__log_level__ is not None:
                logger.setLevel(self.__log_level__)
            self.__dict__["__logger__"] = logger

        return logger

    @logger.setter
    def logger(obj, logger):
        if not isinstance(logger, Logger):
            raise TypeError(
                "class logger must be an instance of logging.Logger; got {}".format(
                    type(logger)
                )
            )
        obj.__dict__["__logger__"] = logger

    def __getstate__(self):
        self.logger.debug(
            "Getting state for pickling/copying, excluding __logger__ attribute"
        )
        # can't pickle RThreadLock objects!
        state = self.__dict__.copy()
        state.pop("__logger__", None)
        self.logger.debug("Got state dict with keys %s", state.keys())
        return state


def verbose_init(init: Callable):
    @wraps(init)
    def __init__(self: Logged, *args, **kwargs):
        if self.__instance_naming__ is InstanceLoggerNamingConvention.keyword:
            name = kwargs.pop(LOG_NAME_KWARG, None)
            if name is not None:
                self.__logname__ = name
        if self.__verbose__:
            logger = self.logger
            cls = type(self)
            logger.debug("Initializing %s instance", cls)
            try:
                init(self, *args, **kwargs)
            except Exception as e:
                sig = cls.__signature__
                bound_args = sig.bind(*args, **kwargs)
                logger.error(
                    "Initialization failed for %s instance with args %s",
                    cls,
                    bound_args,
                    exc_info=self.__log_tracebacks__,
                )
        else:
            init(self, *args, **kwargs)

    return __init__
