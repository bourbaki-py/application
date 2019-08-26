# coding:utf-8
from typing import Optional, Tuple, Dict, Union
import enum
from inspect import Parameter
from argparse import ArgumentParser, OPTIONAL, ONE_OR_MORE, ZERO_OR_MORE
from functools import lru_cache
from bourbaki.introspection.types import deconstruct_generic
from .cli_parse import cli_parser
from .cli_nargs_ import cli_nargs
from .cli_repr_ import cli_repr
from .cli_complete import cli_completer
from .config_encode import config_encoder, config_key_encoder
from .config_decode import config_decoder, config_key_decoder
from .config_repr_ import config_repr
from .env_parse import env_parser
from .utils import Empty, Doc, to_param_doc, to_cmd_line_name, cmd_line_arg_names, CLI_PREFIX_CHAR
from .utils import cached_property, PicklableWithType, missing, identity


class ArgSource(enum.Enum):
    CLI = "command line"
    CONFIG = "configuration file"
    ENV = "environment variables"


CLI, CONFIG, ENV = ArgSource.CLI, ArgSource.CONFIG, ArgSource.ENV


class TypedIO(PicklableWithType):
    """Bag of dispatched methods/values for CLI and config I/O. Methods/attributes are only computed if needed,
    so that if some are unavailable for a given type, but aren't needed, no exceptions are thrown"""

    @lru_cache(None)
    def __new__(cls, type_, *args):
        new = object.__new__(cls)
        cls.__init__(new, type_, *args)
        return new

    def __repr__(self):
        cls = type(self)
        return "{}.{}({})".format(cls.__module__, cls.__name__, repr(self.type_))

    def __str__(self):
        return self.__repr__()

    def __getnewargs__(self):
        return (deconstruct_generic(self.type_),)

    @classmethod
    def from_parameter(cls, param: Parameter, type_=None):
        if type_ is None:
            type_ = param.annotation

        if param.kind is Parameter.VAR_POSITIONAL:
            type_ = Tuple[type_, ...]
        elif param.kind == Parameter.VAR_KEYWORD:
            type_ = Dict[str, type_]

        return cls(type_)

    @classmethod
    def register(cls, type_, *,
                 cli_parser_=None, cli_nargs_=None, cli_repr_=None, cli_completer_=None,
                 config_decoder_=None, config_encoder_=None, config_repr_=None,
                 config_key_decoder_=None, config_key_encoder_=None,
                 as_const=True):
        """Convenience method to allow registration of all relevant typed I/O functions and constants with one call.
        For purposes of readability and debugging, this is the recommended way, since scattering registrations
        throughout a code base can make errors difficult to locate, and increase the likelihood of forgetting to
        register an important function (e.g. missing cli_nargs when cli_parser is given and it can't be inferred from
        the signature.

        Note: every argument with a "decoder" in the name should supply an inverse operation for the corresponding
        argument with "encoder" in the name, and vice-versa.

        :param as_const: when `False` (NOT the default), all args here are treated as functions with a
            `(base_type, *generic_args)` signature, and returning the relevant value.
            (see the other parameters documentation for what "relevant" means in each context)
            I.e., these are called on a _type_ after decomposing it into its original base and type constructor args.

            Therefore, this is generally only useful for
            a) parameterizable `typing.Generic` subclasses
            b) fairly high-level classes which have many subclasses that you want to treat differently
               (an `abc.ABC` for instance).

            For example, with `TypedIO.register(List[int], cli_nargs_=...)`, `cli_nargs_` would be a function taking
            literal `(List, int)` as args and returning a value that is legal for the `nargs` keyword arg
            of ArgumentParser.add_argument(...) (so an int, or `None`, or `argparse.ZERO_OR_MORE`, etc.).

            Admittedly, the above case is counterintuitive!
            `List[int] is fully determined already, and so we'd like to just say `cli_nargs=argparse.ZERO_OR_MORE` there.
            And _that_ is what `as_const=True` is for!  Just pass that flag in this case and you'll be fine.

            On the other hand, you might want to register `MyCustomGeneric[TypeVar("T")]` - that's the case where
            having as_const=False is what you want, because `MyCustomGeneric` can be parameterized by a type, and we may
            want the `cli_nargs`, or the `cli_parser`, or the `config_decoder`, etc. to depend on that type parameter.
            In this way you can register _all_ of the possible instantiations of a generic class in one call.

            If you want _some_ of the things to depend on the type parameters and some not to, you may pass
            `as_const=False` and selectively use the `application.typed_io.const(my_value_that_doesnt_take_type_args)`
            wrapper on those things that don't care about type parameters (usually `cli_nargs_`).

        :param cli_parser_: a function with signature `(command_line_value: Union[str, List[str]]) -> parsed_value`,
            where it is up to you to ensure that `parsed_value` is an instance of `type_`.
            Note: you may specify the `cli_nargs_` implicitly here as well by providing a type annotation:
            `str` for a single command line arg, `List[str]` for zero or more, or `Tuple[str, str, str, ...]` for a
            fixed integer number of command line args. The signature of this function will be checked to ensure that it
            only requires one positional arg and an error will be raised if not.

            OR if `type_` is a parameterizable generic type, specify `as_const=False` and then pass to `cli_parser_`
            a function with signature `(base_type, *generic_args) -> parser`, where `parser` has the specified
            signature. (see `as_const` above)

        :param cli_nargs_: a function with signature `(command_line_value: Union[str, List[str]]) -> nargs`,
            where `nargs` is a legal value for the `argparse.ArgumentParser.add_argument` method (None, or a positive
            int, or `argparse.ZERO_OR_MORE/ONE_OR_MORE/OPTIONAL`)
            Note: if you omit this, and `as_const=True` (the default), cli_nargs_ will be inferred from the signature
            of `cli_parser_` (see `cli_parser_` above), with the fallback value being `None`.

            OR if `type_` is a parameterizable generic type, specify `as_const=False` and then pass to `cli_nargs_`
            a function with signature `(base_type, *generic_args) -> nargs`. (see `as_const` above)

        :param cli_repr_: a `str` specifying what your `type_` "looks like" on the command line, for documentation of
            how to input it.  For example, the default `cli_repr_` for `ipaddress.IPv4Address` is
            "<0-255>.<0-255>.<0-255>.<0-255>".

            OR if `type_` is a parameterizable generic type, specify `as_const=False` and then pass to `cli_repr_`
            a function with signature `(base_type, *generic_args) -> cli_string_for_type`. (see `as_const` above)

        :param cli_completer_: an `application.completion.Complete` _instance_.  These have a `__str__` method that specifies
            a bash shell call to perform completion for the given value.  It is recommended not to implement these from
            scratch, as they require a fairly delicate knowledge of the bash completion machinery, and they reference
            shell functions, which you must ensure are available on the command line for the calling user for proper
            functioning.

            A nice way to register these is to use one of the many options already available in the
            `application.completion` module, including via attribute access on the `application.completion.BashCompletion`
            object, for instance `application.completion.BashCompletion.pids` for process ID completion.
            Note: most of these rely on installation of the "bash-completion" package, which is available on most linux
            distributions and MacOS via Homebrew (see the `application.completion` docstring for more info).

            OR if `type_` is a parameterizable generic type, specify `as_const=False` and then pass to `cli_completer_`
            a function with signature `(base_type, *generic_args) -> completer`, where `completer` is an appropriate
            `application.completion.Complete` instance. (see `as_const` above)

        :param config_decoder_: a function with signature `(config_value: JSONLike) -> parsed_value`,
            where it is up to you to ensure that `parsed_value` is an instance of `type_`.
            Here, `JSONLike` means any value that can be read from a config file via `application.config.load_config`,
            which for most config formats (yaml, toml, json, ini, etc), will mean `str`, `int`, `float`, `bool`, `None`,
            `List[JSONLike]` or `Dict[str, JSONLike]`.

            OR if `type_` is a parameterizable generic type, specify `as_const=False` and then pass to `config_decoder_`
            a function with signature `(base_type, *generic_args) -> decoder`, where `decoder` has the specified
            signature. (see `as_const` above)

        :param config_encoder_: a function with signature `(runtime_value) -> config_value`,
            where it is up to you to determine that `config_value` is encodable in your preferred config format.
            This generally means that `config_value` should be JSON-like (see `config_decoder_` above).

            OR if `type_` is a parameterizable generic type, specify `as_const=False` and then pass to `config_encoder_`
            a function with signature `(base_type, *generic_args) -> encoder`, where `encoder` has the specified
            signature. (see `as_const` above)

        :param config_key_decoder_: like `config_decoder_` but only takes a key from a mapping that was parsed from a
            config file, which for most config formats will be a string.  Allows you to specify more complex key types
            for your Mapping-typed inputs, with the caveat that you must specify a key parser separately here.

        :param config_key_encoder_: the reverse of `config_key_decoder_`: a function taking a runtime value and
            returning a key for a config value (which for most config formats will be a string.)

        :param config_repr_: a JSON-like value specifying what your `type_` "looks like" in configuration, for
            documentation of how to enter it in a config file.  For example, the default `config_repr_` for
            `List[int]` is `["<int>", "..."]`.
            This is for filling empty config files to guide users on how to enter typed values for CLI's.

            OR if `type_` is a parameterizable generic type, specify `as_const=False` and then pass to `config_repr_`
            a function with signature `(base_type, *generic_args) -> config_value_for_type`. (see `as_const` above)
        """
        # cli_parser first, since cli_nargs/repr/completer may be derivable
        for dispatcher, func in [(cli_parser, cli_parser_),
                                 (cli_nargs, cli_nargs_),
                                 (cli_repr, cli_repr_),
                                 (cli_completer, cli_completer_),
                                 (config_decoder, config_decoder_),
                                 (config_encoder, config_encoder_),
                                 (config_repr, config_repr_),
                                 (config_key_decoder, config_key_decoder_),
                                 (config_key_encoder, config_key_encoder_),
                                 ]:
            if func is not None:
                dispatcher.register(type_, as_const=as_const)(func)

    @cached_property
    def cli_parser(self):
        return cli_parser(self.type_)

    @cached_property
    def cli_nargs(self):
        return cli_nargs(self.type_)

    @property
    def is_variadic(self):
        return cli_nargs(self.type_) in (ZERO_OR_MORE, ONE_OR_MORE)

    @property
    def is_optional(self):
        return cli_nargs(self.type_) == OPTIONAL

    @cached_property
    def cli_repr(self):
        return cli_repr(self.type_)

    @cached_property
    def cli_completer(self):
        comp = cli_completer(self.type_)
        return comp

    @cached_property
    def env_parser(self):
        return env_parser(self.type_)

    @cached_property
    def config_encoder(self):
        return config_encoder(self.type_)

    @cached_property
    def config_decoder(self):
        return config_decoder(self.type_)

    @cached_property
    def config_repr(self):
        return config_repr(self.type_)

    def parser_for_source(self, source: ArgSource):
        if source == CLI:
            return self.cli_parser
        elif source == CONFIG:
            return self.config_decoder
        elif source == ENV:
            return self.env_parser
        return identity

    def argparse_spec(self, param: Parameter,
                      allow_positionals=False,
                      implicit_flags=False,
                      has_fallback=False,
                      metavar=None,
                      include_default=False,
                      docs: Optional[Doc]=None):
        name, default, kind = param.name, param.default, param.kind
        if default is Empty:
            default = missing
            has_default = False
        else:
            has_default = True

        if kind == Parameter.VAR_KEYWORD:
            variadic = True
            default = {}
            positional = False
        elif kind == Parameter.VAR_POSITIONAL:
            variadic = True
            positional = allow_positionals
        elif kind == Parameter.KEYWORD_ONLY:
            variadic = False
            positional = False
        else:
            # Parameter.POSITIONAL_OR_KEYWORD and Parameter.POSITIONAL_ONLY
            variadic = self.is_variadic
            positional = allow_positionals and not variadic

        required = not has_default and not has_fallback and not variadic
        doc = to_param_doc(docs, name)

        is_flag = self.type_ is bool and implicit_flags and not positional and not variadic
        is_negative_flag = is_flag and default is True

        names = cmd_line_arg_names(name, positional=positional, prefix_char=CLI_PREFIX_CHAR,
                                   negative_flag=is_negative_flag)

        if is_flag:
            kw = dict(action="store_false" if is_negative_flag else "store_true")
            if include_default:
                kw["default"] = default
            else:
                kw["default"] = missing
            # negative flags get name-mangled so we do this to be sure
            kw["dest"] = name
            defaultstr = None
            type_str = None
        else:
            nargs = self.cli_nargs

            if isinstance(metavar, dict):
                metavar = metavar.get(name)

            if metavar is None:
                type_str = None
                metavar = self.cli_repr
                if positional and not isinstance(metavar, str):
                    # hack to deal with the fact that argparse handles fixed-length positionals differently than
                    # fixed-length options when formatting help strings
                    type_str = ' '.join(metavar)
                    metavar = name.upper()
            else:
                type_str = self.cli_repr

            # don't pass the parser here; we handle parsing as a postprocessing step
            kw = dict(metavar=metavar)
            if has_default and include_default:
                kw['default'] = default
            elif not required:
                kw['default'] = missing

            if not positional:  # no required/dest kwargs allowed for positionals
                kw['required'] = required
                kw['dest'] = name

            if nargs is not None:
                kw['nargs'] = nargs
            elif positional and not required:
                kw['nargs'] = OPTIONAL

            if has_default and default is not None and not variadic:
                defaultstr = "default {}".format(repr(default))
            else:
                defaultstr = None

        help_ = doc
        helpstr = ": ".join(s for s in (type_str, help_, defaultstr) if s)
        if helpstr:
            kw['help'] = helpstr

        return names, kw, positional

    def add_argparse_arg(self, parser: ArgumentParser,
                         param: Parameter,
                         allow_positionals=False,
                         implicit_flags=False,
                         has_fallback=False,
                         metavar: Optional[Union[str, Dict[str, str]]]=None,
                         include_default=False,
                         docs: Optional[Doc]=None):
        names, kw, positional = self.argparse_spec(param, allow_positionals=allow_positionals,
                                                   implicit_flags=implicit_flags, include_default=include_default,
                                                   has_fallback=has_fallback, metavar=metavar, docs=docs)

        action = parser.add_argument(*names, **kw)
        try:
            completer = self.cli_completer
        except (TypeError, NotImplementedError):
            pass
        else:
            action.completer = completer

        action.positional = positional
        return action
