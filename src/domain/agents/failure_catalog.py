"""Human-readable catalogue of optimizer failures and blocks.

Every failure code the optimizer can surface maps to a Spanish explanation,
whether a retry can help and who has to act. Failures are never
self-managed: when the agent lacks context or exhausts a limit it stops in a
blocked state and the Channel Manager decides whether to grant more.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentFailure:
    code: str
    title: str
    detail: str
    action: str
    retryable: bool = False
    # What the Channel Manager can grant to unblock the session, if anything.
    approval: str | None = None  # "budget" | "candidates" | "context"


def _failure(
    code: str,
    title: str,
    detail: str,
    action: str,
    *,
    retryable: bool = False,
    approval: str | None = None,
) -> AgentFailure:
    return AgentFailure(code, title, detail, action, retryable, approval)


_ENTRIES = (
    # Blocks that wait for the Channel Manager.
    _failure(
        "BUDGET_EXHAUSTED",
        "Presupuesto agotado",
        "La sesión consumió el presupuesto autorizado.",
        "Aprueba más presupuesto para que continúe.",
        approval="budget",
    ),
    _failure(
        "CANDIDATE_LIMIT_REACHED",
        "Límite de propuestas alcanzado",
        "El agente llegó al máximo de iteraciones o propuestas por sesión.",
        "Aprueba más iteraciones para que continúe.",
        approval="candidates",
    ),
    _failure(
        "CONTEXT_MISSING",
        "Falta contexto",
        "No hay hipótesis ni señal suficiente para decidir el siguiente experimento.",
        "Entrega contexto (una pista, restricción o hipótesis) para que continúe.",
        approval="context",
    ),
    _failure(
        "STAGNATION",
        "Sin mejora sostenida",
        "Varias iteraciones seguidas no mejoraron el objetivo.",
        "Revisa la evidencia; puedes aprobar más iteraciones o dar nuevo contexto.",
        approval="candidates",
    ),
    _failure(
        "COST_ANOMALY",
        "Costo anómalo en una iteración",
        "La última iteración costó mucho más que lo habitual en esta sesión.",
        "Revisa el gasto; si es esperado, aprueba más iteraciones para continuar.",
        approval="candidates",
    ),
    _failure(
        "CRITICAL_FAILURE",
        "Falla crítica de un especialista",
        "Un especialista falló y la política detiene la sesión.",
        "Revisa el error del especialista; puedes reintentar con más iteraciones.",
        approval="candidates",
    ),
    # Infrastructure failures: the system can retry, nobody has to approve.
    _failure(
        "WORKER_LEASE_EXPIRED",
        "El worker dejó de responder",
        "La ejecución se interrumpió antes de terminar; el trabajo abierto se cerró.",
        "Reanuda la sesión; el sistema la reintenta automáticamente.",
        retryable=True,
    ),
    _failure(
        "LEASE_EXPIRED",
        "Reserva de ejecución vencida",
        "Otra ejecución tomó el control de la sesión.",
        "No requiere acción.",
        retryable=True,
    ),
    _failure(
        "DISPATCH_FAILED",
        "No se pudo despachar la tarea",
        "La cola no aceptó el trabajo del especialista.",
        "Reintenta; si persiste, avisa al equipo técnico.",
        retryable=True,
    ),
    _failure(
        "EVALUATION_FAILED",
        "Falló la evaluación",
        "La evaluación del experimento no terminó.",
        "Reintenta la iteración.",
        retryable=True,
    ),
    _failure(
        "GLOBAL_EVALUATION_FAILED",
        "Falló la evaluación global",
        "No se pudo calcular el objetivo global sobre la muestra final.",
        "Verifica la muestra madura y reintenta.",
        retryable=True,
    ),
    _failure(
        "PIPELINE_REPLAY_WORKFLOW_FAILED",
        "Falló la reproducción del pipeline",
        "Una o más alertas no completaron el flujo real durante el experimento.",
        "Revisa los workers de revisión y reintenta con una muestra menor.",
        retryable=True,
    ),
    _failure(
        "RUN_CANCELLED",
        "Ejecución cancelada",
        "La sesión fue cancelada mientras el especialista trabajaba.",
        "No requiere acción.",
    ),
    _failure(
        "EXECUTION_FAILED",
        "Falló la ejecución del especialista",
        "El especialista terminó con un error.",
        "Reintenta la iteración.",
        retryable=True,
    ),
    _failure(
        "EXECUTION_INVALID",
        "Resultado inválido del especialista",
        "El resultado no cumple el contrato esperado.",
        "Reintenta la iteración.",
        retryable=True,
    ),
    _failure(
        "GENERATION_FAILED",
        "Falló la generación",
        "El modelo de lenguaje no produjo una propuesta.",
        "Reintenta la iteración.",
        retryable=True,
    ),
    _failure(
        "GENERATION_INVALID",
        "Propuesta generada inválida",
        "La propuesta no cumple el formato requerido.",
        "Reintenta la iteración.",
        retryable=True,
    ),
    _failure(
        "CONTEXT_UNAVAILABLE",
        "Contexto no disponible",
        "No se pudo cargar el contexto de la sesión.",
        "Reintenta; si persiste, avisa al equipo técnico.",
        retryable=True,
    ),
    _failure(
        "PROMPT_NOT_PINNED",
        "Prompt sin versión fijada",
        "La sesión no tiene una versión de prompt fijada.",
        "Crea una sesión nueva.",
    ),
    _failure(
        "PROMPT_UNAVAILABLE",
        "Prompt no disponible",
        "La versión fijada del prompt ya no existe.",
        "Crea una sesión nueva.",
    ),
    _failure(
        "PROMPT_VERSION_MISMATCH",
        "Versión de prompt distinta",
        "La versión del prompt cambió durante la sesión.",
        "Crea una sesión nueva.",
    ),
    _failure(
        "CONFIGURATION_CHANGES_REQUIRED",
        "Sin cambios de configuración",
        "El especialista no propuso ningún cambio de configuración.",
        "Da contexto más específico.",
        approval="context",
    ),
    _failure(
        "ACTIVE_CONFIGURATION_REQUIRED",
        "Falta una configuración activa",
        "No hay configuración activa como línea base.",
        "Activa una configuración y reintenta.",
    ),
    _failure(
        "CONFIGURATION_PATH_OR_VALUE_INVALID",
        "Cambio de configuración inválido",
        "Una ruta o valor propuesto no existe en la configuración.",
        "Reintenta la iteración.",
        retryable=True,
    ),
    _failure(
        "CONFIGURATION_CANDIDATE_REJECTED",
        "Configuración candidata rechazada",
        "La configuración propuesta no pasó las validaciones.",
        "Reintenta la iteración.",
        retryable=True,
    ),
    _failure(
        "LIBRARY_DRAFT_INVALID",
        "Borrador de Biblioteca inválido",
        "El borrador de Biblioteca no cumple el esquema.",
        "Reintenta la iteración.",
        retryable=True,
    ),
    _failure(
        "PERSONAL_DATA_BLOCKED",
        "Datos personales bloqueados",
        "La propuesta contenía datos personales y fue bloqueada.",
        "Revisa el contexto entregado.",
    ),
    _failure(
        "LIBRARY_REFERENCE_INVALID",
        "Referencia de Biblioteca inválida",
        "La propuesta apunta a una entidad que no existe.",
        "Reintenta la iteración.",
        retryable=True,
    ),
    _failure(
        "LIBRARY_DUPLICATE",
        "Entidad duplicada",
        "La propuesta duplica una entidad existente de la Biblioteca.",
        "Da contexto distinto.",
        approval="context",
    ),
    _failure(
        "PLAYBOOK_FALLBACK_INVALID",
        "Alternativa de playbook inválida",
        "El playbook propuesto no incluye alternativas válidas.",
        "Reintenta la iteración.",
        retryable=True,
    ),
    _failure(
        "VECTOR_QUERY_NOT_AUTHORIZED",
        "Consulta vectorial no autorizada",
        "La consulta al Vector Store no está autorizada para esta sesión.",
        "Revisa los permisos del Vector Store.",
    ),
    _failure(
        "VECTOR_MANIFEST_UNAVAILABLE",
        "Manifiesto vectorial no disponible",
        "No se encontró el manifiesto del Vector Store.",
        "Construye el Vector Store y reintenta.",
    ),
    _failure(
        "VECTOR_MANIFEST_EMPTY",
        "Manifiesto vectorial vacío",
        "El Vector Store no tiene documentos.",
        "Carga documentos y reintenta.",
    ),
    _failure(
        "VECTOR_CANDIDATE_BUILD_FAILED",
        "Falló la construcción del Vector Store candidato",
        "No se pudo construir el índice candidato.",
        "Reintenta la iteración.",
        retryable=True,
    ),
    _failure(
        "VECTOR_CANDIDATE_VERIFICATION_FAILED",
        "Vector Store candidato no verificado",
        "El índice candidato no pasó la verificación.",
        "Reintenta la iteración.",
        retryable=True,
    ),
    _failure(
        "AUTHORIZED_MODEL_BASELINE_REQUIRED",
        "Falta un modelo base autorizado",
        "No hay un modelo autorizado como línea base.",
        "Autoriza un modelo y reintenta.",
    ),
    _failure(
        "TRAINING_PARAMETER_NOT_SUPPORTED",
        "Parámetro de entrenamiento no soportado",
        "El especialista propuso un parámetro que el entrenamiento no admite.",
        "Reintenta la iteración.",
        retryable=True,
    ),
    _failure(
        "MODEL_CANDIDATE_LOST",
        "Se perdió el modelo candidato",
        "El entrenamiento terminó pero el candidato no está disponible.",
        "Reintenta la iteración.",
        retryable=True,
    ),
    _failure(
        "MODEL_TRAINING_FAILED",
        "Falló el entrenamiento",
        "El entrenamiento del modelo candidato terminó con error.",
        "Reintenta la iteración.",
        retryable=True,
    ),
    _failure(
        "MODEL_CANDIDATE_START_FAILED",
        "No inició el entrenamiento",
        "No se pudo lanzar el entrenamiento del candidato.",
        "Reintenta la iteración.",
        retryable=True,
    ),
    _failure(
        "MODEL_TRAINING_BUDGET_INVALID",
        "Presupuesto de entrenamiento inválido",
        "El presupuesto asignado al entrenamiento no es válido.",
        "Aprueba más presupuesto.",
        approval="budget",
    ),
    _failure(
        "MODEL_REPORT_INCOMPLETE",
        "Reporte del modelo incompleto",
        "El entrenamiento no devolvió todas las métricas.",
        "Reintenta la iteración.",
        retryable=True,
    ),
    _failure(
        "SPECIALIST_FAILED",
        "Falló un especialista",
        "Un especialista terminó con un error no clasificado.",
        "Reintenta; si persiste, avisa al equipo técnico.",
        retryable=True,
    ),
)

CATALOG: dict[str, AgentFailure] = {entry.code: entry for entry in _ENTRIES}

UNKNOWN_FAILURE = AgentFailure(
    code="UNKNOWN_FAILURE",
    title="Falla no clasificada",
    detail="El agente terminó con un error que no está en el catálogo.",
    action="Avisa al equipo técnico.",
    retryable=False,
)


def describe_failure(code: str | None) -> AgentFailure:
    """Return the catalogue entry; unknown codes never leak their raw text."""
    if code is None:
        return UNKNOWN_FAILURE
    return CATALOG.get(code, UNKNOWN_FAILURE)
