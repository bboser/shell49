from connection import SerialConnection, TelnetConnection, ConnectionError
from fileops import set_fileops_params
from autobool import AutoBool
from printing import dprint, eprint, qprint
import printing

from threading import Thread
import time
import inspect
import traceback
import os

from blessed import Terminal

QUIT_REPL_CHAR = 'X'
QUIT_REPL_BYTE = bytes((ord(QUIT_REPL_CHAR) - ord('@'),))  # Control-X


class BoardError(Exception):
    """Errors relating to board connections"""
    def __init__(self, msg):
        super().__init__(msg)


class Board(object):
    """Serial or telnet connection to a MicroPython REPL"""

    STATUS_UNKNOWN = 1
    STATUS_RAW_REPL = 2
    STATUS_NORMAL_REPL = 3

    def __init__(self, config):
        """New instance. Call open_XXX to establish connection."""
        self._config = config
        self._serial = None
        self._id = None
        self._has_buffer = False
        self._root_dirs = []
        # repl status (raw/normal/unknown)
        self._status = self.STATUS_UNKNOWN

    ###################################################################
    # connection

    def connect_serial(self, port, baudrate):
        """Connect to board via serial connection"""
        self._serial = SerialConnection(port, baudrate)
        self._board_characteristics()
        if not self.connected:
            raise BoardError("Failed to establish connection to board at '{}'".format(port))

    def connect_telnet(self, ip, user, password):
        """Connect via telnet"""
        self._serial = TelnetConnection(ip, user, password)
        self._board_characteristics()
        if not self.connected:
            raise BoardError("Failed to establish connection to board at '{}'".format(ip))

    def _board_characteristics(self):
        """Get device id and other updates"""
        # get unique board id
        self._id = self.remote_eval(get_unique_id, 'BOARD HAS NO ID')
        qprint("Connected to '{}' (id={}) ...".format(self.name, self.id), end='', flush=True)
        # check buffer
        self._has_buffer = self.remote_eval(test_buffer)
        qprint(" has_buffer={}".format(self._has_buffer), end='', flush=True)
        if self._serial.is_circuit_python:
            qprint()
        else:
            # get root dirs
            qprint("{} dirs=".format(self._has_buffer), end='', flush=True)
            self._root_dirs = ['/{}/'.format(dir) for dir in self.remote_eval(listroot)]
            qprint(self._root_dirs, end='', flush=True)
            if not self.get_config('mac'):
                qprint(" mac=", end='', flush=True)
                self.set_config('mac', self.remote_eval(get_mac_address))
                qprint(self.get_config('mac'), end='', flush=True)
            # sync time
            now = time.localtime(time.time())
            qprint(" sync time ...")
            self.remote(set_time, now.tm_year, now.tm_mon, now.tm_mday,
                        now.tm_hour, now.tm_min, now.tm_sec)
        qprint()

    def disconnect(self):
        """Disconnect and release port / ip"""
        dprint("Disconnecting board", self._id)
        self._id = None
        self._root_dirs = []
        if self._serial:
            self._serial.close()
            self._serial = None

    @property
    def connected(self):
        """Connected to a MicroPython REPL"""
        return self._serial and self._serial.connected

    ###################################################################
    # id & configuration

    @property
    def id(self):
        """Unique id of this board"""
        if not self._id:
            raise BoardError("board has no id")
        return self._id

    @property
    def address(self):
        """Board serial port or ip address"""
        return self._serial.address

    def match(self, spec):
        """Board matches spec: id, name, port, ip address or URL"""
        if self.id == spec: return True
        if self.name == spec: return True
        return self._serial.match(spec)

    @property
    def is_telnet(self):
        """Board is connected via telnet"""
        return self._serial.is_telnet

    @property
    def name(self):
        """Get board name"""
        return self.get_config('name', 'py')

    @property
    def name_path(self):
        """Path prefix for this board."""
        return '/{}/'.format(self.name)

    @name.setter
    def name(self, name):
        """Set board name. Note: stored only locally, not uploaded to board!"""
        self.set_config('name', name)

    def get_config(self, option, default=None):
        """Get configuration value"""
        return self._config.get(self._id, option, default)

    def set_config(self, option, value):
        """Set configuration value"""
        self._config.set(self._id, option, value)

    def remove_config_option(self, option):
        """Remove option from board config"""
        self._config.remove(self._id, option)

    def config_options(self):
        """List of all options of this board"""
        return self._config.options(self._id)

    def config_string(self):
        return self._config.config_string(self._id)

    def is_root_path(self, filename):
        """Determines if 'filename' corresponds to a directory on this device."""
        test_filename = filename + '/'
        for root_dir in self._root_dirs:
            if test_filename.startswith(root_dir):
                return True
        return False

    @property
    def root_dirs(self):
        """List of root directories on this board."""
        return self._root_dirs

    @property
    def has_buffer(self):
        """Board upy io has buffer"""
        return self._has_buffer

    def write(self, bytes):
        """Send bytes to board"""
        self._serial.write(bytes)

    def read(self, len):
        """Read bytes from board"""
        return self._serial.read(len)


    ###################################################################
    # repl and remote execution

    @property
    def repl_status(self):
        """Board repl status"""
        return self._status

    def enter_raw_repl(self):
        """Enter raw repl if not already in this mode."""
        if self._serial.is_circuit_python:
            self.enter_raw_repl_cp()
        else:
            self.enter_raw_repl_mp()

    def enter_raw_repl_cp(self):
        """Enter raw repl if not already in this mode for CIRCUITPYTHON."""
        # Ctrl-C twice: interrupt any running program
        dprint("^C, abort running program")
        self._serial.write(b'\r\x03\x03')

        # Ctrl-A: enter raw REPL
        dprint("^A, raw repl")
        self._serial.write(b'\r\x01')

        expect = b"raw REPL; CTRL-B to exit"
        data = self._serial.read_until(1, expect)
        if not data.endswith(expect):
            raise BoardError('Cannot enter raw repl: expected {}, got {}'.format(expect, data))

        expect = b"\r\n"
        data = self._serial.read_until(1, expect)
        if not data.endswith(expect):
            raise BoardError('Cannot enter raw repl: expected {}, got {}'.format(expect, data))

    def enter_raw_repl_mp(self):
        """Enter raw repl if not already in this mode for MICROPYTHON."""
        dprint("^B^C, abort running program")
        self._serial.write(b'\r\x02\x03')
        time.sleep(.1)

        # Attempt to get to REPL prompt, send Ctrl-C on failure.
        expect = b'> '
        abort = True
        for attempt in range(3):
            try:
                self._serial.read_until(1, expect)
                abort = False
                break
            except ConnectionError as err:
                dprint('ConnectionError: {0}'.format(err))
                self._serial.write(b'\x03')
                time.sleep(1)

        # Kickout if 3rd attempt fails
        if abort:
            raise ConnectionError('Failed to enter raw REPL')

        time.sleep(.1)

        # Ctrl-A: enter raw REPL
        dprint("^A, raw repl")
        self._serial.write(b'\r\x01')
        expect = b'raw REPL; CTRL-B to exit\r\n'
        data = self._serial.read_until(1, expect)
        if not data.endswith(expect):
            raise BoardError('Cannot enter raw repl: expected {}, got {}'.format(expect, data))

        # determine required steps
        # Note 1: no soft reset breaks telnet connection
        # Note 2: if user pressed reset button, mode status is STATUS_NORMAL_REPL
        #         but shell49 won't know it. Hence we cannot assume RAW_REPL.
        #         BUT soft reset is not required.
        if self.is_telnet or self._status == self.STATUS_RAW_REPL:
            dprint("enter_raw_repl: already in RAW REPL state, no action")
            return

        # Ctrl-D: soft reset
        dprint("^D, soft reset")
        self._serial.write(b'\x04')
        expect = b'soft reboot\r\n'
        data = self._serial.read_until(1, expect)
        if not data.endswith(expect):
            raise BoardError('Could not do soft reset: expected {}, got {}'.format(expect, data))
        # By splitting this into 2 reads, it allows boot.py to print stuff,
        # which will show up after the soft reboot and before the raw REPL.
        # The next read_until takes ~0.8 seconds (on ESP32)
        expect = b'raw REPL; CTRL-B to exit\r\n'
        data = self._serial.read_until(1, expect)
        if not data.endswith(expect):
            raise BoardError('Soft reset failed: expected {}, got {}'.format(expect, data))

        # update board status
        self._status = self.STATUS_RAW_REPL
        dprint("in raw repl")

    def exit_raw_repl(self):
        """Enter friendly (normal) repl."""
        # Ctrl-B: enter friendly REPL
        self._serial.write(b'\r\x02')
        self._status = self.STATUS_NORMAL_REPL

    def _exec_no_output(self, cmd, data_consumer=None, timeout=10):
        """Send command (string or bytes) to board for execution.
        Pass board output to data_consumer (e.g. print).
        no_output ... won't get execution output."""
        if isinstance(cmd, str):
            cmd = bytes(cmd, encoding='utf-8')
        dprint()
        dprint("_exec_no_output:", cmd.decode('utf-8')[:20])
        # enter raw repl (if needed) and check if we have a prompt
        self.enter_raw_repl()
        dprint("wait for >")
        data = self._serial.read_until(1, b'>', timeout=1)
        if not data.endswith(b'>'):
            raise BoardError("Cannot get response from board")
        # send command to board
        for i in range(0, len(cmd), 256):
            self._serial.write(cmd[i:min(i + 256, len(cmd))])
            time.sleep(0.01)
        # execute command
        self._serial.write(b'\x04')
        # check if successful
        if self._serial.read(2) != b'OK':
            self._status = self.STATUS_UNKNOWN
            raise BoardError("Could not exec '{} ...'".format(cmd.decode('utf-8').partition('\n')[0]))

    def _exec_output(self, data_consumer=None, timeout=10):
        """Read output after exec_no_output"""
        # self._serial.write(b'123\r')
        data = self._serial.read_until(1, b'\x04', timeout=timeout, data_consumer=data_consumer)
        if not data.endswith(b'\x04'):
            raise BoardError('_exec_output expected 1st EOF, got "{}"'.format(data))
        data = data[:-1]
        # wait for error output
        data_err = self._serial.read_until(1, b'\x04', timeout=timeout)
        if not data_err.endswith(b'\x04'):
            raise BoardError('_exec_output expected 2nd EOF, got "{}"'.format(data))
        data_err = data_err[:-1]
        if data_err:
            self._status = self.STATUS_UNKNOWN
            raise BoardError("Exec -> {}".format(data_err.decode('utf-8')))
        # return result
        return data

    def exec(self, cmd, *, data_consumer=None, timeout=10):
        """Send cmd (str or bytes) to board for execution and return result."""
        try:
            self._exec_no_output(cmd, data_consumer, timeout)
            return self._exec_output(data_consumer, timeout)
        except ConnectionError:
            self.disconnect()
            raise

    def execfile(self, filename, *, data_consumer=None, timeout=10):
        """Exec file on remote board return results.
        Also passes output to data_consumer as they become available.
        Timeout None disables timeout.
        """
        with open(os.path.expanduser(filename), 'rb') as f:
            cmds = f.read()
        try:
            self.exec(cmds, data_consumer=data_consumer, timeout=timeout)
        finally:
            self._status = self.STATUS_UNKNOWN


    ###################################################################
    # remote function call

    def _remote_repr(self, i):
        """Helper function to deal with types which we can't send to the pyboard."""
        repr_str = repr(i)
        if repr_str and repr_str[0] == '<':
            return 'None'
        return repr_str

    def remote(self, func, *args, xfer_func=None, **kwargs):
        """Call func with args on the micropython board."""
        has_buffer = self._has_buffer
        buffer_size = self.get_config('buffer_size', default=128)
        time_offset = self.get_config('time_offset', default=946684800)
        set_fileops_params(has_buffer, buffer_size, time_offset)
        args_arr = [self._remote_repr(i) for i in args]
        kwargs_arr = ["{}={}".format(k, self._remote_repr(v)) for k, v in kwargs.items()]
        func_str = inspect.getsource(func)
        func_str += 'output = ' + func.__name__ + '('
        func_str += ', '.join(args_arr + kwargs_arr)
        func_str += ')\n'
        func_str += 'if output is None:\n'
        func_str += '    print("None")\n'
        func_str += 'else:\n'
        func_str += '    print(output)\n'
        func_str = func_str.replace('TIME_OFFSET', '{}'.format(time_offset))
        func_str = func_str.replace('HAS_BUFFER', '{}'.format(has_buffer))
        func_str = func_str.replace('BUFFER_SIZE', '{}'.format(buffer_size))
        func_str = func_str.replace('IS_UPY', 'True')
        start_time = time.time()
        output = self._exec_no_output(func_str)
        if xfer_func:
            xfer_func(self, *args, **kwargs)
        output = self._exec_output()
        dprint("remote: {}({}) --> {},   in {:.3} s)".format(
            func.__name__,
            repr(args)[1:-1],
            output,
            time.time()-start_time))
        return output

    def remote_eval(self, func, *args, **kwargs):
        """Calls func with the indicated args on the micropython board, and
           converts the response back into python by using eval.
        """
        res = self.remote(func, *args, **kwargs)
        try:
            return eval(res)
        except (SyntaxError, ValueError) as e:
            eprint("*** remote_eval({}, {}, {}) -> \n{} is not valid python code".format(
                func.__name__, args, kwargs, res.decode('utf-8')))
            return None

    ###################################################################
    # repl

    def _repl_serial(self, serial_ok):
        """Thread, copies bytes from serial to out"""

        term = Terminal()

        try:
            with serial_ok, term.raw():
                save_timeout = self._serial.timeout
                # Set a timeout so that the read returns periodically with no data
                # and allows us to check whether the main thread wants us to quit.
                self._serial.timeout = 0.4
                while not self._quit_serial_reader:
                    char = self._serial.read(1)
                    if char.decode('utf-8') != '':
                        print(char.decode('utf-8'), end='', flush=True)
                self._serial.timeout = save_timeout
        except ConnectionError as e:
            self.disconnect()
            print('\r')
            eprint(str(e).replace('\n', '\r'))
        except Exception:
            # catchall, print error traceback
            from io import StringIO
            s = StringIO()
            print('\r', printing.ERR_COLOR)
            traceback.print_exc(file=s)
            eprint(s.getvalue().replace('\n', '\r'))

    def repl(self, getch):

        self.exit_raw_repl()
        # who knows what state we are in after repl?
        serial_ok = AutoBool()

        self._quit_serial_reader = False
        repl_thread = Thread(target=self._repl_serial, args=[serial_ok], name="REPL")
        repl_thread.daemon = True
        repl_thread.start()
        # wait for reader to start
        while not serial_ok(): pass
        try:
            # Wake up the prompt
            self._serial.write(b'\r')
            while serial_ok():
                char = getch()
                if not char: continue
                if char == QUIT_REPL_BYTE:
                    self._quit_serial_reader = True
                    # needed by some boards, e.g. WiPy
                    self._serial.write(b' ')
                    # wait for reader thread to notice
                    time.sleep(0.5)
                    # print newline so the shell49 prompt looks good
                    print('\n')
                    # stay in the loop until the reader thread is quitting
                    continue
                if char == b'\n':
                    char = b'\r'
                self._serial.write(char)
        except (AttributeError, BoardError):
            # Board no longer present?
            self.disconnect()
            print('\n')


###################################################################
# remote operations, these run on the uPy board

def get_unique_id(default):
    """Inquire the boards unique id."""
    try:
        from microcontroller import cpu
        from binascii import hexlify
        uid = hexlify(cpu.uid).decode('ascii')
    except:
        try:
            from machine import unique_id
            from binascii import hexlify
            uid = hexlify(unique_id()).decode('ascii')
        except:
            uid = default
    return repr(uid)

def listroot():
    """Return list of filenames contained in root directory."""
    import os
    return os.listdir('/')

def get_mac_address():
    try:
        from binascii import hexlify
        from network import WLAN, STA_IF
        mac = hexlify(WLAN(STA_IF).config('mac'), ':').decode('ascii')
    except:
        mac = None
    return repr(mac)

def set_time(y, m, d, h, min, s):
    """Set time on upy board."""
    rtc = None
    try:
        import pyb
        rtc = pyb.RTC()
        rtc.datetime((y, m, d, None, h, min, s))
        return rtc.datetime()
    except:
        try:
            import machine
            rtc = machine.RTC()
            if not rtc.synced():
                try:
                    rtc.datetime((y, m, d, None, h, min, s))
                    return rtc.datetime()
                except:
                    rtc.init((y, m, d, h, min, s))
                    return rtc.now()
        except:
            return None

def test_buffer():
    """Check micropython firmware to see if sys.stdin.buffer exists."""
    import sys
    try:
        return sys.stdin.buffer != None
    except:
        return False

###################################################################
# test code

def data_consumer(bytes):
    print(bytes.decode('utf-8'), end='')

def putch(byte):
    print(byte.decode('utf-8'), end='', flush=True)

def main():
    from . config import Config
    from . timeit import Timeit

    port = "/dev/cu.SLAB_USBtoUART"
    baudrate = 115200
    config = Config('~/Dropbox/Files/Class/49/.shell49_rc.py')

    with Timeit() as t:
        board = Board(config)
        board.connect_serial(port, baudrate)
    print("*** Connecting to board took {:0.3f} seconds".format(t.interval))

    print(board.exec("print(2**100)", data_consumer=data_consumer).decode('utf-8'))
    print(board.remote(get_unique_id, "no_id"))
    if False:
        from . getch import getch
        board.repl(getch, putch)
    print(board.exec("print(2**30)").decode('utf-8'))
    print(board.remote(get_unique_id, "no_id"))
    print(board.exec("print(2**80)").decode('utf-8'))
