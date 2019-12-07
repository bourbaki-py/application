# coding:utf-8
from argparse import ONE_OR_MORE, OPTIONAL, ZERO_OR_MORE
from collections import ChainMap, Counter
from functools import lru_cache
from inspect import Parameter, Signature
from itertools import chain
from pathlib import Path
import sys
from string import punctuation
from typing import Dict, List, Set, Tuple, Union, Optional, Mapping, Generic

from bourbaki.introspection.docstrings import CallableDocs
from ..logging import ProgressLogger, TimedTaskContext
from ..logging.defaults import PROGRESS, ERROR
from ..typed_io.main import ArgSource
from ..typed_io.cli_nargs_ import cli_nargs

VARIADIC_NARGS = (ONE_OR_MORE, OPTIONAL, ZERO_OR_MORE)

_type = tuple({type, *(type(t) for t in (Mapping, Tuple, Generic))})


class LookupOrderConfigError(ValueError):
    def __init__(self, name_or_names):
        self.args = (
            "all names in lookup_order must be in {}; got {}".format(
                tuple(s.name for s in ArgSource), name_or_names
            ),
        )


class LookupOrderRepeated(LookupOrderConfigError):
    def __init__(self, name_or_names):
        self.args = (
            "names in lookup_order must be unique; got {}".format(name_or_names),
        )


_sentinel = object()


class NamedChainMap(ChainMap):
    def __init__(self, *named_maps):
        self.names, maps = zip(*named_maps)
        super().__init__(*maps)

    def get_with_name(self, key, default=_sentinel):
        for name, map_ in zip(self.names, self.maps):
            try:
                return name, map_[key]
            except KeyError:
                continue
        if default is _sentinel:
            raise KeyError(repr(key))

        return None, default


class OutputHandlerSignatureError(TypeError):
    pass


def strip_command_prefix(prefix: Union[str, Tuple[str, ...]], funcname: str) -> str:
    if isinstance(prefix, str):
        prefix = (prefix,)

    suffix = tuple(p.replace("-", "_") for p in prefix)
    while not funcname.startswith("_".join(suffix)):
        suffix = suffix[1:]

    strip_prefix = "_".join(suffix)
    funcname = funcname[len(strip_prefix) :].lstrip("_")

    return funcname


def sibling_files(path):
    # for specifying the helper_files arg to the CLI: helper_files=sibling_files(__file__)
    return list(Path(path).parent.glob("*.py"))


def get_task(logger, name, log_level=PROGRESS, error_level=ERROR, time_units="s"):
    if isinstance(logger, ProgressLogger):
        return logger.task(
            name, time_units=time_units, level=log_level, error_level=error_level
        )
    return TimedTaskContext(
        name,
        logger_or_print_func=logger,
        time_units=time_units,
        level=log_level,
        error_level=error_level,
    )


def update_in(conf, subsection, subconf):
    if not isinstance(subsection, (list, tuple)):
        subsection = (subsection,)

    subconf_ = conf
    for key in subsection:
        subconf__ = subconf_.get(key)
        if subconf__ is None:
            subconf__ = {}
            subconf_[key] = subconf__
        subconf_ = subconf__
    subconf_.update(subconf)


def try_or_exit(func, exit, error_status, *args, **kwargs):
    try:
        result = func(*args, **kwargs)
    except Exception as e:
        print("Execution failed: {}".format(e), file=sys.stderr)
        exit(error_status)
    else:
        return result


def _help_kwargs_from_docs(
    docs: CallableDocs, long_desc_as_epilog: bool = False, help_: bool = True
):
    if help_:
        kw = {"help": docs.short_desc}
    else:
        kw = {}

    if long_desc_as_epilog:
        kw["description"] = docs.short_desc
        kw["epilog"] = docs.long_desc
    else:
        short = docs.short_desc
        if short:
            if short[-1] in punctuation:
                join = " "
            else:
                join = "; "
            description = join.join(d for d in (short, docs.long_desc) if d)
        else:
            description = docs.long_desc
        kw["description"] = description

    return kw


@lru_cache(None)
def _validate_lookup_order(*lookup_order: ArgSource, include_defaults=True):
    order = []
    missing = []
    for s in lookup_order:
        if isinstance(s, str):
            source = getattr(ArgSource, s, None)
        else:
            source = s

        if not isinstance(source, ArgSource):
            missing.append(s)
        else:
            order.append(source)

    if missing:
        raise LookupOrderConfigError(lookup_order)
    if len(set(lookup_order)) != len(lookup_order):
        raise LookupOrderRepeated(lookup_order)

    if include_defaults and ArgSource.DEFAULTS not in order:
        order.append(ArgSource.DEFAULTS)

    return order


def _validate_parse_order(*parse_order):
    if not parse_order:
        raise ValueError(
            "can't make sense of an empty parse_order: {}".format(parse_order)
        )
    if parse_order.count(Ellipsis) > 1:
        raise ValueError(
            "at most one `...` may be present in parse_order; got {}".format(
                parse_order
            )
        )
    if not all((isinstance(n, str) or n is Ellipsis) for n in parse_order):
        raise TypeError(
            "all elements of parse_order must be str or `...`; got {}".format(
                parse_order
            )
        )
    return parse_order


