# coding:utf-8
import os
import sys
from argparse import Action, SUPPRESS
from ..completion import install_shell_completion


# custom actions


def load_package_info(package):
    from pkg_resources import get_distribution
    from pkginfo import Distribution

    dist = get_distribution(package)
    meta = dist.get_metadata(dist.PKG_INFO)
    d = Distribution()
    d.parse(meta)
    return d.__dict__


def print_package_info(info, keys=None, exclude_keys=("package",)):
    if keys is None:
        value = {k: v for k, v in info.items() if k in info and k not in exclude_keys}
    elif isinstance(keys, str):
        value = info[keys]
    elif keys:
        value = {k: info[k] for k in keys if k in info and k not in exclude_keys}
    else:
        raise ValueError(
            "misunderstood keys arg; pass None, a string, or a collection of strings"
        )
    import yaml

    if isinstance(value, (int, str, bool, float, type(None))):
        print(value, file=sys.stdout)
    else:
        yaml.dump(value, sys.stdout, default_flow_style=False)


class InfoAction(Action):
    _info_type = "metadata"

    def __init__(
        self,
        option_strings,
        package,
        version=None,
        info_keys=None,
        dest=SUPPRESS,
        default=SUPPRESS,
        help=None,
    ):
        if help is None:
            help = "show {} for parent package {} and exit".format(
                self._info_type, repr(package)
            )

        super().__init__(
            option_strings=option_strings,
            dest=dest,
            default=default,
            nargs=0,
            help=help,
        )

        self.package = package
        self.version = version
        if version is True and info_keys and "version" not in info_keys:
            info_keys = ("version", *info_keys)
        self.info_keys = info_keys

    def load_package_info(self):
        info = load_package_info(self.package)
        if self.version is not None:
            if self.version is False:
                info.pop("version", None)
            elif self.version is not True:
                info["version"] = self.version
        return info

    def __call__(self, parser, namespace, values, option_string=None):
        info = self.load_package_info()
        print_package_info(info, keys=self.info_keys)
        sys.exit(0)


class PackageVersionAction(InfoAction):
    _info_type = "version"

    def __call__(self, *args, **kwargs):
        info = self.load_package_info()
        print_package_info(info, keys="version")
        sys.exit(0)


class InstallShellCompletionAction(Action):
    def __init__(
        self,
        option_strings,
        dest=SUPPRESS,
        default=SUPPRESS,
        help="Install bash completions for this CLI",
    ):
        super().__init__(
            option_strings=option_strings,
            dest=dest,
            default=default,
            nargs=0,
            help=help,
        )

    def __call__(self, parser, namespace, values, option_string=None):
        cmds = [parser.prog]
        src = getattr(parser, "source_file", None)
        if src is not None:
            cmds.append(os.path.basename(src))
        install_shell_completion(parser, *cmds)
        exit(0)


class SetExecuteFlagAction(Action):
    def __init__(
        self,
        option_strings,
        dest=SUPPRESS,
        default=SUPPRESS,
        help="only execute disk-altering, expensive, or external-resource-dependent commands if "
        "this flag is passed",
    ):
        super().__init__(
            option_strings=option_strings,
            dest=dest,
            default=default,
            nargs=0,
            help=help,
        )

    def __call__(self, parser, namespace, values, option_string=None):
        from bourbaki.application import cli

        cli.EXECUTE = False
