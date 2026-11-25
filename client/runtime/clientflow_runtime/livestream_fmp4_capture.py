"""Capture-side bounded fMP4 handoff; never opens network connections.

The encoded queue may discard buffers only when overloaded. That invalidates
the entire fMP4 branch permanently for this capture; never publish after a
known gap. The original HLS branch remains responsible for video availability.
"""
from pathlib import Path
import threading
import time

if __package__:
    from .livestream_fmp4 import BoxAssembler, FILENAME, MAX_FRAGMENT, publish_latest, wire_pair
else:
    from livestream_fmp4 import BoxAssembler, FILENAME, MAX_FRAGMENT, publish_latest, wire_pair


class FragmentHandoff:
    def __init__(self, gst, pipeline, output: Path):
        self.gst = gst
        self.output = output
        self.queue = pipeline.get_by_name("cf_mp4_queue")
        self.valve = pipeline.get_by_name("cf_mp4_valve")
        self.sink = pipeline.get_by_name("cf_mp4_sink")
        if any(element is None for element in (self.queue, self.valve, self.sink)):
            raise RuntimeError("Incomplete continuous branch")
        self.stop = threading.Event()
        self.failed = threading.Event()
        self.thread = threading.Thread(target=self._run, name="cf-fmp4-handoff", daemon=True)
        self.signal = self.queue.connect("overrun", self._overrun)

    def _overrun(self, *_args):
        # No filesystem/network operation from the streaming thread.
        self.failed.set()
        self.valve.set_property("drop", True)

    def start(self):
        self.thread.start()

    def _run(self):
        assembler = BoxAssembler()
        sequence = 0
        started = time.monotonic_ns()
        last = 0
        try:
            while not self.stop.is_set() and not self.failed.is_set():
                sample = self.sink.emit("try-pull-sample", 100 * self.gst.MSECOND)
                if sample is None:
                    self.stop.wait(0.02)
                    continue
                buf = sample.get_buffer()
                size = buf.get_size()
                if not 0 < size <= MAX_FRAGMENT:
                    raise ValueError("oversized mux sample")
                for fragment in assembler.feed(buf.extract_dup(0, size)):
                    if self.stop.is_set() or self.failed.is_set():
                        break
                    sequence += 1
                    last = max(last + 1, (time.monotonic_ns() - started) // 1000)
                    publish_latest(self.output, wire_pair(assembler.init, fragment, sequence, last))
        except Exception:
            self.failed.set()
        finally:
            self.valve.set_property("drop", True)
            (self.output / FILENAME).unlink(missing_ok=True)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)
        self.queue.disconnect(self.signal)
        if self.thread.is_alive():
            raise RuntimeError("fMP4 handoff did not stop")
