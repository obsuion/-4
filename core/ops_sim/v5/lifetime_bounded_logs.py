"""Bounded administrative stdout/stderr capture for the existing owned child.

The child inherits anonymous-pipe write handles, never the disk-file handles.
Two parent drainers keep consuming after an overflow/error; only the bounded
prefix reaches disk. This module neither launches nor reaps a process.
"""
from pathlib import Path
import math
import os
import threading
import time
from .lifetime_io_accounting import fsync


class BoundedLogPipes:
    """Start drainers now; close parent writers immediately after child launch.

    After the private Job has been reaped, finish with that SAME absolute cleanup
    deadline. A timeout/error is explicit; it is never reported as clean closure.
    stdout/stderr expose real binary pipe writers for the unchanged factory.
    """
    BLOCK_BYTES = 65536

    def __init__(self, directory, maximum_bytes=2**20):
        if type(maximum_bytes) is not int or not 1 <= maximum_bytes <= 2**20:
            raise ValueError('YEAR-V4 exact bounded aggregate log bytes')
        self.maximum_bytes = maximum_bytes
        self.directory = Path(directory)
        if not self.directory.is_dir() or self.directory.is_symlink():
            raise ValueError('YEAR-V4 existing owned log directory required')
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads = []
        self._writers = []
        self._errors = []
        self._reserved = self._written = self._received = self._dropped = 0
        self._overflow = False
        self._finished = False
        self._reader_completion = [None, None]
        self._cleanup_deadline = None
        self._streams = []
        self.stdout = self.stderr = None
        try:
            from .lifetime_physical_storage import register_producer_path
            for leaf in ('stdout.log', 'stderr.log'):
                path = self.directory / leaf
                register_producer_path(path)
                # Nonblocking reads make deadline cleanup finite even if an
                # erroneous producer retained an inherited write handle.
                read_fd, write_fd = os.pipe()
                try:
                    os.set_blocking(read_fd, False)
                    writer = os.fdopen(write_fd, 'wb', buffering=0)
                except BaseException:
                    os.close(read_fd); os.close(write_fd)
                    raise
                self._writers.append(writer)
                try:
                    sink = path.open('xb', buffering=0)
                except BaseException:
                    os.close(read_fd)
                    raise
                self._streams.append((read_fd, sink))
            self.stdout, self.stderr = self._writers
            for index, (read_fd, sink) in enumerate(self._streams):
                thread = threading.Thread(target=self._drain,
                    args=(index, read_fd, sink), name='year-v4-log-' + str(index), daemon=True)
                thread.start()
                self._threads.append(thread)
        except BaseException:
            self.close_parent_writers()
            self._stop.set()
            for read_fd, sink in self._streams[len(self._threads):]:
                os.close(read_fd); sink.close()
            # Any started reader has a nonblocking fd and observes _stop.
            for thread in self._threads:thread.join(.1)
            raise

    def _error(self, operation, error):
        # Bound error metadata as well as the log prefix. Preserve the first
        # errors; an IO failure must not cause repeated unbounded reporting.
        with self._lock:
            if len(self._errors) < 8:
                self._errors.append(dict(operation=operation,
                    type=type(error).__name__, reason=str(error)[:512]))

    def _drain(self, index, read_fd, sink):
        writable = True
        try:
            while not self._stop.is_set():
                try:
                    data = os.read(read_fd, self.BLOCK_BYTES)
                except BlockingIOError:
                    self._stop.wait(.01)
                    continue
                if not data:break
                with self._lock:
                    self._received += len(data)
                    allowed = min(len(data), self.maximum_bytes - self._reserved) if writable else 0
                    # Reserve BEFORE the system write. Even an uncertain short
                    # or failed write cannot be followed by reusing its bytes.
                    self._reserved += allowed
                    dropped = len(data) - allowed
                    self._dropped += dropped
                    if self._received > self.maximum_bytes:self._overflow = True
                if not allowed:continue
                try:
                    amount = sink.write(data[:allowed])
                    if type(amount) is not int or amount != allowed:
                        raise OSError('short administrative log write')
                    with self._lock:self._written += amount
                except BaseException as error:
                    writable = False
                    self._error('WRITE', error)
                    # Keep reading and discarding this pipe after disk failure.
        except BaseException as error:
            self._error('READ', error)
        finally:
            try:os.close(read_fd)
            except BaseException as error:self._error('CLOSE_PIPE', error)
            try:
                sink.flush(); fsync(sink.fileno())
            except BaseException as error:self._error('SYNC', error)
            finally:
                try:sink.close()
                except BaseException as error:self._error('CLOSE_LOG', error)
            with self._lock:
                self._reader_completion[index] = time.perf_counter()

    def close_parent_writers(self):
        errors = []
        for writer in self._writers:
            if not writer.closed:
                try:writer.close()
                except BaseException as error:errors.append(error)
        for error in errors:self._error('CLOSE_PARENT_WRITER', error)

    def snapshot(self):
        with self._lock:
            return dict(format='YEAR_V4_BOUNDED_ADMINISTRATIVE_LOGS_V1',
                maximum_bytes=self.maximum_bytes, prospective_bytes_reserved=self._reserved,
                bytes_written=self._written, bytes_received=self._received,
                bytes_discarded=self._dropped, truncated=self._overflow,
                errors=list(self._errors), readers_joined=self._finished,
                reader_completion_monotonic=list(self._reader_completion),
                cleanup_deadline_monotonic=self._cleanup_deadline,
                scope='ADMINISTRATIVE_STDOUT_STDERR_ONLY_NO_SCIENTIFIC_RECORDS')

    def check(self):
        state = self.snapshot()
        if state['errors']:
            raise OSError('YEAR-V4 bounded worker log reader failure: ' + repr(state['errors']))
        if state['truncated']:
            raise ValueError('YEAR-V4 bounded worker log cap; administrative suffix discarded')
        return state

    def finish(self, cleanup_deadline):
        if type(cleanup_deadline) not in (int, float) or not math.isfinite(cleanup_deadline):
            raise ValueError('YEAR-V4 absolute cleanup deadline required')
        with self._lock:
            self._finished = False
            self._cleanup_deadline = cleanup_deadline
        self.close_parent_writers()
        for thread in self._threads:
            thread.join(max(0., cleanup_deadline - time.perf_counter()))
        unfinished = [thread for thread in self._threads if thread.is_alive()]
        with self._lock:
            completions = list(self._reader_completion)
        late = any(value is None or value > cleanup_deadline for value in completions)
        if unfinished or late:
            self._stop.set()
            self._error('JOIN_DEADLINE', TimeoutError('log readers did not close by owned cleanup deadline'))
            raise TimeoutError('YEAR-V4 log readers exceeded the same owned cleanup deadline')
        self._finished = True
        return self.check()
