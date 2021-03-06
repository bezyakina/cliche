import re
import sys
import argparse
from cliche.docstring_to_help import parse_doc_params

pydantic_models = {}


class ColoredHelpOnErrorParser(argparse.ArgumentParser):

    # color_dict is a class attribute, here we avoid compatibility
    # issues by attempting to override the __init__ method
    # RED : Error, GREEN : Okay, YELLOW : Warning, Blue: Help/Info
    color_dict = {'RED': '1;31', 'GREEN': '1;32', 'YELLOW': '1;33', 'BLUE': '1;36'}
    # only when called with `cliche`, not `python`
    module_name = False

    def print_help(self, file=None):
        if file is None:
            file = sys.stdout
        self._print_message(self.format_help(), file, self.color_dict['BLUE'])

    def _print_message(self, message, file=None, color=None):
        if message:
            message = message[0].upper() + message[1:]
            if self.module_name:
                repl = " ".join(["cliche " + self.module_name] + self.prog.split()[1:])
                message = message.replace(self.prog, repl)
            if file is None:
                file = sys.stderr
            # Print messages in bold, colored text if color is given.
            if color is None:
                file.write(message)
            else:
                # \x1b[ is the ANSI Control Sequence Introducer (CSI)
                if color == self.color_dict["BLUE"]:
                    message = message.strip()
                    message = message.replace("positional arguments:", "POSITIONAL ARGUMENTS:")
                    message = message.replace("optional arguments:", "OPTIONAL ARGUMENTS:")
                    message = re.sub(
                        "^Usage: .+", "\x1b[" + color + "m" + r"\g<0>" + "\x1b[0m", message
                    )
                    message = re.sub(
                        "Default: [^|]+", "\x1b[" + color + "m" + r"\g<0>" + "\x1b[0m", message
                    )

                    reg = ", (--[^ ]+) "
                    message = re.sub(
                        reg, ", " + "\x1b[" + color + "m" + r"\g<1> " + "\x1b[0m", message
                    )
                    for reg in ["\n  -h, --help", "\n +--[^ ]+", "\n  ? ? ? ? ? ?[a-z0-9A-Z_-]+"]:
                        message = re.sub(reg, "\x1b[" + color + "m" + r"\g<0>" + "\x1b[0m", message)
                    file.write(message + "\n")
                else:
                    file.write('\x1b[' + color + 'm' + message.strip() + '\x1b[0m\n')

    def exit(self, status=0, message=None):
        if message:
            self._print_message(message, sys.stderr, self.color_dict['RED'])
        sys.exit(status)

    def error(self, message):
        message = message.replace(
            "unrecognized arguments", "unrecognized (too many positional) arguments"
        )
        self.print_help(sys.stderr)
        self.exit(2, message)


#     def error(self, message):
#         # TODO: it actually now prints generic help but it should print the specific help of the subcommand
#         # print(sys.modules[cli.__module__].__doc__)

#         message = message.replace(
#             "unrecognized arguments", "unrecognized (too many positional) arguments"
#         )
#         warn(f"error: {message}")
#         sys.exit(2)


def add_command(subparsers, fn_name, fn):
    doc_str = fn.__doc__ or ""
    desc = re.split("^ *Parameter|^ *Return|^ *Example|:param|\n\n", doc_str)[0].strip()
    desc = desc.replace("%", "%%")
    cmd = subparsers.add_parser(fn_name.replace("_", "-"), help=desc, description=desc)
    return cmd


def is_pydantic(class_type):
    try:
        return "BaseModel" in [x.__name__ for x in class_type.__mro__]
    except AttributeError:
        return False


