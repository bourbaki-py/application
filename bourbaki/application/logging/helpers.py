# coding:utf-8
from logging import _nameToLevel, _levelToName


def validate_log_level(level):
    assert (
        level in _nameToLevel or level in _levelToName or level == "NOTSET"
    ), "'{}' is not a valid logging level".format(level)
    return level


def validate_log_level_int(level):
    level = validate_log_level(level)
    return level if level in _levelToName else _nameToLevel.get(level, level)


def validate_log_level_str(level):
    level = validate_log_level(level)
    return level if level in _nameToLevel else _levelToName.get(level, level)
