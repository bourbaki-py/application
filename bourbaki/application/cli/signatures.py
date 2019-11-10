from typing import Callable, Collection, Dict, Set, List, Mapping, NamedTuple, Pattern, Iterable, Optional, Union
from collections import ChainMap
from functools import singledispatch
from enum import Enum
from itertools import chain
from inspect import Parameter, Signature
import re

from .decorators import cli_attrs
from .helpers import _validate_parse_order


class ArgKind(Enum):
    PositionalOnly = Parameter.POSITIONAL_ONLY
    PositionalOrKeyword = Parameter.POSITIONAL_OR_KEYWORD
    KeywordOnly = Parameter.KEYWORD_ONLY
    VarArgs = Parameter.VAR_POSITIONAL
    VarKwargs = Parameter.VAR_KEYWORD
    AllPositional = (Parameter.POSITIONAL_OR_KEYWORD, Parameter.POSITIONAL_ONLY, Parameter.VAR_POSITIONAL)
    StrictPositional = (Parameter.POSITIONAL_ONLY, Parameter.VAR_POSITIONAL)
    AllKeyWord = (Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY, Parameter.VAR_KEYWORD)
    StrictKeyWord = (Parameter.KEYWORD_ONLY, Parameter.VAR_KEYWORD)


_ParameterKind = type(Parameter.POSITIONAL_OR_KEYWORD)

ArgNameSpec = Union[str, Pattern[str], ArgKind, _ParameterKind]

AnyArgNameSpec = Union[bool, ArgNameSpec, Collection[ArgNameSpec]]


class CLISignatureSpec(NamedTuple):
    ignore_on_cmd_line: Optional[AnyArgNameSpec] = None
    ignore_in_config: Optional[AnyArgNameSpec] = None
    parse_config_as_cli: Optional[AnyArgNameSpec] = None
    parse_env: Optional[Dict[str, str]] = None
    parse_order: Optional[List[Union[str, type(Ellipsis)]]] = None

    @classmethod
    def from_callable(cls, func: Callable) -> 'CLISignatureSpec':
        return CLISignatureSpec(
            ignore_on_cmd_line=cli_attrs.ignore_on_cmd_line(func),
            ignore_in_config=cli_attrs.ignore_in_config(func),
            parse_config_as_cli=cli_attrs.parse_config_as_cli(func),
            parse_env=cli_attrs.parse_env(func),
        )

    @property
    def nonnull_attrs(self):
        attrs = ((k, getattr(self, k)) for k in self._fields)
        return dict((k, v) for k, v in attrs if v is not None)

    def overriding(self, *others: 'CLISignatureSpec') -> 'CLISignatureSpec':
        namespaces = (n.nonnull_attrs for n in chain((self,), others))
        return CLISignatureSpec(**ChainMap(*namespaces))

    def configure(self, sig: Signature, warn_missing: Optional[Callable[[str], None]] = None) -> 'FinalCLISignatureSpec':
        params = sig.parameters
        all_names = set(params)

        def param_names(attr, invert=False):
            names = filter_params(getattr(self, attr), params, attr)
            return all_names.difference(names) if invert else set(names)

        parse_env = {name: envname for name, envname in self.parse_env.items() if name in all_names}
        parse_order = compute_parse_order(self.parse_order, all_names)

        if warn_missing is not None:
            if len(parse_env) < len(self.parse_env):
                warn_missing("None of names {} in parse_env occurred in signature {}".format(
                    tuple(name for name in parse_env if name not in all_names),
                    sig,
                ))
            missing = tuple(n for n in parse_order if n is not Ellipsis and n not in all_names)
            if missing:
                warn_missing("None of names {} in parse_order occurred in signature {}".format(
                    missing, sig,
                ))

        return FinalCLISignatureSpec(
            parse_cmd_line=param_names('ignore_on_cmd_line', invert=True),
            parse_config=param_names('ignore_in_config', invert=True),
            parse_config_as_cli=param_names('parse_config_as_cli', invert=False),
            parse_env=parse_env,
            parse_order=parse_order,
        )


class FinalCLISignatureSpec(NamedTuple):
    parse_cmd_line: Set[str]
    parse_config: Set[str]
    parse_env: Dict[str, str]
    parse_config_as_cli: Set[str]
    parse_order: List[str]


class UnknownArgSpecifier(TypeError):
    def __init__(self, spec, argname: Optional[str]):
        super().__init__(spec, argname)

    def __str__(self):
        spec = self.args[0]
        msg = "Can't filter function params with specifier {} of type {}".format(repr(spec), type(spec))
        if self.args[1]:
            msg += "; occurred for attribute '{}'".format(self.args[1])
        return "{}({})".format(type(self).__name__, repr(msg))


@singledispatch
def filter_params(spec: AnyArgNameSpec,
                  params: Mapping[str, Parameter],
                  argname: Optional[str] = None,
                  warn_missing: Optional[Callable[[str], None]] = None) -> Iterable[str]:
    if spec is None:
        return ()
    if isinstance(spec, Collection):
        return chain.from_iterable(filter_params(s, params, warn_missing=warn_missing) for s in spec)
    else:
        raise UnknownArgSpecifier(spec, argname)


@filter_params.register(bool)
def _filter_params_bool(spec: bool, params, argname=None, warn_missing=None):
    return iter(params) if spec else ()


@filter_params.register(str)
def _filter_params_str(spec: str, params, argname=None, warn_missing=None):
    if spec.isidentifier():
        if spec in params:
            return (spec,)
        else:
            if warn_missing is not None:
                warn_missing("Name {} is not in signature {}{}".format(
                    repr(spec),
                    Signature(params.values()),
                    "; occurred for '{}'".format(argname) if argname else ''
                ))
            return ()
    else:
        return _filter_params_re(re.compile(spec), params, argname)


@filter_params.register(type(re.compile("")))
def _filter_params_re(spec: Pattern, params, argname=None, warn_missing=None):
    names = filter(spec.fullmatch, params)
    if warn_missing is not None:
        names = list(names)
        if not names:
            warn_missing("No names in signature {} match pattern {}{}".format(
                Signature(params.values()),
                repr(spec.pattern),
                "; occurred for '{}'".format(argname) if argname else ''
            ))
    return names


@filter_params.register(_ParameterKind)
def _filter_params_kind(spec: _ParameterKind, params, argname=None, warn_missing=None):
    return (name for name, param in params.items() if param.kind == spec)


@filter_params.register(ArgKind)
def _filter_params_argkind(spec: ArgKind, params, argname=None, warn_missing=None):
    kinds = spec.value
    return (name for name, param in params.items() if param.kind in kinds)


def compute_parse_order(parse_order: List[Union[str, type(Ellipsis)]], param_names: Set[str]):
    if parse_order is None:
        return list(param_names)
    parse_order = _validate_parse_order(*parse_order)

    if any((n not in param_names) or (n is not Ellipsis) for n in parse_order):
        raise NameError("parse_order entries must all be in {}; got {}".format(param_names, parse_order))

    try:
        ellipsis_ix = parse_order.index(Ellipsis)
    except ValueError:
        head, tail = parse_order, ()
        middle = ()
    else:
        head, tail = parse_order[:ellipsis_ix], parse_order[ellipsis_ix + 1:]
        middle = param_names.difference(head).difference(tail)

    return [*(h for h in head if h in param_names), *middle, *(t for t in tail if t in param_names)]