def add_group(parser_cmd, model, fn, var_name, abbrevs):
    kwargs = []
    pydantic_models[fn] = {}
    group = parser_cmd.add_argument_group(model.__name__.replace("_", "-"))
    for field_name, field in model.__fields__.items():
        kwargs.append(field_name)
        default = field.default if field.default is not None else "--1"
        default_help = f"Default: {default} | " if default != "--1" else ""
        tp = field.type_
        container_type = tp in [list, set, tuple]
        try:
            container_type = tp._name in ["List", "Iterable", "Set", "Tuple"]
        except AttributeError:
            pass
        if is_pydantic(tp):
            msg = (
                f"Cannot use nested pydantic just yet:"
                + f"property {var_name}.{field_name} of function {fn.__name__}"
            )
            raise ValueError(msg)
        arg_desc = f"|{tp.__name__}| {default_help}"
        add_argument(group, tp, container_type, field_name, default, arg_desc, abbrevs)
    pydantic_models[fn][var_name] = (model, kwargs)


def get_var_names(var_name, abbrevs):
    # adds shortenings when possible
    if var_name.startswith("--"):
        short = "-" + var_name[2]
        if short not in abbrevs:
            abbrevs.append(short)
            var_names = [short, var_name]
        elif short.upper() not in abbrevs:
            abbrevs.append(short.upper())
            var_names = [short.upper(), var_name]
        else:
            var_names = [var_name]
    else:
        var_names = [var_name]
    return var_names


def add_argument(parser_cmd, tp, container_type, var_name, default, arg_desc, abbrevs):
    action = "store"
    var_name = var_name.replace("_", "-")
    arg_desc = arg_desc.replace("%", "%%")
    if tp is bool:
        action = "store_true" if not default else "store_false"
        var_names = get_var_names("--" + var_name, abbrevs)
        parser_cmd.add_argument(*var_names, action=action, help=arg_desc)
        return
    nargs = None
    if default != "--1":
        var_name = "--" + var_name
    if container_type:
        try:
            tp = tp.__args__[0]
            nargs = "+"
        except AttributeError as e:
            pass
    var_names = get_var_names(var_name, abbrevs)
    parser_cmd.add_argument(*var_names, type=tp, nargs=nargs, default=default, help=arg_desc)


def add_arguments_to_command(cmd, fn):
    doc_str = fn.__doc__ or ""
    arg_count = fn.__code__.co_argcount
    defs = fn.__defaults__ or tuple()
    defaults = (("--1",) * arg_count + defs)[-arg_count:]
    doc_params = parse_doc_params(doc_str)
    abbrevs = ["-h"]
    for var_name, default in zip(fn.__code__.co_varnames, defaults):
        default_help = f"Default: {default} | " if default != "--1" else ""
        default_type = type(default) if default != "--1" and default is not None else None
        tp = fn.__annotations__.get(var_name, default_type or str)
        # List, Iterable, Set, Tuple
        container_type = False
        if default_type in [list, set, tuple]:
            for value in default:
                break
            else:
                value = ""
            container_type = default_type
            if "typing" not in str(tp):
                tp_args = ", ".join(set(type(x).__name__ for x in default)) or "str"
                tp_name = "1 or more of: " + tp_args
                tp = None
            else:
                tp_args = ", ".join(x.__name__ for x in tp.__args__)
                tp_name = "1 or more of: " + tp_args
                # tp = type(value)
                tp = None
        else:
            try:
                container_type = tp._name in ["List", "Iterable", "Set", "Tuple"]
            except AttributeError:
                pass
            if container_type:
                if tp.__args__ and "Union" in str(tp.__args__[0]):
                    # cannot cast
                    tp_arg = "str"
                elif tp.__args__:
                    tp_arg = tp.__args__[0].__name__
                else:
                    tp_arg = "str"
                tp_name = "1 or more of: " + tp_arg
            else:
                tp_name = tp.__name__
        if is_pydantic(tp):
            # msg = f"Cannot use pydantic just yet, argument {var_name!r} (type {tp.__name__}) on cmd {cmd.prog!r}"
            # raise ValueError(msg)
            add_group(cmd, tp, fn, var_name, abbrevs)
            continue
        arg_desc = f"|{tp_name}| {default_help}" + doc_params.get(var_name, "")
        add_argument(cmd, tp, container_type, var_name, default, arg_desc, abbrevs)
