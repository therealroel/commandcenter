import os
import pty
import fcntl
import termios
import struct
import signal

import gevent
import gevent.socket


class PtyBridge:
    """Spawns a child process under a PTY and pipes bytes to/from a callback."""

    def __init__(self, argv, on_data, rows=40, cols=120, env=None):
        self.on_data = on_data
        self.alive = False
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            # child
            if env:
                for k, v in env.items():
                    os.environ[k] = v
            os.environ.setdefault("TERM", "xterm-256color")
            try:
                os.execvp(argv[0], argv)
            except Exception:
                os._exit(1)
        # parent
        self.alive = True
        self.resize(rows, cols)
        self._reader = gevent.spawn(self._read_loop)

    def _read_loop(self):
        while self.alive:
            try:
                gevent.socket.wait_read(self.fd)
                data = os.read(self.fd, 8192)
            except (OSError, EOFError):
                break
            if not data:
                break
            try:
                self.on_data(data)
            except Exception:
                pass
        self.alive = False
        try:
            self.on_data(b"\r\n\x1b[31m[session ended]\x1b[0m\r\n")
        except Exception:
            pass

    def write(self, data):
        if not self.alive:
            return
        if isinstance(data, str):
            data = data.encode("utf-8", errors="replace")
        try:
            os.write(self.fd, data)
        except OSError:
            self.alive = False

    def resize(self, rows, cols):
        try:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ,
                        struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass

    def close(self):
        self.alive = False
        try:
            os.kill(self.pid, signal.SIGHUP)
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass
