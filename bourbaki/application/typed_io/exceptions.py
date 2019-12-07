# coding:utf-8
from inspect import signature
from bourbaki.introspection.types import eval_type_tree, concretize_typevars


class TypedIOTypeError(TypeError):
    def __init__(self, type_, *args):
        super().__init__(type_, *args)
        self.type_ = concretize_typevars(eval_type_tree(type_))


class TypedIOValueError(ValueError):
    def __init__(self, type_, value, exc=None):
        super().__init__(type_, value)
        self.type_ = concretize_typevars(eval_type_tree(type_))
        self.value = value
        self.exc = exc


class ExceptionReprMixin:
    def __repr__(self):
        return "{}({})".format(type(self).__name__, repr(str(self)))


class IOUndefinedForType(TypedIOTypeError, ExceptionReprMixin):
    source = None
    msg = "{}I/O is not defined for type {}"

    def __str__(self):
        source = "{} ".format(self.source.title()) if self.source else ""
        msg = self.msg.format(source, self.type_)
        if self.args:
            msg = msg + "; {}".format(self.args)
        return msg


class TypedInputError(TypedIOValueError, ExceptionReprMixin):
    source = None

    def __str__(self):
        source = "{} ".format(self.source) if self.source else ""
        msg = "Cannot parse type {} from {}value {}".format(
            self.type_, source, repr(self.value)
        )
        if self.exc is None:
            return msg
        return msg + "; raised {}".format(self.exc)


class TypedOutputError(TypedIOValueError, ExceptionReprMixin):
    source = None

    def __str__(self):
        source = "{} ".format(self.source) if self.source else ""
        msg = "Cannot write value {} to {}with target type {}".format(
            repr(self.value), source, self.type_
        )
        if self.exc is None:
            return msg
        return msg + "; raised {}".format(self.exc)


class ConfigIOUndefined(IOUndefinedForType):
    source = "configuration"


class ConfigIOUndefinedForKeyType(ConfigIOUndefined):
    msg = (
        "{}I/O is undefined for Mapping types with keys of type {}; "
        "use config_key_encoder.register to define a custom method"
    )


class ConfigCollectionKeysNotAllowed(ConfigIOUndefinedForKeyType):
    msg = "{}I/O is undefined for Mapping types with Collection-typed keys: {}"


class CLIIOUndefined(IOUndefinedForType):
    source = "command line"


class CLINestedCollectionsNotAllowed(CLIIOUndefined):
    msg = "{}I/O is undefined for nested collection types: {}"


class EnvIOUndefined(IOUndefinedForType):
    source = "configuration"


class ConfigTypedInputError(TypedInputError):
    source = "configuration"


class ConfigUnionInputError(ConfigTypedInputError):
    pass


class ConfigCallableInputError(ConfigTypedInputError):
    def __str__(self):
        msg = super().__str__()
        try:
            sig = signature(self.value)
        except ValueError:
            return msg
        else:
            return msg + "; signature is {}".format(sig)


class ConfigTypedOutputError(TypedOutputError):
    source = "configuration"


class ConfigTypedKeyOutputError(ConfigTypedOutputError):
    source = "configuration mapping key"


class ConfigUnionOutputError(ConfigTypedOutputError):
    pass


class CLITypedInputError(TypedInputError):
    source = "command line"


class CLIUnionInputError(CLITypedInputError):
    pass


class EnvTypedInputError(TypedInputError):
    source = "environment variable"
