from board import QUIT_REPL_CHAR
from getch import getch
from printing import eprint, mprint
import printing


def do_repl(self, line):
    """repl [board-name] [~ line [~]]

       Enters into the regular REPL (read-eval-print-loop) with the
       MicroPython board.
       Use Control-X to exit REPL mode and return the shell.
       It may take a couple of seconds before the REPL exits.

       If you provide a line to the repl command, then that will be executed.
       If you want the REPL to exit, end the line with the ~ character.
    """
    args = self.line_to_args(line)
    if len(args) > 0 and line[0] != '~':
        name = args[0]
        line = ' '.join(args[1:])
        board = self.boards.find_board(name)
        if not board:
            eprint("No board '{}'".format(name))
            return
    else:
        board = self.boards.default

    if line[0:2] == '~ ':
        line = line[2:]

    mprint('Entering REPL.  Control-%c to exit.' % QUIT_REPL_CHAR)
    mprint('   Soft reset:  Control-D or sys.exit()')
    mprint('   Hard reset:  Reset button on board or machine.reset()')
    print(printing.MPY_COLOR, end='')

    board.repl(getch)
    print()


def putch(byte):
    print(byte.decode('utf-8'), end='', flush=True)
