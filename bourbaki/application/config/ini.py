# coding:utf-8
import json
import configparser
from warnings import warn
from collections.abc import Mapping
from .exceptions import ConfigNotSerializable

NoneType = type(None)

# inferred-type .ini load/dump methods

# section in which to dump top-level values that aren't mappings
INI_DEFAULT_SECTION = "__TOP_LEVEL__"


class INIConfigUnserializable(ConfigNotSerializable):
    pass


def load_ini(file):
    parser = configparser.ConfigParser()
    parser.read_file(file)
    keys = parser.sections()
    conf = {
        s: {k: _dynamic_str_parse(parser.get(s, k)) for k in parser.options(s)}
        for s in keys
    }
    top_level = conf.pop(INI_DEFAULT_SECTION, None)
    if top_level:
        update = set(top_level.keys()).difference(conf)
        conf.update([(k, top_level[k]) for k in update])
        if len(update) < len(top_level):
            warn(
                "The keys {} were defined at the top level in {} and also as subsections; they will be overridden by "
                "the subsections".format(tuple(set(top_level).difference(update)), file)
            )
    return conf


def dump_ini(conf, file):
    def is_str_mapping(d):
        return isinstance(d, Mapping) and all(isinstance(key, str) for key in d.keys())

    if not is_str_mapping(conf) or any(
        (not isinstance(v, (str, int, bool, NoneType, float, list)))
        and (not is_str_mapping(v))
        for v in conf.values()
    ):
        raise INIConfigUnserializable(
            "Can only dump Mapping[str, Union[Mapping[str, Any], str, int, float, bool, NoneType, list]] "
            "in .ini format; got {}".format(conf)
        )

    dumper = configparser.ConfigParser(default_section=INI_DEFAULT_SECTION)

    for name, section in conf.items():
        if isinstance(section, Mapping):
            dumper.add_section(name)
            for k, v in section.items():
                dumper.set(name, k, _dynamic_repr(v))
        else:
            # no section
            dumper.set(None, name, _dynamic_repr(section))

    dumper.write(file)


def _dynamic_str_parse(s):
    for parser in int, float, _parse_bool, _parse_none, json.loads, str:
        try:
            val = parser(s)
        except (TypeError, ValueError, KeyError):
            continue
        else:
            break
    else:
        raise TypeError("Could not parse {} dynamically".format(s))
    return val


def _parse_bool(s):
    return {"true": True, "false": False, "True": True, "False": False}[s]


def _parse_none(s):
    return {"none": None, "None": None, "null": None, "Null": None}[s]


def _dynamic_repr(o):
    if isinstance(o, (str, list, NoneType, bool)):
        return json.dumps(o)
    else:
        return repr(o)
