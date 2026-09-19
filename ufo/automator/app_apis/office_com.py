"""
Shared COM plumbing for the Word / Excel / PowerPoint MCP servers.

- Every COM call for an app runs on one dedicated single-threaded-apartment
  thread (COM objects must not hop threads).
- Attaches to the user's running instance (GetActiveObject) before starting
  one (Dispatch), and re-resolves the target document on every call, so a
  document opened/closed/switched since the last call is handled.
- A call that exceeds the timeout returns an error; the Office process is
  never killed (it may hold the user's unsaved work — usually it is just
  showing a modal dialog). The stuck worker is abandoned and replaced.
"""
import logging
import queue
import threading
from concurrent.futures import Future
from typing import Any, Callable, Optional, Type

logger = logging.getLogger(__name__)


class OfficeComError(RuntimeError):
    pass


class _StaWorker:
    def __init__(self, name: str) -> None:
        self._jobs: "queue.Queue[tuple]" = queue.Queue()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self.app = None
        self._thread.start()

    def _run(self) -> None:
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except ImportError:
            pythoncom = None
        try:
            while True:
                fn, fut = self._jobs.get()
                if fn is None:
                    return
                if fut.set_running_or_notify_cancel():
                    try:
                        fut.set_result(fn(self))
                    except BaseException as e:  # noqa: BLE001 - surfaced to caller
                        fut.set_exception(e)
        finally:
            self.app = None
            if pythoncom is not None:
                pythoncom.CoUninitialize()

    def submit(self, fn: Callable[["_StaWorker"], Any]) -> Future:
        fut: Future = Future()
        self._jobs.put((fn, fut))
        return fut

    def stop(self) -> None:
        self._jobs.put((None, None))


class OfficeComSession:
    """Runs receiver methods for one Office app on a dedicated STA thread."""

    def __init__(self, progid: str, receiver_cls: Type, app_root_name: str, process_name: str = "", timeout: float = 30.0,
                 attach: Optional[Callable[[str], Any]] = None) -> None:
        self.progid = progid
        self._attach_fn = attach or self._attach
        self.receiver_cls = receiver_cls
        self.app_root_name = app_root_name
        self.process_name = process_name or ""
        self.timeout = timeout
        self._worker: Optional[_StaWorker] = None
        self._lock = threading.Lock()

    def _get_worker(self) -> _StaWorker:
        with self._lock:
            if self._worker is None:
                self._worker = _StaWorker(f"com-{self.app_root_name}")
            return self._worker

    @staticmethod
    def _attach(progid: str):
        import win32com.client
        try:
            return win32com.client.GetActiveObject(progid)
        except Exception:
            return win32com.client.Dispatch(progid)

    def _receiver(self, worker: _StaWorker):
        if worker.app is None:
            worker.app = self._attach_fn(self.progid)
        receiver = self.receiver_cls.__new__(self.receiver_cls)
        receiver.app_root_name = self.app_root_name
        receiver.process_name = self.process_name
        receiver.clsid = self.progid
        receiver.client = worker.app
        try:
            receiver.com_object = receiver.get_object_from_process_name()
        except Exception:
            # The cached application proxy died (Office was closed/restarted).
            worker.app = self._attach_fn(self.progid)
            receiver.client = worker.app
            receiver.com_object = receiver.get_object_from_process_name()
        if receiver.com_object is None:
            raise OfficeComError(f"No open {self.app_root_name} document matches '{self.process_name}'.")
        return receiver

    def close(self, quit_app: bool = False) -> None:
        """Release this session's COM references (optionally quitting the app first).

        Office keeps running while any COM reference is alive, so a Quit only
        takes effect once the worker thread has dropped its proxies.
        """
        with self._lock:
            worker, self._worker = self._worker, None
        if worker is None:
            return
        if quit_app:
            def _quit(w):
                if w.app is not None:
                    w.app.Quit()
                w.app = None
            try:
                worker.submit(_quit).result(timeout=self.timeout)
            except Exception as e:
                logger.warning(f'{self.app_root_name}: Quit failed: {e}')
        worker.stop()
        worker._thread.join(timeout=10)

    def call(self, fn: Callable[[Any], Any]) -> Any:
        """Run fn(receiver) on the STA thread and return its result."""
        worker = self._get_worker()
        fut = worker.submit(lambda w: fn(self._receiver(w)))
        try:
            return fut.result(timeout=self.timeout)
        except TimeoutError:
            fut.cancel()
            with self._lock:
                if self._worker is worker:
                    self._worker = None  # abandon the stuck thread; next call gets a fresh one
            raise OfficeComError(
                f"{self.app_root_name} did not respond within {self.timeout:.0f}s "
                "(it may be showing a dialog). The application was left running."
            )
