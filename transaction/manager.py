import os
import threading
import time

from common.page import PAGE_SIZE
from transaction.locks import LockManager, DeadlockError, LockTimeoutError


class TransactionError(Exception):
    pass


class Transaction:
    __slots__ = ("xact_id", "session_id", "undo_buffer", "active", "start_time", "operaciones")

    def __init__(self, xact_id: str, session_id: str):
        self.xact_id = xact_id
        self.session_id = session_id
        self.undo_buffer: list = []  # (path, page_id, op, before)
        self.active = True
        self.start_time = time.time()
        self.operaciones = 0


def _no_op_hook(op: str, path: str, page_id, before) -> None:
    return None


# Hook global inyectable: los storages/indices lo llaman por atributo de
# modulo (`from transaction import manager as tx_manager; tx_manager.TX_HOOK(...)`)
# para que siempre vean el valor vigente, no el que existia al importar.
TX_HOOK = _no_op_hook


class _BindContext:
    __slots__ = ("_manager", "_session_id", "_previo")

    def __init__(self, manager: "TransactionManager", session_id: str):
        self._manager = manager
        self._session_id = session_id
        self._previo = None

    def __enter__(self):
        self._previo = getattr(self._manager._local, "txn", None)
        self._manager._local.txn = self._manager.get_active(self._session_id)
        return self

    def __exit__(self, exc_type, exc, tb):
        self._manager._local.txn = self._previo
        return False


class TransactionManager:
    def __init__(self, lock_manager: LockManager | None = None, timeout: float = 3.0):
        self.lock_manager = lock_manager or LockManager(timeout=timeout)
        self._sessions: dict[str, Transaction] = {}
        self._lock = threading.RLock()
        self._next_id = 1000
        self._local = threading.local()
        self.historia: list[tuple] = []  # (xact_id, recurso, modo, ts)

        global TX_HOOK
        TX_HOOK = self._tx_hook

    # --------------------------------------------------------------- ciclo

    def _nuevo_xact_id(self) -> str:
        with self._lock:
            self._next_id += 1
            return f"T{self._next_id}"

    def begin(self, session_id: str) -> Transaction:
        with self._lock:
            existente = self._sessions.get(session_id)
            if existente is not None and existente.active:
                raise TransactionError(
                    f"la sesion '{session_id}' ya tiene una transaccion activa ({existente.xact_id})"
                )
            txn = Transaction(self._nuevo_xact_id(), session_id)
            self._sessions[session_id] = txn
            return txn

    def is_active(self, session_id: str) -> bool:
        with self._lock:
            txn = self._sessions.get(session_id)
            return txn is not None and txn.active

    def get_active(self, session_id: str) -> Transaction | None:
        with self._lock:
            txn = self._sessions.get(session_id)
            if txn is not None and txn.active:
                return txn
            return None

    def bind_current(self, session_id: str) -> _BindContext:
        return _BindContext(self, session_id)

    def _current_txn(self) -> Transaction | None:
        return getattr(self._local, "txn", None)

    # -------------------------------------------------------- undo en RAM

    def _tx_hook(self, op: str, path: str, page_id, before) -> None:
        txn = self._current_txn()
        if txn is None or not txn.active:
            return
        txn.undo_buffer.append((path, page_id, op, before))

    def register_snapshot(self, path: str, content: bytes) -> None:
        self._tx_hook("SNAPSHOT", path, None, content)

    def register_truncate(self, path: str, before_length: int) -> None:
        self._tx_hook("TRUNCATE", path, None, before_length)

    def registrar_acceso(self, session_id: str, recurso: str, modo: str) -> None:
        txn = self.get_active(session_id)
        xact_id = txn.xact_id if txn is not None else f"AUTO-{session_id}-{time.time_ns()}"
        if txn is not None:
            txn.operaciones += 1
        entrada = (xact_id, recurso, modo, time.time())
        with self._lock:
            self.historia.append(entrada)

    # ------------------------------------------------------------ commit

    def commit(self, session_id: str) -> Transaction:
        with self._lock:
            txn = self._sessions.get(session_id)
            if txn is None or not txn.active:
                raise TransactionError(f"no hay transaccion activa en la sesion '{session_id}'")
            txn.active = False
        self.lock_manager.release_all(session_id)
        txn.undo_buffer.clear()
        return txn

    def rollback(self, session_id: str) -> Transaction:
        with self._lock:
            txn = self._sessions.get(session_id)
            if txn is None or not txn.active:
                raise TransactionError(f"no hay transaccion activa en la sesion '{session_id}'")
            txn.active = False
        self._deshacer(txn)
        self.lock_manager.release_all(session_id)
        return txn

    def abortar_por_deadlock_o_timeout(self, session_id: str) -> Transaction | None:
        with self._lock:
            txn = self._sessions.get(session_id)
            if txn is None or not txn.active:
                return None
        return self.rollback(session_id)

    def _deshacer(self, txn: Transaction) -> None:
        for path, page_id, op, before in reversed(txn.undo_buffer):
            if op == "WRITE":
                with open(path, "r+b") as f:
                    f.seek(page_id * PAGE_SIZE)
                    f.write(before)
            elif op == "APPEND":
                # antes de este append el archivo tenia exactamente page_id paginas
                with open(path, "r+b") as f:
                    f.truncate(page_id * PAGE_SIZE)
            elif op == "SNAPSHOT":
                with open(path, "wb") as f:
                    f.write(before)
            elif op == "TRUNCATE":
                pass  # el SNAPSHOT correspondiente ya restauro el archivo completo
        txn.undo_buffer.clear()
