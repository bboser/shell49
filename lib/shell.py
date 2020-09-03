from board import BoardError
from connection import ConnectionError
from util import escape, unescape
from fileops import auto, listdir_matches
from printing import qprint, eprint, dprint
import printing

import sys

# apparently readline differs for various os'es

# https://pypi.python.org/pypi/gnureadline
# Mac: install gnureadline
#    Some platforms, such as macOS, do not ship with GNU readline installed.
#    As the alternatives to GNU readline do not have fully equivalent functionality, ...
# Linux: no install needed
#    This module is usually unnecessary on Linux and other Unix systems with
#    default readline support.
# Win: pyreadline
#    If you are using Windows, which also ships without GNU readline, you might
#    want to consider using the pyreadline module instead, which is a readline
#    replacement written in pure Python that interacts with the Windows clipboard.
try:
    if sys.platform == 'darwin' or sys.platform == 'linux':
        import gnureadline as readline
    elif sys.platform == 'win32':
        # import pyreadline as readline
        import readline
    sys.modules['readline'] = readline
except ImportError:
    import readline

import cmd
import inspect
import importlib
import argparse
import traceback
import os


class Shell(cmd.Cmd):

    def __init__(self, boards, editor):
        self.boards = boards
        self.config = boards.config
        self.editor = editor
        self.doc_header = 'shell49 commands'
        self.DELIMS = ' \t\n>;'
        self.interactive = False
        # working directory: we set this so file completion works correctly
        cwd = boards.config.get('default', 'startup_dir', '.')
        cwd = os.path.expanduser(cwd)
        self.cur_dir = cwd
        self.prev_dir = cwd
        os.chdir(os.path.expanduser(cwd))
        super(Shell, self).__init__()

    def set_prompt(self):
        try:
            board_name = self.boards.default.name
        except BoardError:
            board_name = 'NO BOARD'
        self.prompt = "{}{}:{}> {}".format(
            printing.PROMPT_COLOR,
            board_name,
            self.cur_dir,
            printing.OUTPUT_COLOR
        )

    def cmdloop(self, line=None):
        """Handle interactive and non-interactive input"""
        if line:
            # non-interactive (file or command)
            self.use_rawinput = False
            line = self.precmd(line)
            stop = self.onecmd(line)
            stop = self.postcmd(stop, line)
        else:
            # interactive
            self.interactive = True
            try:
                readline.set_completer_delims(self.DELIMS)
            except (AttributeError, NameError):
                # platforms that do not support readline (Windows)
                pass
            self.set_prompt()
            cmd.Cmd.cmdloop(self)

    def onecmd(self, line):
        """Global error catcher"""
        try:
            res = cmd.Cmd.onecmd(self, line)
            if self.interactive: self.set_prompt()
            return res
        except (BoardError, ConnectionError) as e:
            eprint("***", e)
        except UnicodeDecodeError as e:
            eprint("***", e)
        except KeyboardInterrupt:
            eprint("Command aborted")
        except Exception as e:
            # catchall, to prevent shell from quitting
            print(printing.ERR_COLOR)
            traceback.print_exc(file=sys.stdout)

    def emptyline(self):
        """Disable repeating previous command"""
        pass

    def default(self, line):
        eprint("Unrecognized command:", line)

    def do_EOF(self, line):
        """Type Control-D to quit."""
        qprint("Bye")
        return True

    def line_to_args(self, line):
        """Convert the line passed into the do_xxx functions into an array of arguments."""
        args = line.split()
        curr_cmd, _, _ = self.parseline(self.lastcmd)
        parser = self.create_argparser(curr_cmd)
        if parser:
            args = parser.parse_args(args)
        return args

    def create_argparser(self, command):
        try:
            argparse_args = getattr(self, "argparse_" + command)
        except AttributeError:
            return None
        doc_lines = getattr(
            self, "do_" + command).__doc__.expandtabs().splitlines()
        if '' in doc_lines:
            blank_idx = doc_lines.index('')
            usage = doc_lines[:blank_idx]
            description = doc_lines[blank_idx + 1:]
        else:
            usage = doc_lines
            description = []
        parser = argparse.ArgumentParser(
            prog=command,
            usage='\n'.join(usage),
            description='\n'.join(description),
            formatter_class=argparse.ArgumentDefaultsHelpFormatter
        )
        for args, kwargs in argparse_args:
            parser.add_argument(*args, **kwargs)
        return parser

    def filename_complete(self, text, line, begidx, endidx):
        """Wrapper for catching exceptions since cmd seems to silently
           absorb them.
        """
        try:
            return self.real_filename_complete(text, line, begidx, endidx)
        except:
            traceback.print_exc()

    def real_filename_complete(self, text, line, begidx, endidx):
        """Figure out what filenames match the completion."""

        # line contains the full command line that's been entered so far.
        # text contains the portion of the line that readline is trying to complete
        # text should correspond to line[begidx:endidx]
        #
        # The way the completer works text will start after one of the characters
        # in DELIMS. So if the filename entered so far was "embedded\ sp" and
        # then text will point to the s in sp.
        #
        # The following bit of logic backs up to find the real beginning of the
        # filename.

        for before_match in range(begidx, 0, -1):
            if line[before_match] in self.DELIMS and before_match >= 1 and line[before_match-1] != '\\':
                break

        # We set fixed to be the portion of the filename which is before text
        # and match is the full portion of the filename that's been entered so
        # far (that's that part we use for matching files).
        #
        # When we return a list of completions, the bit that we return should
        # just be the portion that we replace 'text' with.

        # fixed portion of the match
        fixed = unescape(line[before_match + 1:begidx])
        # portion to match filenames against
        match = unescape(line[before_match + 1:endidx])

        # We do the following to cover the case that the current directory
        # is / and the path being entered is relative.
        if match[0] == '/':
            abs_match = match
        elif self.cur_dir == '/':
            abs_match = self.cur_dir + match
        else:
            abs_match = self.cur_dir + '/' + match

        completions = []
        prepend = ''
        if abs_match.rfind('/') == 0:  # match is in the root directory
            # This means that we're looking for matches in the root directory
            # (i.e. abs_match is /foo and the user hit TAB).
            # So we'll supply the matching board names as possible completions.
            # Since they're all treated as directories we leave the trailing slash.
            if match[0] == '/':
                completions += [dev.name_path for dev in self.boards.boards()
                                if dev.name_path.startswith(abs_match)]
            else:
                completions += [dev.name_path[1:] for dev in self.boards.boards()
                                if dev.name_path.startswith(abs_match)]
            try:
                # Add root directories of the default device
                def_dev = self.boards.default
                if match[0] == '/':
                    completions += [
                        root_dir for root_dir in def_dev.root_dirs if root_dir.startswith(match)]
                else:
                    completions += [root_dir[1:]
                                    for root_dir in def_dev.root_dirs if root_dir[1:].startswith(match)]
            except BoardError:
                pass
        else:
            # This means that there are at least 2 slashes in abs_match. If one
            # of them matches a board name then we need to remove the board
            # name from fixed. Since the results from listdir_matches won't
            # contain the board name, we need to prepend each of the completions.
            for dev in self.boards.boards():
                if abs_match.startswith(dev.name_path):
                    prepend = dev.name_path[:-1]

        paths = sorted(auto(self.boards, listdir_matches, match))
        for path in paths:
            path = prepend + path
            completions.append(escape(path.replace(fixed, '', 1)))
        return completions

    def directory_complete(self, text, line, begidx, endidx):
        """Figure out what directories match the completion."""
        return [filename for filename in self.filename_complete(text, line, begidx, endidx) if filename[-1] == '/']



####################################################################
# dynamically load commands from do folder

def attach_commands():
    """Import commands defined in folder do/"""
    dir = os.path.dirname(inspect.getfile(inspect.currentframe()))
    dir = os.path.join(dir, 'do')
    for filename in os.listdir(dir):
        if not filename.startswith('do_') or not filename.endswith('.py'):
            continue
        module_name = os.path.splitext(filename)[0]
        cmd_name = module_name[3:]
        module = importlib.import_module(module_name)
        # attach to the shell
        dprint("attaching command", module_name, end='')
        setattr(Shell, module_name, getattr(module, module_name))
        try:
            argparse = "argparse_" + cmd_name
            setattr(Shell, argparse, getattr(module, argparse))
            dprint(" +", argparse, end='')
        except AttributeError:
            pass
        try:
            complete = "complete_" + cmd_name
            setattr(Shell, complete, getattr(module, complete))
            dprint(" +", complete, end='')
        except AttributeError:
            pass
        dprint()
