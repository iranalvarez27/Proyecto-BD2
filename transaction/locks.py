import threading
import time

_COMPAT_UPGRADE = {"S", "X"}

class DeadlockError(Exception):
    def __init__(self, session_id: str, ciclo: list):
        self.session_id = session_id
        self.ciclo = ciclo
        ciclo_str = " -> ".join(ciclo)
        super().__init__(f"deadlock detectado ({ciclo_str}); victima={session_id}")


class LockTimeoutError(Exception):
    def __init__(self, session_id: str, resource: str, mode: str):
        self.session_id = session_id
        self.resource = resource
        self.mode = mode
        super().__init__(f"timeout esperando lock {mode} en '{resource}' (sesion {session_id})")


class LockManager:
    def __init__(self, timeout: float = 3.0):
        self._timeout = timeout
        self._cond = threading.Condition()
        # recurso -> {"S": {session_id, ...}, "X": session_id | None}
        self._state: dict[str, dict] = {}
        # session_id -> {recurso, ...} (para release_all)
        self._held_by_session: dict[str, set] = {}
        # (session_id, recurso) -> modo otorgado
        self._mode_by_session_resource: dict[tuple, str] = {}
        # session_id -> {session_id, ...} de quienes espera actualmente
        self._wait_for: dict[str, set] = {}
        # historia de adquisiciones exitosas: (session_id, recurso, modo, ts)
        self.historia: list[tuple] = []

    # estado

    def _resource_state(self, resource: str) -> dict:
        return self._state.setdefault(resource, {"S": set(), "X": None})

    def _current_mode(self, session_id: str, resource: str):
        return self._mode_by_session_resource.get((session_id, resource))

    def _can_grant(self, session_id: str, resource: str, mode: str) -> bool:
        st = self._resource_state(resource)
        if mode == "S":
            return st["X"] is None or st["X"] == session_id
        # mode == "X"
        if st["X"] is not None and st["X"] != session_id:
            return False
        otros_lectores = st["S"] - {session_id}
        return len(otros_lectores) == 0

    def _grant(self, session_id: str, resource: str, mode: str) -> None:
        st = self._resource_state(resource)
        anterior = self._current_mode(session_id, resource)
        if anterior == "S" and mode == "X":
            st["S"].discard(session_id)
        if mode == "X":
            st["X"] = session_id
        else:
            st["S"].add(session_id)
        self._mode_by_session_resource[(session_id, resource)] = mode
        self._held_by_session.setdefault(session_id, set()).add(resource)

    # wait-for

    def _update_wait_for(self, session_id: str, resource: str, mode: str) -> None:
        st = self._resource_state(resource)
        bloqueadores = set()
        if st["X"] is not None and st["X"] != session_id:
            bloqueadores.add(st["X"])
        if mode == "X":
            bloqueadores |= (st["S"] - {session_id})
        if bloqueadores:
            self._wait_for[session_id] = bloqueadores
        else:
            self._wait_for.pop(session_id, None)

    def _clear_wait(self, session_id: str) -> None:
        self._wait_for.pop(session_id, None)

    def _find_cycle(self, start: str):
        stack = [start]
        visitados_en_rama = {start}

        def dfs(nodo, camino):
            for vecino in self._wait_for.get(nodo, ()):
                if vecino == start:
                    return camino + [vecino]
                if vecino in visitados_en_rama:
                    continue
                visitados_en_rama.add(vecino)
                resultado = dfs(vecino, camino + [vecino])
                if resultado is not None:
                    return resultado
            return None

        return dfs(start, stack)

    # publico

    def acquire(self, session_id: str, resource: str, mode: str) -> None:
        if mode not in ("S", "X"):
            raise ValueError(f"modo de lock invalido: {mode}")
        deadline = time.time() + self._timeout
        with self._cond:
            actual = self._current_mode(session_id, resource)
            if actual == "X":
                return
            if actual == "S" and mode == "S":
                return

            while not self._can_grant(session_id, resource, mode):
                self._update_wait_for(session_id, resource, mode)
                ciclo = self._find_cycle(session_id)
                if ciclo is not None:
                    self._clear_wait(session_id)
                    raise DeadlockError(session_id, ciclo)

                restante = deadline - time.time()
                if restante <= 0:
                    self._clear_wait(session_id)
                    raise LockTimeoutError(session_id, resource, mode)

                self._cond.wait(min(restante, 0.2))

            self._clear_wait(session_id)
            self._grant(session_id, resource, mode)
            self.historia.append((session_id, resource, mode, time.time()))
            self._cond.notify_all()

    def release_resource(self, session_id: str, resource: str) -> None:
        with self._cond:
            st = self._resource_state(resource)
            st["S"].discard(session_id)
            if st["X"] == session_id:
                st["X"] = None
            self._mode_by_session_resource.pop((session_id, resource), None)
            held = self._held_by_session.get(session_id)
            if held is not None:
                held.discard(resource)
            self._cond.notify_all()

    def release_all(self, session_id: str) -> None:
        with self._cond:
            recursos = self._held_by_session.pop(session_id, set())
            for resource in recursos:
                st = self._resource_state(resource)
                st["S"].discard(session_id)
                if st["X"] == session_id:
                    st["X"] = None
                self._mode_by_session_resource.pop((session_id, resource), None)
            self._clear_wait(session_id)
            self._cond.notify_all()

    def held_resources(self, session_id: str) -> set:
        with self._cond:
            return set(self._held_by_session.get(session_id, set()))

    def snapshot_estado(self) -> dict:
        with self._cond:
            return {
                recurso: {"S": set(st["S"]), "X": st["X"]}
                for recurso, st in self._state.items()
            }
