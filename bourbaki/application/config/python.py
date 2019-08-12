# coding:utf-8
import os
import ast
import ujson as json
from bourbaki.introspection.prettyprint import fmt_pyobj
from .exceptions import ConfigNotSerializable

DEFAULT_PY_INDENT = '    '
MAX_PY_WIDTH = 80


class UnsafePythonSourceConfig(SyntaxError):
    pass


class IllegalFunctionInSourceConfig(UnsafePythonSourceConfig):
    pass


class IllegalExpressionInSourceConfig(UnsafePythonSourceConfig):
    pass


class PythonConfigNotSerializable(ConfigNotSerializable):
    pass


def is_json_serializable(conf):
    try:
        with open(os.devnull, "w") as f:
            json.dump(conf, f)
    except TypeError:
        return False
    else:
        return True


# safe python syntactic constructs for configuration
legal_python_config_exprs = (ast.Num, ast.Str, ast.BinOp, ast.operator, ast.Compare, ast.Name, ast.Attribute,
                             ast.List, ast.Tuple, ast.Dict, ast.Set, ast.Bytes, ast.Subscript, ast.Ellipsis,
                             ast.ListComp, ast.DictComp, ast.SetComp, ast.comprehension,
                             ast.keyword, ast.NameConstant, ast.Assign, ast.Call)

# safe python builtin functions for configuration
legal_builtin_functions = {'abs', 'all', 'any', 'ascii', 'bin', 'bool', 'bytearray', 'bytes', 'callable', 'chr',
                           'complex', 'dict', 'dir', 'divmod', 'enumerate', 'filter', 'frozenset', 'hash', 'hex',
                           'id', 'int', 'iter', 'len', 'list', 'map', 'max', 'min', 'next', 'oct', 'ord', 'pow',
                           'range', 'repr', 'reversed', 'round', 'set', 'slice', 'sorted', 'str', 'sum', 'tuple',
                           'vars', 'zip'}


def validate_python_config_source(ast_or_source):
    if isinstance(ast_or_source, str):
        tree = ast.parse(ast_or_source)
    else:
        tree = ast_or_source

    msg = ("when using python source as configuration, supply only a single expression "
          "(generally a builtin collection expression) or a sequence of variable assignments; got {}")
    mode = 'exec'
    if len(tree.body) > 1:
        if not all(isinstance(node, ast.Assign) for node in tree.body):
            raise SyntaxError(msg.format(list(map(type, tree.body))))
    elif len(tree.body) == 1:
        if not isinstance(tree.body[0], (ast.Expr, ast.Assign)):
            raise SyntaxError(msg.format(type(tree.body[0])))
        if isinstance(tree.body[0], ast.Expr):
            mode = 'eval'

    def inner(node):
        if isinstance(node, (list, ast.Module)):
            if not isinstance(node, list):
                node = node.body
            return all(inner(v) for v in node)

        if isinstance(node, ast.Call):
            f = node.func
            msg = "function {} is not allowed in python configuration source; occurred at line {}, column {}"
            if isinstance(f, ast.Name) and f.id not in legal_builtin_functions:
                raise IllegalFunctionInSourceConfig(msg.format(repr(node.func.id), node.lineno, node.col_offset))
            elif not isinstance(f, ast.Name):
                raise IllegalFunctionInSourceConfig(msg.format(repr(node.func), node.lineno, node.col_offset))

        if isinstance(node, ast.Expr):
            return inner(node.value)

        if not isinstance(node, legal_python_config_exprs):
            raise IllegalExpressionInSourceConfig("expression type {} is not allowed in python configuration source; "
                                                  "occurred at line {}, column {}"
                                                  .format(type(node), node.lineno, node.col_offset))

        subexprs = tuple(getattr(node, attr) for attr in node._fields)
        subexprs = (e for e in subexprs if isinstance(e, (ast.AST, list)) and not isinstance(e, (ast.Store, ast.Load)))

        return all(map(inner, subexprs))

    if inner(tree):
        if mode == 'eval':
            tree = ast.Expression(tree.body[0].value)
        return tree, mode


def load_python(file):
    source = file.read()
    path = getattr(file, 'name', '<string>')
    tree, mode = validate_python_config_source(source)
    code = compile(tree, filename=path, mode=mode)
    if mode == 'eval':
        conf = eval(source, {})
    else:
        conf = {}
        exec(code, conf)
        conf.pop('__builtins__', None)
    return conf


def dump_python(conf, file, check_json_compat=False):
    if check_json_compat and not is_json_serializable(conf):
        raise PythonConfigNotSerializable("can only write json-serializable config to python source; got {}"
                                         .format(conf))

    print(fmt_pyobj(conf, top_level=True), file=file)
