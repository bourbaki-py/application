# coding:utf-8
from typing import Mapping, Iterable, Tuple, Any, Union
from collections.abc import Mapping as _Mapping
import argparse
from operator import itemgetter
from textwrap import indent
from multipledispatch import dispatch
from bourbaki.introspection.prettyprint import fmt_pyobj


class Namespace(Mapping[str, Any]):
    """
    Syntactic sugar for configuration objects; use [] or . to get field values.
    This also adds the option to include multiple config objects/dicts as positional args, whose keys override one
    another from left to right, and are finally overridden by any keyword args that are passed.
    """

    def __init__(
        self,
        *args: Union[Mapping, argparse.Namespace, Iterable[Tuple[str, Any]]],
        **kwargs: Any
    ):
        if not all(
            isinstance(d, (Mapping, argparse.Namespace, Iterable)) for d in args
        ):
            raise TypeError("all positional args must be dict or argparse.Namespace")

        for d in args:
            if isinstance(d, (Mapping, Iterable)):
                self.__dict__.update(d)
            elif isinstance(d, (Namespace, argparse.Namespace)):
                self.__dict__.update(d.__dict__)
            else:
                raise TypeError(
                    "varargs must each be instances of Mapping, argparse.Namespace, "
                    "or Iterable[Tuple[str, Any]]"
                )

        self.__dict__.update(kwargs)

    def __getitem__(self, item):
        return self.__dict__[item]

    def __setitem__(self, key, value):
        self.__dict__[key] = value

    def __delitem__(self, key):
        del self.__dict__[key]

    def get(self, item, default=None):
        return self.__dict__.get(item, default)

    def keys(self):
        return self.__dict__.keys()

    def values(self):
        return self.__dict__.values()

    def items(self):
        return self.__dict__.items()

    def __len__(self):
        return len(self.__dict__)

    def __contains__(self, item):
        return item in self.__dict__

    def __iter__(self):
        return iter(self.__dict__.keys())

    def __dir__(self):
        return list(self.__dict__.keys())

    def __repr__(self):
        return namespace_pretty_repr(self)


def namespace_pretty_repr(ns, indent_=4):
    name = ns.__class__.__name__
    break_ = "\n" if len(ns.__dict__) > 0 else ""
    return "{}({}{}{})".format(
        name,
        break_,
        indent(
            ",\n".join(
                "{}={}".format(
                    k,
                    namespace_pretty_repr(v, len(k) + 5)
                    if isinstance(v, Namespace)
                    else fmt_pyobj(v),
                )
                for k, v in sorted(type(ns).items(ns), key=itemgetter(0))
            ),
            " " * indent_,
        ),
        break_,
    )


@dispatch(_Mapping)
def namespace_recursive(obj: Mapping):
    return Namespace({k: namespace_recursive(v) for k, v in obj.items()})


@dispatch(argparse.Namespace)
def namespace_recursive(obj: argparse.Namespace):
    return namespace_recursive(obj.__dict__)


@dispatch((list, tuple))
def namespace_recursive(obj: list):
    return type(obj)(map(namespace_recursive, obj))


@dispatch(object)
def namespace_recursive(obj: object):
    return obj


@dispatch(_Mapping)
def un_namespace_recursive(obj: Mapping):
    return {k: un_namespace_recursive(v) for k, v in obj.items()}


@dispatch(argparse.Namespace)
def un_namespace_recursive(obj: argparse.Namespace):
    return un_namespace_recursive(obj.__dict__)


@dispatch((list, tuple))
def un_namespace_recursive(obj: list):
    return type(obj)(map(un_namespace_recursive, obj))


@dispatch(object)
def un_namespace_recursive(obj: object):
    return obj
