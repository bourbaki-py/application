# coding:utf-8
import typing
import enum
from inspect import signature, Signature, Parameter
from itertools import chain
from typing_inspect import is_optional_type
from bourbaki.introspection.generic_dispatch import (
    GenericTypeLevelSingleDispatch,
    UnknownSignature,
    const,
)
from bourbaki.introspection.generic_dispatch_helpers import UnionWrapper, LazyWrapper
from bourbaki.introspection.classes import (
    classpath,
    parameterized_classpath,
    most_specific_constructor,
)
from bourbaki.introspection.callables import (
    has_varargs,
    get_globals,
    get_callable_params,
    function_classpath,
)
from bourbaki.introspection.wrappers import lru_cache_sig_preserving
from bourbaki.introspection.types import (
    issubclass_generic,
    is_top_type,
    fully_concretize_type,
    get_generic_params,
    get_named_tuple_arg_types,
    BuiltinAtomic,
    NonStrCollection,
    NonStdLib,
    LazyType,
    NamedTupleABC,
)
from .exceptions import (
    ConfigIOUndefined,
    ConfigIOUndefinedForKeyType,
    ConfigCollectionKeysNotAllowed,
)
from .utils import (
    type_spec,
    default_repr_values,
    byte_repr,
    any_repr,
    ellipsis_,
    repr_type,
    Empty,
)
from .inflation import CONSTRUCTOR_KEY, CLASSPATH_KEY, KWARGS_KEY, ARGS_KEY
from .parsers import EnumParser

NoneType = type(None)

null_config_repr = "<null>"

bytes_config_repr = [byte_repr, ellipsis_]
bool_config_repr = type_spec(bool)

bytes_config_key_repr = "b'\\x{}{}'".format(byte_repr, ellipsis_)
bool_config_key_repr = "{}|{}".format(repr(True), repr(False))

config_repr_values = default_repr_values.copy()
config_repr_values.update(
    [
        (typing.ByteString, bytes_config_repr),
        (bool, bool_config_repr),
        (NoneType, null_config_repr),
    ]
)

config_key_repr_values = default_repr_values.copy()
config_key_repr_values.update(
    [
        (bool, bool_config_key_repr),
        (typing.ByteString, bytes_config_key_repr),
        # don't try to parse complex types for keys
        (typing.Any, any_repr),
        (NoneType, null_config_repr),
    ]
)


ONLY_REQUIRED_ARGS = False
LITERAL_DEFAULTS = True


def config_repr_all_args():
    global ONLY_REQUIRED_ARGS
    ONLY_REQUIRED_ARGS = False


def config_repr_only_required_args():
    global ONLY_REQUIRED_ARGS
    ONLY_REQUIRED_ARGS = True


def config_repr_literal_defaults():
    global LITERAL_DEFAULTS
    LITERAL_DEFAULTS = True


def config_repr_non_literal_defaults():
    global LITERAL_DEFAULTS
    LITERAL_DEFAULTS = False


@lru_cache_sig_preserving(None)
def config_repr_callable(
    f: typing.Callable, *args: type, only_required_args=None, literal_defaults=None
):
    if args:
        params = get_callable_params(f)
        param_dict = dict(zip(params, args))
    else:
        param_dict = None

    repr_, sig = config_repr_callable_args(
        f,
        param_dict,
        skip_self=False,
        only_required_args=only_required_args,
        literal_defaults=literal_defaults,
    )
    repr_[CONSTRUCTOR_KEY] = classpath(f)

    return_ = sig.return_annotation
    if return_ not in (Parameter.empty, object, typing.Any):
        return_ = fully_concretize_type(return_, param_dict, get_globals(f))
        repr_[CLASSPATH_KEY] = parameterized_classpath(return_)

    return repr_


@lru_cache_sig_preserving(None)
def config_repr_class(
    t: typing.Type,
    *args: type,
    only_required_args=None,
    literal_defaults=None,
    constructor: typing.Optional[typing.Union[str, typing.Callable]] = None
):
    skip_self = False
    if constructor is None:
        # don't use just the type for the signature; in cases where Generic is subclassed for instance you'll
        # get an uninformative *args, **kwargs signature
        init = most_specific_constructor(t)
        skip_self = True
        add_constructor = False
    elif isinstance(constructor, str):
        try:
            init = getattr(t, constructor)
        except AttributeError:
            raise AttributeError(
                "constructor name '{}' is not an attribute of type {}".format(
                    constructor, t
                )
            )
        add_constructor = True
    elif callable(constructor):
        init = constructor
        add_constructor = True
    else:
        raise TypeError(
            "if passed, constructor must be a callable or attribute name; got {}".format(
                type(constructor)
            )
        )

    params = get_generic_params(t)
    param_dict = dict(zip(params, args))

    repr_, sig = config_repr_callable_args(
        init,
        param_dict,
        skip_self=skip_self,
        only_required_args=only_required_args,
        literal_defaults=literal_defaults,
    )

    if args:
        if len(args) == 1:
            args = args[0]
        type_ = t[args]
    else:
        type_ = t

    repr_[CLASSPATH_KEY] = parameterized_classpath(
        fully_concretize_type(type_, param_dict, get_globals(t))
    )
    if add_constructor:
        repr_[CONSTRUCTOR_KEY] = classpath(init)
    return repr_


