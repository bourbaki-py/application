# coding:utf-8
from typing import Callable
from collections.abc import Mapping
from collections import OrderedDict
from functools import update_wrapper
from inspect import signature, Parameter
from itertools import chain
from logging import getLogger
from cytoolz import valmap
from bourbaki.introspection.imports import import_object, import_type
from bourbaki.introspection.types import (
    typetypes,
    eval_forward_refs,
    concretize_typevars,
    get_generic_origin,
    get_param_dict,
    reparameterized_bases,
    fully_concretize_type,
    issubclass_generic,
)
from bourbaki.introspection.types.compat import NEW_TYPING, _GenericAlias
from bourbaki.introspection.typechecking import isinstance_generic
from bourbaki.introspection.callables import to_bound_method_signature, get_globals
from bourbaki.introspection.classes import most_specific_constructor
from bourbaki.introspection.wrappers import cached_getter, lru_cache_sig_preserving
from .exceptions import ExceptionReprMixin, ConfigTypedInputError

config_decoder = None  # this will be imported later to avoid circular imports
logger = getLogger(__name__)
CLASSPATH_KEY = "__classpath__"
ARGS_KEY = "__args__"
KWARGS_KEY = "__kwargs__"
CONSTRUCTOR_KEY = "__constructor__"
INFLATABLE_CONFIG_KEYS = frozenset(
    [CLASSPATH_KEY, ARGS_KEY, KWARGS_KEY, CONSTRUCTOR_KEY]
)
NON_VARIADIC_KINDS = (
    Parameter.POSITIONAL_OR_KEYWORD,
    Parameter.KEYWORD_ONLY,
    Parameter.POSITIONAL_ONLY,
)
TYPE_TYPES = (type, *typetypes)


class ConfigInflationError(ValueError, ExceptionReprMixin):
    def __init__(self, func, argname, value, exc):
        super().__init__()
        self.func, self.argname, self.value, self.exc = func, argname, value, exc

    def __str__(self):
        return "Decoding config value {} for argument '{}' of function {} raised {}".format(
            repr(self.value), self.argname, self.func, self.exc
        )


def _is_inflatable_config(obj):
    return (
        isinstance(obj, Mapping)
        and (CLASSPATH_KEY in obj or CONSTRUCTOR_KEY in obj)
        and INFLATABLE_CONFIG_KEYS.issuperset(obj.keys())
    )


def inflate_config(conf, target_type=None):
    if _is_inflatable_config(conf):
        try:
            return instance_from(**conf, target_type=target_type)
        except Exception as e:
            raise ConfigTypedInputError(target_type, conf, e)
    return conf


def instance_from(
    __classpath__=None,
    __args__=None,
    __kwargs__=None,
    __constructor__=None,
    target_type=None,
):
    """
    Instantiate general values from configuration files. E.g. with the json-compatible configuration
        conf = {"__classpath__":"sklearn.cluster.KMeans", "__kwargs__": {"n_clusters": 10, "n_init": 10}},
        instance_from(**conf) returns an sklearn.cluster.KMeans clustering model.
    :param __classpath__: str, optional path to the class to be instantiated. If no __constructor__ is passed, this
        will be called directly, otherwise it will be used for a final instance check.
    :param __args__: optional positional args to be passed to the class constructor (or function if classpath refers to
        a general callable)
    :param __kwargs__: optional keyword args to be passed to the class constructor (or function if classpath refers to a
        general callable)
    :param __constructor__: optional path to a callable to call to construct the desired instance
    :param target_type: optional type to check the classpath against before attempting to inflate an instance
    :return: an instance of the class (or the results of calling the function) identified by classpath
    """
    logger.debug(
        "Attempting to instantiate {} instance with{} args {} and kwargs {}".format(
            __classpath__,
            " constructor {},".format(__constructor__)
            if __constructor__ is not None
            else "",
            __args__,
            __kwargs__,
        )
    )

    if __classpath__ is not None:
        cls = import_type(__classpath__)
        if not isinstance(cls, TYPE_TYPES):
            raise TypeError(
                "classpath {} does not specify a class or type; got {}".format(
                    __classpath__, cls
                )
            )
        # don't waste time on the construction if the specified type is incorrect
        if target_type is not None:
            target_type_ = concretize_typevars(target_type)
            if not issubclass_generic(cls, target_type_):
                raise TypeError(
                    "classpath {} does not specify a generic subclass of the target type {}".format(
                        __classpath__, target_type
                    )
                )
        # only check the instance if the constructor is other than the class itself
        instance_check = __constructor__ is not None
    else:
        instance_check = False
        cls = None

    if __constructor__ is not None:
        constructor = import_object(__constructor__)
        if not callable(constructor):
            raise TypeError(
                "constructor {} does not specify a callable; got {}".format(
                    __constructor__, constructor
                )
            )
    elif cls is None:
        raise ValueError("Must pass either __classpath__ or __constructor__")
    else:
        constructor = cls

    wrapper = typed_config_callable(constructor)

    if __kwargs__ is None and __args__ is None:
        obj = wrapper()
    elif __kwargs__ is None:
        obj = wrapper(*__args__)
    elif __args__ is None:
        obj = wrapper(**__kwargs__)
    else:
        obj = wrapper(*__args__, **__kwargs__)

    if instance_check and not isinstance_generic(obj, cls):
        raise TypeError(
            "Inflation using constructor {} resulted in a {} instance; expected {}".format(
                constructor, type(obj), cls
            )
        )

    logger.info(
        "Instantiated {} instance successfully{}".format(
            __classpath__,
            " with constructor {}".format(__constructor__)
            if __constructor__ is not None
            else "",
        )
    )

    return obj