def _to_name_set(maybe_names, default_set=None, metavar=None):
    if isinstance(maybe_names, str):
        names = {maybe_names}
    elif maybe_names is True:
        # no need to check
        return default_set
    elif not maybe_names:  # None, False
        names = set()
    else:  # collection
        names = set(maybe_names)

    if default_set is not None:
        extra = names.difference(default_set)
        if extra:
            raise NameError(
                "{} must all be in {}; values {} are not".format(
                    metavar or "names", default_set, extra
                )
            )
    return names


def _maybe_bool(names, fallback=_to_name_set):
    if len(names) == 1 and isinstance(names[0], bool):
        return names[0]
    return fallback(names)


def _combined_cli_sig(
    signature: Signature,
    *other_signatures: Signature,
    parse: Optional[Set[str]] = None,
    have_fallback: Optional[Set[str]] = None
):
    all_signatures = (signature, *other_signatures)

    all_names = chain.from_iterable(s.parameters for s in all_signatures)
    if parse is not None:
        all_names = filter(parse.__contains__, all_names)
    name_counts = Counter(all_names)
    common_names = tuple(n for n, c in name_counts.items() if c > 1)
    if common_names:
        raise OutputHandlerSignatureError(
            "signatures share overlapping arg names: {}".format(common_names)
        )

    params = {
        k: []
        for k in (
            Parameter.POSITIONAL_ONLY,
            Parameter.POSITIONAL_OR_KEYWORD,
            Parameter.VAR_POSITIONAL,
            Parameter.KEYWORD_ONLY,
            Parameter.VAR_KEYWORD,
        )
    }
    for sig in all_signatures:
        for param in sig.parameters.values():
            if parse is None or param.name in parse:
                params[param.kind].append(param)

    # algorithm:
    # sort variadics to the end of the positionals
    # if there are any positional variadics, move all but the first to kw_only, and move any *args to kw_only
    # if there are no positional variadics, move the first *args to the end of positionals, the rest to kw_only
    # if there are more than one **kwargs, move the tail to kw_only

    all_pos = (
        params[Parameter.POSITIONAL_ONLY] + params[Parameter.POSITIONAL_OR_KEYWORD]
    )
    non_variadic_pos, variadic_pos = _separate_variadic_params(all_pos)
    maybe_variadic_pos = []
    if variadic_pos:
        first_variadic = variadic_pos[0]
        last_pos_kind = (
            max(non_variadic_pos[-1].kind, first_variadic.kind)
            if non_variadic_pos
            else first_variadic.kind
        )
        maybe_variadic_pos.append(first_variadic.replace(kind=last_pos_kind))
        params[Parameter.KEYWORD_ONLY].extend(
            p.replace(kind=Parameter.KEYWORD_ONLY) for p in variadic_pos[1:]
        )
    elif params[Parameter.VAR_POSITIONAL]:
        varargs = params[Parameter.VAR_POSITIONAL]
        first_varargs = varargs[0]
        maybe_variadic_pos.append(
            first_varargs.replace(
                kind=Parameter.POSITIONAL_OR_KEYWORD,
                annotation=Tuple[first_varargs.annotation, ...],
            )
        )
        params[Parameter.VAR_POSITIONAL] = varargs[1:]

    for kind in Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD:
        ps = params[kind]
        params[Parameter.KEYWORD_ONLY].extend(
            p.replace(
                kind=Parameter.KEYWORD_ONLY,
                annotation=Tuple[p.annotation, ...]
                if kind is Parameter.VAR_POSITIONAL
                else Dict[str, p.annotation],
            )
            for p in ps
        )

    nondefault_pos, default_pos = _separate_default_params(
        non_variadic_pos, have_fallback=have_fallback
    )
    all_params = (
        nondefault_pos
        + default_pos
        + maybe_variadic_pos
        + params[Parameter.KEYWORD_ONLY]
    )

    # Don't validate because we may have defaults preceding non-defaults at this point
    return Signature(
        all_params,
        return_annotation=signature.return_annotation,
        __validate_parameters__=False,
    )


def _separate_default_params(
    params: List[Parameter], have_fallback: Optional[Set[str]] = None
) -> Tuple[List[Parameter], List[Parameter]]:
    nondefaults, defaults = [], []
    for param in params:
        if param.default is Parameter.empty and (
            not have_fallback or param.name not in have_fallback
        ):
            nondefaults.append(param)
        else:
            defaults.append(param)
    return nondefaults, defaults


def _separate_variadic_params(
    params: List[Parameter]
) -> Tuple[List[Parameter], List[Parameter]]:
    args, variadics = [], []
    for param in params:
        if param.annotation is Parameter.empty:
            args.append(param)
        elif cli_nargs(param.annotation) in VARIADIC_NARGS:
            variadics.append(param)
        else:
            args.append(param)
    return args, variadics