def config_repr_callable_args(
    init,
    param_dict=None,
    skip_self=False,
    only_required_args=None,
    literal_defaults=None,
):
    if only_required_args is None:
        only_required_args = ONLY_REQUIRED_ARGS
    if literal_defaults is None:
        literal_defaults = LITERAL_DEFAULTS

    if isinstance(init, Signature):
        sig = init
        globals_ = None
    else:
        sig = signature(init)
        globals_ = get_globals(init)

    concretize = param_dict or globals_
    append_positionals = has_varargs(sig)
    arg_reprs, kwarg_reprs = [], {}
    parameter_iter = iter(sig.parameters.items())
    if skip_self:
        next(parameter_iter)

    for name, param in parameter_iter:
        if literal_defaults and (param.default not in (Parameter.empty, None)):
            r = param.default
        else:
            if concretize:
                type_ = fully_concretize_type(param.annotation, param_dict, globals_)
            else:
                type_ = param.annotation
            r = config_repr(type_)

        if param.kind is Parameter.POSITIONAL_ONLY:
            arg_reprs.append(r)
        elif param.kind is Parameter.VAR_POSITIONAL:
            arg_reprs.extend([r, ellipsis_])
        elif param.kind is Parameter.VAR_KEYWORD:
            kwarg_reprs[ellipsis_] = r
        elif (
            only_required_args
            and param.default is not Parameter.empty
            and is_optional_type(param.annotation)
        ):
            # only skip once we're past the positionals, to avoid skipping args
            continue
        elif param.kind is Parameter.KEYWORD_ONLY:
            kwarg_reprs[name] = r
        else:
            if append_positionals:
                arg_reprs.append(r)
            else:
                kwarg_reprs[name] = r

    repr_ = {KWARGS_KEY: kwarg_reprs}
    if arg_reprs:
        repr_[ARGS_KEY] = arg_reprs

    return repr_, sig


# the main method

config_repr = GenericTypeLevelSingleDispatch(
    "config_repr", isolated_bases=[typing.Union, NonStdLib]
)

config_key_repr = GenericTypeLevelSingleDispatch(
    "config_key_repr", isolated_bases=[typing.Union, NonStdLib]
)

config_repr.register(BuiltinAtomic)(type_spec)


@config_repr.register_all(typing.Any, typing.Generic, NonStdLib)
def config_repr_any(t, *types, **kw):
    if is_top_type(t):
        return any_repr
    return config_repr_class(t, *types, **kw)


class _ConfigReprUnion(UnionWrapper):
    tolerate_errors = (ConfigIOUndefined, UnknownSignature)
    tolerate_errors_call = ()
    exc_class = ConfigIOUndefined

    @staticmethod
    def getter(t):
        return const(config_repr(t))

    @staticmethod
    def reduce(reprs):
        reprs = list(reprs)
        if all(isinstance(r, (str, NoneType)) for r in reprs):
            return _ConfigKeyReprUnion.reduce(filter(None, reprs))
        return list(chain.from_iterable((r, "OR") for r in reprs))[:-1]


ConfigReprUnion = lru_cache_sig_preserving(None)(_ConfigReprUnion)


@config_repr.register(typing.Union)
def config_repr_union(u, *types):
    return ConfigReprUnion(u, *types)(None)


@config_repr.register(typing.Tuple)
def config_repr_tuple(t, *types):
    if types and types[-1] is not Ellipsis:
        return list(map(config_repr, types))
    elif not types:
        return [any_repr, ellipsis_]
    else:
        return [config_repr(types[0]), ellipsis_]


@config_repr.register(NamedTupleABC)
def config_repr_namedtuple(t, *types):
    if not types:
        types = get_named_tuple_arg_types(t)
    return dict(zip(t._fields, map(config_repr, types)))


@config_repr.register(typing.Mapping)
def config_repr_mapping(m, k=object, v=object):
    # have to check this here because the key type param is invariant; we can't resolve from a base class
    if issubclass_generic(k, NonStrCollection):
        raise ConfigCollectionKeysNotAllowed((m, k, v))
    try:
        key_repr = config_key_repr(k)
    except UnknownSignature:
        raise ConfigIOUndefinedForKeyType((m, k, v))
    else:
        return {key_repr: config_repr(v), ellipsis_: ellipsis_}


@config_repr.register(typing.Collection)
def config_repr_seq(s, t=Empty, e=ellipsis_):
    return [config_repr(t), ellipsis_]


@config_repr.register(LazyType)
def lazy_config_repr(lazy, ref):
    return LazyConfigRepr(lazy, ref)()


config_repr.register(typing.Type)(repr_type)
config_key_repr.register(typing.Type)(repr_type)


class LazyConfigRepr(LazyWrapper):
    @staticmethod
    def getter(type_):
        return const(config_repr(type_))


config_repr.register_from_mapping(config_repr_values, as_const=True)


@config_repr.register_all(enum.Enum, enum.IntEnum)
@config_key_repr.register_all(enum.Enum, enum.IntEnum)
def config_repr_enum(enum_):
    return EnumParser(enum_).config_repr()


class _ConfigKeyReprUnion(UnionWrapper):
    tolerate_errors = (ConfigIOUndefined, UnknownSignature)
    tolerate_errors_call = ()
    exc_class = ConfigIOUndefinedForKeyType
    getter = config_key_repr
    reduce = staticmethod(" OR ".join)

    @staticmethod
    def getter(t):
        return const(config_key_repr(t))


ConfigKeyReprUnion = lru_cache_sig_preserving(None)(_ConfigKeyReprUnion)


@config_key_repr.register(typing.Union)
def config_key_repr_union(u, *types):
    return ConfigKeyReprUnion(u, *types)(None)


config_key_repr.register_all(int, float)(type_spec)

config_key_repr.register_from_mapping(config_key_repr_values, as_const=True)
