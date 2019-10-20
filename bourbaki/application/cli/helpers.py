# coding:utf-8
from argparse import ONE_OR_MORE, OPTIONAL, ZERO_OR_MORE
from collections import ChainMap
from inspect import Parameter, Signature
from itertools import chain
from pathlib import Path
from string import punctuation
from typing import Dict, List, Tuple, Optional, Union

from bourbaki.introspection.docstrings import CallableDocs
from ..logging import ProgressLogger, TimedTaskContext
from ..logging.defaults import PROGRESS, ERROR
from ..typed_io.main import ArgSource
from ..typed_io.cli_nargs_ import cli_nargs

VARIADIC_NARGS = (ONE_OR_MORE, OPTIONAL, ZERO_OR_MORE)


class LookupOrderConfigError(ValueError):
    def __init__(self, name_or_names):
        self.args = ("all names in lookup_order must be in {}; got {}".format(tuple(s.name for s in ArgSource), name_or_names),)


class LookupOrderRepeated(LookupOrderConfigError):
    def __init__(self, name_or_names):
        self.args = ("names in lookup_order must be unique; got {}".format(name_or_names),)


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


class ReturnHandlerSignatureError(TypeError):
    pass


def strip_command_prefix(prefix: Union[str, Tuple[str, ...]], funcname: str) -> str:
    if isinstance(prefix, str):
        prefix = (prefix,)

    suffix = tuple(p.replace('-', '_') for p in prefix)
    while not funcname.startswith('_'.join(suffix)):
        suffix = suffix[1:]

    strip_prefix = '_'.join(suffix)
    funcname = funcname[len(strip_prefix):].lstrip("_")

    return funcname


def sibling_files(path):
    # for specifying the helper_files arg to the CLI: helper_files=sibling_files(__file__)
    return list(Path(path).parent.glob("*.py"))


def get_task(logger, name, log_level=PROGRESS, error_level=ERROR, time_units='s'):
    if isinstance(logger, ProgressLogger):
        return logger.task(name, time_units=time_units, level=log_level, error_level=error_level)
    return TimedTaskContext(name, logger_or_print_func=logger, time_units=time_units,
                            level=log_level, error_level=error_level)


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


def _help_kwargs_from_docs(docs: CallableDocs, long_desc_as_epilog: bool=False, help_: bool=True):
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


def _validate_lookup_order(*lookup_order: ArgSource):
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

    return order


def _validate_parse_order(*parse_order):
    if not parse_order:
        raise ValueError("can't make sense of an empty parse_order: {}".format(parse_order))
    if parse_order.count(Ellipsis) > 1:
        raise ValueError("at most one `...` may be present in parse_order; got {}".format(parse_order))
    if not all((isinstance(n, str) or n is Ellipsis) for n in parse_order):
        raise TypeError("all elements of parse_order must be str or `...`; got {}".format(parse_order))
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
            raise NameError("{} must all be in {}; values {} are not"
                            .format(metavar or 'names', default_set, extra))
    return names


def _maybe_bool(names, fallback=_to_name_set):
    if len(names) == 1 and isinstance(names[0], bool):
        return names[0]
    return fallback(names)


def _to_output_sig(output_signature: Signature, function_signature: Optional[Signature] = None,
                   require_keyword_args: bool=False):
    if function_signature is None:
        return output_signature

    common_names = set(output_signature.parameters).intersection(function_signature.parameters)
    if common_names:
        raise ReturnHandlerSignatureError("output handler signature and function signature share arg names: {}"
                                          .format(tuple(common_names)))

    def update_annotation(ann, kind):
        if kind is Parameter.VAR_POSITIONAL:
            return Tuple[ann, ...]
        elif kind is Parameter.VAR_KEYWORD:
            return Dict[str, ann]
        return ann

    if require_keyword_args:
        new_params = [p.replace(kind=Parameter.KEYWORD_ONLY, annotation=update_annotation(p.annotation, p.kind))
                      for p in output_signature.parameters.values()]
        output_signature = Signature(new_params)

    kinds = (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD, Parameter.VAR_POSITIONAL,
             Parameter.KEYWORD_ONLY, Parameter.VAR_KEYWORD)
    params_ = [[], [], [], [], []]
    pos_only, pos, args, kw, kwargs = params_

    params = dict(zip(kinds, params_))
    for sig in (function_signature, output_signature):
        for param in sig.parameters.values():
            params[param.kind].append(param)

    if len(args) > 1:
        extra_args = args.pop()
        extra_args = extra_args.replace(kind=Parameter.KEYWORD_ONLY, annotation=Tuple[extra_args.annotation, ...])
        kw.append(extra_args)

    if len(kwargs) > 1:
        extra_kwargs = kwargs.pop()
        extra_kwargs = extra_kwargs.replace(kind=Parameter.KEYWORD_ONLY, annotation=Dict[str, extra_kwargs.annotation])
        kw.append(extra_kwargs)

    for i in (0, 1):
        params_[i] = _sort_variadic_positionals_last(params_[i])
    all_params = list(chain.from_iterable(params_))

    return Signature(all_params, return_annotation=function_signature.return_annotation, __validate_parameters__=False)


def _sort_variadic_positionals_last(params: List[Parameter]) -> List[Parameter]:
    head, tail = [], []

    for param in params:
        if param.annotation is Parameter.empty and param.default is Parameter.empty:
            head.append(param)
        elif cli_nargs(param.annotation) in VARIADIC_NARGS:
            tail.append(param)
        else:
            head.append(param)

    return head + tail
