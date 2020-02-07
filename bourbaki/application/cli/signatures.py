from typing import (
    Callable,
    Collection,
    Dict,
    Set,
    List,
    Mapping,
    NamedTuple,
    Pattern,
    Iterable,
    Optional,
    Union,
    Any,
)
from collections import ChainMap
from functools import singledispatch
from enum import Enum
from itertools import chain
from inspect import Parameter, Signature
import re

from bourbaki.introspection.callables import (
    leading_positionals,
    most_specific_constructor,
)
from .decorators import cli_attrs
from .helpers import _validate_parse_order, _type


class ArgKind(Enum):
    PositionalOnly = Parameter.POSITIONAL_ONLY
    PositionalOrKeyword = Parameter.POSITIONAL_OR_KEYWORD
    KeywordOnly = Parameter.KEYWORD_ONLY
    VarArgs = Parameter.VAR_POSITIONAL
    VarKwargs = Parameter.VAR_KEYWORD
    AllPositional = (
        Parameter.POSITIONAL_OR_KEYWORD,
        Parameter.POSITIONAL_ONLY,
        Parameter.VAR_POSITIONAL,
    )
    StrictPositional = (Parameter.POSITIONAL_ONLY, Parameter.VAR_POSITIONAL)
    AllKeyWord = (
        Parameter.POSITIONAL_OR_KEYWORD,
        Parameter.KEYWORD_ONLY,
        Parameter.VAR_KEYWORD,
    )
    StrictKeyWord = (Parameter.KEYWORD_ONLY, Parameter.VAR_KEYWORD)


_ParameterKind = type(Parameter.POSITIONAL_OR_KEYWORD)

ArgNameSpec = Union[str, Pattern[str], ArgKind, _ParameterKind]

AnyArgNameSpec = Union[bool, ArgNameSpec, Collection[ArgNameSpec]]


class CLISignatureSpec(NamedTuple):
    ignore_on_cmd_line: Optional[AnyArgNameSpec] = None
    ignore_in_config: Optional[AnyArgNameSpec] = None
    parse_config_as_cli: Optional[AnyArgNameSpec] = None
    typecheck: Optional[AnyArgNameSpec] = None
    parse_env: Optional[Dict[str, str]] = None
    metavars: Optional[Dict[str, str]] = None
    named_groups: Optional[Dict[str, Collection[str]]] = None
    parse_order: Optional[List[Union[str, type(Ellipsis)]]] = None
    require_options: Optional[bool] = None

    @classmethod
    def from_callable(cls, func: Callable) -> "CLISignatureSpec":
        if isinstance(func, _type):
            constructor = most_specific_constructor(func)
        else:
            constructor = None

        spec = CLISignatureSpec(
            ignore_on_cmd_line=cli_attrs.ignore_on_cmd_line(func),
            ignore_in_config=cli_attrs.ignore_in_config(func),
            parse_config_as_cli=cli_attrs.parse_config_as_cli(func),
            typecheck=cli_attrs.typecheck(func),
            parse_env=cli_attrs.parse_env(func),
            metavars=cli_attrs.metavars(func),
            named_groups=cli_attrs.named_groups(func),
            parse_order=cli_attrs.parse_order(func),
            require_options=cli_attrs.require_options(func),
        )

        return (
            spec
            if constructor is None
            else spec.overriding(CLISignatureSpec.from_callable(constructor))
        )

    @property
    def nonnull_attrs(self):
        attrs = ((k, getattr(self, k)) for k in self._fields)
        return dict((k, v) for k, v in attrs if v is not None)

    def overriding(self, *others: "CLISignatureSpec") -> "CLISignatureSpec":
        namespaces = [n.nonnull_attrs for n in chain((self,), others)]
        metavars = ChainMap(*filter(None, (n.get("metavars") for n in namespaces)))
        attrs = ChainMap({"metavars": metavars}, *namespaces)
        if attrs.get('require_options') is None:
            attrs['require_options'] = False
        return CLISignatureSpec(**attrs)

    def configure(
        self, sig: Signature, warn_missing: Optional[Callable[[str], None]] = None
    ) -> "FinalCLISignatureSpec":
        params = sig.parameters
        all_names = set(params)

        if self.parse_env is None:
            parse_env = {}
        else:
            parse_env = {
                name: envname
                for name, envname in self.parse_env.items()
                if name in all_names
            }
            if len(parse_env) < len(self.parse_env):
                raise NameError(
                    "None of the names {} in parse_env occurred in signature {}".format(
                        tuple(name for name in parse_env if name not in all_names), sig
                    )
                )

        if self.metavars is None:
            metavars = {}
        else:
            metavars = {
                name: metavar
                for name, metavar in self.metavars.items()
                if name in all_names
            }
            if warn_missing is not None and len(metavars) < len(self.metavars):
                warn_missing(
                    "None of names {} in metavars occurred in signature {}".format(
                        tuple(name for name in metavars if name not in all_names), sig
                    )
                )

        if self.named_groups is None:
            named_groups = {}
        else:
            named_groups = {}
            memo = set()
            prior = []
            for name, group in self.named_groups.items():
                prior.append(name)
                group = set(group)

                if warn_missing is not None:
                    repeated = group.intersection(memo)
                    if repeated:
                        warn_missing(
                            "Names {} in named group '{}' occurred in at least one of prior named groups {}".format(
                                tuple(repeated), name, prior
                            )
                        )
                    missing = group.difference(all_names)
                    if missing:
                        warn_missing(
                            "Names {} in named group '{}' are not present in signature {}".format(
                                tuple(missing), name, sig
                            )
                        )

                memo.update(group)
                named_groups[name] = group.difference(memo).intersection(all_names)

        if self.parse_order is None:
            parse_order = list(params)
        else:
            parse_order = compute_parse_order(self.parse_order, all_names)

        def param_names(attr, invert=False):
            names = filter_params(
                getattr(self, attr), params, argname=attr, warn_missing=warn_missing
            )
            return all_names.difference(names) if invert else set(names)

        return FinalCLISignatureSpec(
            parse_cmd_line=param_names("ignore_on_cmd_line", invert=True),
            parse_config=param_names("ignore_in_config", invert=True),
            parse_config_as_cli=param_names("parse_config_as_cli", invert=False),
            typecheck=param_names("typecheck", invert=False),
            parse_env=parse_env,
            parse_order=parse_order,
            metavars=metavars,
            named_groups=named_groups,
            all_names=all_names,
            positional_names=list(leading_positionals(sig.parameters, names_only=True)),
            require_options=self.require_options,
        )


