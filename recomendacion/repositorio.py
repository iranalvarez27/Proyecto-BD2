"""Acceso SQL al motor, con trazas y sesiones independientes."""
from contextlib import contextmanager
import time
import uuid


def literal(valor):
    if isinstance(valor, str):
        return "'" + valor.replace("'", "''") + "'"
    if isinstance(valor, (int, float)):
        return str(valor)
    raise ValueError('Tipo de literal SQL no admitido')


class Repositorio:
    def __init__(self, conexion, session_id=None):
        self.conexion = conexion
        self.session_id = session_id or str(uuid.uuid4())
        self.trazas = []

    def ejecutar(self, sql):
        inicio = time.perf_counter()
        resultado = self.conexion.execute(sql, self.session_id)
        self.trazas.append({'sql': sql, 'plan': resultado.plan or [],
                            'tiempo_ms': round((time.perf_counter() - inicio) * 1000, 3)})
        if not resultado.ok:
            raise ValueError(resultado.error)
        return resultado.filas or []

    @contextmanager
    def transaccion(self, tablas):
        self.ejecutar('BEGIN TRANSACTION')
        try:
            # Tomar X antes de leer evita conversiones simultáneas S -> X.
            for tabla in sorted(tablas):
                self.conexion.lock_manager.acquire(self.session_id, tabla, 'X')
            yield self
            self.ejecutar('COMMIT')
        except Exception:
            if self.conexion.txn_manager.is_active(self.session_id):
                self.ejecutar('ROLLBACK')
            raise

    def insertar(self, tabla, valores):
        return self.ejecutar(f"INSERT INTO {tabla} VALUES ({', '.join(literal(v) for v in valores)})")
