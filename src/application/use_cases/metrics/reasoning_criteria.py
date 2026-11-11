"""The default criteria the LLM-judge applies to an alert's reasoning.

Two are judged per reasoning step and feed the rollup rates ("Alucinaciones",
"Uso correcto de datos"); the explainability ones are judged once per alert and
kept with the verdict (visible per alert, not part of the rollups). Adding or
rewording a criterion changes the judge prompt: bump ``PROMPT_VERSION`` in
``evaluate_alert_reasoning``."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReasoningCriterion:
    key: str
    label: str
    question: str
    # "step": one verdict per reasoning step; "alert": one for the whole alert.
    scope: str
    # True when the criterion can be undecidable (e.g. no model output to compare).
    optional: bool = False
    counts_in_rollups: bool = False


DEFAULT_CRITERIA: tuple[ReasoningCriterion, ...] = (
    ReasoningCriterion(
        key="hallucination",
        label="Alucinación",
        question=(
            "¿Algún paso afirma un hecho, cifra o resultado que no está en la "
            "evidencia que ese paso tenía?"
        ),
        scope="step",
        counts_in_rollups=True,
    ),
    ReasoningCriterion(
        key="data_use_correct",
        label="Uso correcto de datos",
        question=(
            "¿El paso leyó e interpretó bien los datos que cita y no ignoró "
            "evidencia decisiva en contra de su conclusión?"
        ),
        scope="step",
        counts_in_rollups=True,
    ),
    ReasoningCriterion(
        key="clarity",
        label="Claridad",
        question=(
            "¿La explicación final dice qué se decidió, por qué y con qué datos, "
            "en un lenguaje que un analista entiende sin ver el prompt?"
        ),
        scope="alert",
    ),
    ReasoningCriterion(
        key="step_consistency",
        label="Coherencia entre pasos",
        question=(
            "¿Las conclusiones de los pasos son coherentes entre sí, o las "
            "contradicciones están explicadas?"
        ),
        scope="alert",
    ),
    ReasoningCriterion(
        key="evidence_citation",
        label="Cita de evidencia",
        question=(
            "¿Las afirmaciones clave citan datos concretos (campos y valores) de "
            "la evidencia, en vez de generalidades?"
        ),
        scope="alert",
    ),
    ReasoningCriterion(
        key="model_alignment",
        label="Consistencia con el modelo",
        question=(
            "¿La conclusión es coherente con la salida del modelo XGBoost, o "
            "explica por qué se aparta de ella? (sin respuesta si no hubo modelo)"
        ),
        scope="alert",
        optional=True,
    ),
)

ALERT_CRITERIA: tuple[ReasoningCriterion, ...] = tuple(
    c for c in DEFAULT_CRITERIA if c.scope == "alert"
)