class TypedConfigCallable:
    called = False
    __signature__ = None

    def __init__(self, func: Callable, param_dict=None, ignore_args=()):
        func_for_sig = func

        if isinstance(func, TYPE_TYPES):
            cls_for_sig, func_for_sig = most_specific_constructor(
                func, return_class=True
            )
            skip_first_arg = not isinstance(func_for_sig, staticmethod)

            _cls_for_sig = get_generic_origin(cls_for_sig)
            if param_dict is None:
                for base in chain((func,), reparameterized_bases(func)):
                    if get_generic_origin(base) is _cls_for_sig:
                        param_dict = get_param_dict(base)
        else:
            skip_first_arg = False

        try:
            sig = signature(func_for_sig)
        except TypeError as e:
            raise e
        except ValueError:
            # builtins and C extensions
            sig = None

        if skip_first_arg:
            sig = to_bound_method_signature(sig)

        update_wrapper(self, func_for_sig)
        self.__signature__ = sig
        self.func = func
        self.func_for_sig = func_for_sig
        self.param_dict = param_dict
        self.skip_first_arg = skip_first_arg
        self.ignore_args = set(ignore_args)

    @staticmethod
    def concretize_annotation(ann, globals_):
        return concretize_typevars(eval_forward_refs(ann, globals_))

    @property
    @cached_getter
    def decoders(self):
        # importing in a function call is ugly, but better than a giant source file, which is the only other way
        # of getting around the circular import
        global config_decoder
        if not TypedConfigCallable.called:
            from bourbaki.application.typed_io.config_decode import config_decoder

            TypedConfigCallable.called = True

        if self.__signature__ is None:
            return None

        globals_ = get_globals(self.func_for_sig)
        return OrderedDict(
            (
                name,
                config_decoder(
                    fully_concretize_type(p.annotation, self.param_dict, globals_)
                ),
            )
            for name, p in self.__signature__.parameters.items()
            if name not in self.ignore_args
        )

    def __call__(self, *args, **kwargs):
        if self.__signature__ is not None:
            bound = self.__signature__.bind(*args, **kwargs)
            bound_args = bound.arguments
            params = self.__signature__.parameters
            decoders = self.decoders

            for name, arg in bound_args.items():
                param = params[name]
                try:
                    if param.kind in NON_VARIADIC_KINDS:
                        bound_args[name] = decoders[name](arg)
                    elif param.kind is Parameter.VAR_KEYWORD:
                        bound_args[name] = valmap(decoders[name], arg)
                    elif param.kind is Parameter.VAR_POSITIONAL:
                        bound_args[name] = tuple(map(decoders[name], arg))
                except Exception as e:
                    raise ConfigInflationError(self.func, name, arg, e)

            bound.apply_defaults()
            args, kwargs = bound.args, bound.kwargs

        self.called = True
        return self.func(*args, **kwargs)


@lru_cache_sig_preserving(None)
def typed_config_callable(func, param_dict=None):
    return TypedConfigCallable(func, param_dict)
