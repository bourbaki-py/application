# coding:utf-8
from typing import Mapping, Any
import os
import functools
import io
import tempfile
import pytest
from itertools import chain, repeat
from copy import deepcopy
from sklearn.base import BaseEstimator
from multipledispatch import dispatch
from bourbaki.application.config import (
    load_config,
    dump_config,
    allow_unsafe_yaml,
    LEGAL_CONFIG_EXTENSIONS,
)
from bourbaki.application.typed_io.inflation import CLASSPATH_KEY, KWARGS_KEY
from bourbaki.application.typed_io.config_decode import config_decoder

# remove duplicate .yaml -> .yml
LEGAL_CONFIG_EXTENSIONS = tuple(e for e in LEGAL_CONFIG_EXTENSIONS if e != ".yaml")
NON_JSON_INI_EXTENSIONS = tuple(
    e for e in LEGAL_CONFIG_EXTENSIONS if e not in (".toml", ".json", ".ini")
)
NON_JSON_EXTENSIONS = tuple(
    e for e in LEGAL_CONFIG_EXTENSIONS if e not in (".toml", ".json")
)
NON_INI_EXTENSIONS = tuple(e for e in LEGAL_CONFIG_EXTENSIONS if e not in (".ini",))
ALLOW_INT_KEYS_EXTENSIONS = (".yml", ".py")

construct_instances_recursively = config_decoder(Mapping[str, BaseEstimator])

sklearnconf = {
    "forest": {
        CLASSPATH_KEY: "sklearn.ensemble.RandomForestClassifier",
        KWARGS_KEY: {"min_samples_split": 5, "n_estimators": 100},
    },
    "isolation_forest_n192_s1024": {
        CLASSPATH_KEY: "sklearn.ensemble.iforest.IsolationForest",
        KWARGS_KEY: {
            "bootstrap": True,
            "max_samples": 1024,
            "n_estimators": 192,
            "n_jobs": 7,
        },
    },
    "logistic_l1": {
        CLASSPATH_KEY: "sklearn.linear_model.LogisticRegression",
        KWARGS_KEY: {"penalty": "l1"},
    },
    "logistic_l1_highreg": {
        CLASSPATH_KEY: "sklearn.linear_model.LogisticRegression",
        KWARGS_KEY: {
            "C": 0.1,
            # 'class_weight': {0: 0.01, 1: 0.99},
            "penalty": "l1",
        },
    },
    "logistic_l2": {
        CLASSPATH_KEY: "sklearn.linear_model.LogisticRegression",
        KWARGS_KEY: {"penalty": "l2"},
    },
    "logistic_l2_highreg": {
        CLASSPATH_KEY: "sklearn.linear_model.LogisticRegression",
        KWARGS_KEY: {
            "C": 0.1,
            # 'class_weight': {0: 0.01, 1: 0.99},
            "penalty": "l2",
        },
    },
    "svc": {
        CLASSPATH_KEY: "sklearn.svm.SVC",
        KWARGS_KEY: {
            "C": 1.0,
            "cache_size": 1024,
            # 'class_weight': {0: 0.01, 1: 0.99},
            "coef0": 0.0,
            "degree": 2,
            "gamma": "auto",
            "kernel": "poly",
            "probability": True,
        },
    },
}

sklearnconf_w_int_keys = deepcopy(sklearnconf)
sklearnconf_w_int_keys["svc"][KWARGS_KEY]["class_weight"] = {0: 0.01, 1: 0.99}


fooconf = dict(foo="bar", baz=(1, 2, {3: 4, 5: [6, 7]}), qux=["foo", ("bar", "baz")])

# replace lists with tuples
@dispatch(dict)
def jsonify(obj, str_keys=True):
    f = str if str_keys else lambda x: x
    return {f(k): jsonify(v, str_keys=str_keys) for k, v in obj.items()}


@dispatch((list, tuple))
def jsonify(obj, str_keys=True):
    return list(map(functools.partial(jsonify, str_keys=str_keys), obj))


@dispatch(object)
def jsonify(obj, str_keys=True):
    return obj


@pytest.fixture(scope="function")
def tmp():
    f = tempfile.mktemp()
    yield f


def test_top_level_in_ini():
    # values with no sections dump and load in .ini as we would expect in .toml
    s = """
    value1 = "foo"
    [section]
    value2 = 1
    """
    f = io.StringIO(s)
    c = load_config(f, ext=".toml")
    newf = io.StringIO()
    dump_config(c, newf, ext=".ini")
    newf.seek(0)
    assert c == load_config(newf, ext=".ini")


def test_inflate_instances():
    models = construct_instances_recursively(sklearnconf_w_int_keys)
    for v in models.values():
        assert isinstance(v, BaseEstimator)


@pytest.mark.parametrize("ext", NON_JSON_INI_EXTENSIONS)
@pytest.mark.parametrize("conf", [sklearnconf, fooconf])
def test_dump_load_python_yaml(conf, ext, tmp):
    if not os.path.exists(tmp):
        with open(tmp + ext, "w"):
            pass
    dump_config(conf, tmp, ext=ext)
    conf_ = load_config(tmp + ext, disambiguate=True)
    assert jsonify(conf, str_keys=False) == jsonify(conf_, str_keys=False)
    os.remove(tmp + ext)


@pytest.mark.parametrize("conf", [sklearnconf, fooconf])
def test_dump_load_json(conf, tmp):
    ext = ".json"
    dump_config(conf, tmp, ext=ext)
    conf_ = load_config(tmp, disambiguate=True)
    assert jsonify(conf) == conf_
    # os.remove(tmp + ext)


@pytest.mark.parametrize(
    "ext,conf",
    chain(
        zip(NON_INI_EXTENSIONS, repeat(sklearnconf)),
        zip(ALLOW_INT_KEYS_EXTENSIONS, repeat(sklearnconf_w_int_keys)),
    ),
)
def test_dump_load_class_instances(ext, conf, tmp):
    dump_config(conf, tmp, ext=ext)
    conf_ = load_config(tmp, disambiguate=True)
    models = construct_instances_recursively(conf)
    models_ = construct_instances_recursively(conf_)

    for m in (models, models_):
        for v in m.values():
            assert isinstance(v, BaseEstimator)

    assert models_.keys() == models.keys()

    for k in models:
        m1 = models[k]
        m2 = models_[k]
        c = conf[k]
        for attr in c[KWARGS_KEY]:
            attr1 = getattr(m1, attr)
            if ext == ".json":
                attr1 = jsonify(attr1)

            assert attr1 == getattr(m2, attr)

    # os.remove(tmp + ext)
