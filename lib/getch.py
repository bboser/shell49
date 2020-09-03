#!/usr/bin/env python3

"""Implements getch. From: https://gist.github.com/chao787/2652257"""

# Last modified: <2012-05-10 18:04:45 Thursday by richard>

# @version 0.1
# @author : Richard Wong
# Email: chao787@gmail.com

import sys

class _Getch:
    """
    Gets a single character from standard input.  Does not echo to
    the screen.
    """

    def __init__(self):
        self.impl = _GetchWindows() if sys.platform == 'win32' else _GetchUnix()

    def __call__(self):
        return self.impl()


class _GetchUnix:
    def __init__(self):
        pass

    def __call__(self):
        import sys
        import tty
        import termios
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.buffer.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            return ch


class _GetchWindows:

    def __init__(self):
        pass

    def __call__(self):
        import msvcrt
        lookup = {b'M': b'\x1b\x5b\x43',
                  b'P': b'\x1b\x5b\x42',
                  b'H': b'\x1b\x5b\x41',
                  b'K': b'\x1b\x5b\x44',
                  b'S': b'\x1b\x5b\x33\x7e',
                  b'G': b'\x1b\x5b\x31\x7e',
                  b'O': b'\x1b\x5b\x34\x7e'}
        char = msvcrt.getch()
        if char == b'\x08':
            char = b'\x7f'
        elif char == b'\xe0':
            char = lookup.get(msvcrt.getch(), b' ')

        return char
        #return msvcrt.getch()

getch = _Getch()

if __name__ == "__main__":
    ch = getch()
    print('ch =', ch)