class FinalCLISignatureSpec(NamedTuple):
    parse_cmd_line: Set[str]
    parse_config: Set[str]
    parse_config_as_cli: Set[str]
    parse_env: Mapping[str, str]
    parse_order: List[str]
    typecheck: Set[str]
    metavars: Mapping[str, str]
    named_groups: Mapping[str, Set[str]]
    all_names: Set[str]
    positional_names: List[str]
    require_options: bool

    @property
    def parsed(self) -> Set[str]:
        return self.parse_cmd_line.union(self.parse_config).union(self.parse_env)

    @property
    def have_fallback(self) -> Set[str]:
        return self.parse_config.union(self.parse_env)


class UnknownArgSpecifier(TypeError):
    def __init__(self, spec, argname: Optional[str]):
        super().__init__(spec, argname)

    def __str__(self):
        spec = self.args[0]
        msg = "Can't filter function params with specifier {} of type {}".format(
            repr(spec), type(spec)
        )
        if self.args[1]:
            msg += "; occurred for attribute '{}'".format(self.args[1])
        return "{}({})".format(type(self).__name__, repr(msg))


@singledispatch
def filter_params(
    spec: AnyArgNameSpec,
    params: Mapping[str, Parameter],
    argname: Optional[str] = None,
    warn_missing: Optional[Callable[[str], None]] = None,
) -> Iterable[str]:
    if spec is None:
        return ()
    if isinstance(spec, Collection):
        return chain.from_iterable(
            filter_params(s, params, warn_missing=warn_missing) for s in spec
        )
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
                warn_missing(
                    "Name {} is not in signature {}{}".format(
                        repr(spec),
                        Signature(params.values()),
                        "; occurred for '{}'".format(argname) if argname else "",
                    )
                )
            return ()
    else:
        return _filter_params_re(re.compile(spec), params, argname)


@filter_params.register(type(re.compile("")))
def _filter_params_re(spec: Pattern, params, argname=None, warn_missing=None):
    names = filter(spec.fullmatch, params)
    if warn_missing is not None:
        names = list(names)
        if not names:
            warn_missing(
                "No names in signature {} match pattern {}{}".format(
                    Signature(params.values()),
                    repr(spec.pattern),
                    "; occurred for '{}'".format(argname) if argname else "",
                )
            )
    return names


@filter_params.register(_ParameterKind)
def _filter_params_kind(spec: _ParameterKind, params, argname=None, warn_missing=None):
    return (name for name, param in params.items() if param.kind == spec)


@filter_params.register(ArgKind)
def _filter_params_argkind(spec: ArgKind, params, argname=None, warn_missing=None):
    kinds = spec.value
    return (name for name, param in params.items() if param.kind in kinds)


def compute_parse_order(
    parse_order: List[Union[str, type(Ellipsis)]], param_names: Set[str]
):
    if parse_order is None:
        return list(param_names)
    parse_order = _validate_parse_order(*parse_order)

    if any((n not in param_names) or (n is not Ellipsis) for n in parse_order):
        raise NameError(
            "parse_order entries must all be in {}; got {}".format(
                param_names, parse_order
            )
        )

    try:
        ellipsis_ix = parse_order.index(Ellipsis)
    except ValueError:
        head, tail = parse_order, ()
        middle = ()
    else:
        head, tail = parse_order[:ellipsis_ix], parse_order[ellipsis_ix + 1 :]
        middle = param_names.difference(head).difference(tail)

    return [
        *(h for h in head if h in param_names),
        *middle,
        *(t for t in tail if t in param_names),
    ]
