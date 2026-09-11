from __future__ import annotations

import re
import uuid as uuid_module
from collections import Counter
from io import BytesIO
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

from src.application.ports.async_operation_port import AsyncOperationStatus
from src.application.ports.model_port import (
    FieldTransform,
    FieldTransformKind,
    ModelStatus,
    HistoricalFeature,
)

from src.infrastructure.workflows.celery.historical_features import build_history_frame

SEED = 42

# Fixed hyperparameters, ported as-is from the newArquitecture+XGboost branch's
# experiments/experimento_1_xgboost/run_experimento_1.py::make_xgb - shallow
# trees + low learning rate + regularization make the model essentially
# additive (a logistic regression over the same features matches its
# accuracy in that experiment), which is why per-case SHAP contributions
# are trustworthy as an explanation, not just a black-box gesture.
XGB_PARAMS: dict[str, Any] = dict(
    n_estimators=400,
    max_depth=4,
    learning_rate=0.03,
    subsample=0.8,
    colsample_bytree=0.8,
    reg_lambda=1.0,
    min_child_weight=3,
    enable_categorical=True,
    tree_method="hist",
    eval_metric="logloss",
    random_state=SEED,
    n_jobs=-1,
)

_TOKEN_SPLIT_RE = re.compile(r"[\[\]]")


def _tokenize(raw: Any) -> set[str]:
    """'[CUSTOMER - dg_risknewpayee, CARD - TJ_x]' -> {'dg_risknewpayee','TJ_x'}."""
    if not raw:
        return set()
    inner = _TOKEN_SPLIT_RE.sub("", str(raw)).strip()
    tokens = set()
    for part in inner.split(","):
        part = part.strip()
        if not part:
            continue
        tokens.add(re.sub(r"^[A-Z]+\s*-\s*", "", part).strip())
    return tokens


def _parse_date(value: Any) -> pd.Timestamp | None:
    if value is None or value == "":
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed


def _field_value(row: dict[str, Any], path: str) -> Any:
    """Read either an exact flat key or a dotted path from a dataset row."""
    if path in row:
        return row[path]
    value: Any = row
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def build_feature_frame(
    rows: list[dict[str, Any]],
    transforms: list[FieldTransform],
    rule_vocab: dict[str, list[str]] | None = None,
    historical_features: list[HistoricalFeature] | None = None,
    timezone: str = "UTC",
    feature_configuration: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """Applies each FieldTransform to produce the training/scoring feature
    matrix. Generalizes the branch's hardcoded `construir_features` into a
    field/kind-driven engine so the transformation choices come from the UI,
    not from a fixed column list in code.

    `rule_vocab` (field -> top tokens) is None at train time (it gets fit
    here and returned) and passed in at scoring time (fixed, from the
    persisted bundle).
    """
    requested_fields = {
        transform.field for transform in transforms
    } | {
        transform.reference_field
        for transform in transforms
        if transform.reference_field
    }
    df = pd.DataFrame(
        {
            field: [_field_value(row, field) for row in rows]
            for field in requested_fields
        }
    )
    feats = pd.DataFrame(index=range(len(rows)))
    fitted_vocab: dict[str, list[str]] = dict(rule_vocab or {})

    for transform in transforms:
        col = transform.field
        if col not in df.columns:
            continue
        if transform.kind == FieldTransformKind.DROP:
            continue
        if transform.kind == FieldTransformKind.NUMERIC:
            feats[col] = pd.to_numeric(df[col], errors="coerce")
        elif transform.kind == FieldTransformKind.CATEGORICAL:
            feats[col] = (
                df[col].fillna("").astype(str).replace("", "NA").astype("category")
            )
        elif transform.kind == FieldTransformKind.DATE_DERIVED:
            parsed = df[col].map(_parse_date)
            feats[f"{col}__hour"] = parsed.map(
                lambda d: d.hour if d is not None else np.nan
            )
            feats[f"{col}__dayofweek"] = parsed.map(
                lambda d: d.dayofweek if d is not None else np.nan
            )
            feats[f"{col}__month"] = parsed.map(
                lambda d: d.month if d is not None else np.nan
            )
            if transform.reference_field and transform.reference_field in df.columns:
                ref_parsed = df[transform.reference_field].map(_parse_date)
                feats[f"{col}__days_since_{transform.reference_field}"] = [
                    (a - b).days if a is not None and b is not None else np.nan
                    for a, b in zip(parsed, ref_parsed)
                ]
        elif transform.kind == FieldTransformKind.RULE_MULTIHOT:
            token_sets = df[col].map(_tokenize)
            vocab = fitted_vocab.get(col)
            if vocab is None:
                vocab = [
                    token
                    for token, _ in Counter(
                        t for tokens in token_sets for t in tokens
                    ).most_common(transform.top_n)
                ]
                fitted_vocab[col] = vocab
            for token in vocab:
                feats[f"{col}__{token}"[:60]] = token_sets.map(
                    lambda s, t=token: int(t in s)
                )
            feats[f"{col}__n_tokens"] = token_sets.map(len)

    feats = pd.concat([feats.reset_index(drop=True), build_history_frame(rows, historical_features or [], timezone)], axis=1)
    if feature_configuration is not None:
        from src.domain.models.feature_recipe import evaluate_feature_definition, validate_feature_definition

        definition = validate_feature_definition(feature_configuration)
        evaluated = []
        for index, row in enumerate(rows):
            result = evaluate_feature_definition(definition, row, validated=True)
            errors = [feature for feature in result["features"] if feature["status"] == "error"]
            if errors:
                raise ValueError(f"Fila {index + 1}, característica {errors[0]['name']}: {errors[0].get('error')}")
            evaluated.append(result["values"])
        recipe_frame = pd.DataFrame(index=range(len(rows)))
        for recipe in definition["recipes"]:
            if not recipe.get("enabled", True):
                continue
            name = recipe["name"]
            values = pd.Series([result.get(name) for result in evaluated], index=recipe_frame.index, dtype=object)
            if recipe.get("output_type", "number") == "string":
                recipe_frame[name] = values.map(lambda value: str(value) if value is not None else np.nan).astype("category")
            else:
                recipe_frame[name] = pd.to_numeric(values, errors="coerce").astype(float)
        feats = pd.concat([feats, recipe_frame], axis=1)
    if feats.columns.duplicated().any():
        raise ValueError("Las transformaciones generan nombres de columnas duplicados")
    return feats, fitted_vocab


def train_xgboost_model(
    X: pd.DataFrame, y: np.ndarray, test_size: float = 0.25
) -> tuple[XGBClassifier, IsotonicRegression, dict[str, float]]:
    X_train, X_cal, y_train, y_cal = train_test_split(
        X, y, test_size=test_size, stratify=y, random_state=SEED
    )
    n_pos = int(y_train.sum())
    n_neg = int(len(y_train) - n_pos)
    model = XGBClassifier(
        **XGB_PARAMS, scale_pos_weight=(n_neg / max(n_pos, 1))
    )
    model.fit(X_train, y_train)

    p_cal_raw = model.predict_proba(X_cal)[:, 1]
    isotonic = IsotonicRegression(out_of_bounds="clip")
    isotonic.fit(p_cal_raw, y_cal)
    p_cal = isotonic.transform(p_cal_raw)

    metrics = {
        "n_samples": float(len(X)),
        "n_calibration": float(len(y_cal)),
        "n_positive": float(int(y.sum())),
        "roc_auc": float(roc_auc_score(y_cal, p_cal_raw)),
        "accuracy_at_0.5": float(
            accuracy_score(y_cal, (p_cal >= 0.5).astype(int))
        ),
        "f1_macro": float(
            f1_score(y_cal, (p_cal >= 0.5).astype(int), average="macro")
        ),
    }
    return model, isotonic, metrics


def target_vector(rows: list[dict[str, Any]], target_field: str, positive_labels: list[str]) -> np.ndarray:
    positive = set(positive_labels)
    values = [_field_value(row, target_field) for row in rows]
    if not positive or any(v is None or str(v).strip() == "" for v in values):
        raise ValueError("El objetivo contiene valores ausentes o faltan etiquetas positivas")
    classes = {str(v).strip() for v in values}
    if len(classes) < 2:
        raise ValueError("El campo objetivo debe contener al menos dos clases distintas para entrenar")
    return np.array([int(str(v) in positive) for v in values])



def run_model_training(
    model_id: str,
    async_operation_id: str,
    *,
    model_repository,
    async_operation_repository,
    dataset_repository,
    model_object_storage,
) -> dict[str, Any]:
    """Orchestrates one training run end to end - imported and driven by
    infrastructure/entrypoint/worker/celery/tasks.py::train_model_task, kept
    in its own module for the same reason alert_review_workflow.py is split
    out of tasks.py (real business logic, not a thin task wrapper).

    Repositories are passed by duck-typed dependency (not imported port
    types) so this module stays decoupled from which concrete
    ModelRepository/AsyncOperationRepository/DatasetRepository/ObjectStoragePort
    the caller wires - infrastructure/entrypoint/worker/celery/tasks.py wires
    the real adapters."""
    op_id = uuid_module.UUID(async_operation_id)
    mdl_id = uuid_module.UUID(model_id)

    def _progress(stage: str, pct: int) -> None:
        async_operation_repository.update(
            op_id,
            status=AsyncOperationStatus.RUNNING,
            result={"stage": stage, "progress_pct": pct},
        )

    model = model_repository.get(mdl_id)
    if model is None:
        raise ValueError(f"Model {model_id} not found")

    try:
        _progress("loading_dataset", 5)
        rows = dataset_repository.get_rows(model.dataset_name)

        from src.infrastructure.workflows.celery.model_evaluation import train_model_bundle

        _progress("building_features", 25)
        bundle = train_model_bundle(rows, model, progress=_progress)
        metrics = bundle["metrics"]
        _progress("persisting", 85)
        buffer = BytesIO()
        joblib.dump(bundle, buffer)
        storage_key = f"{model_id}/{model.tag}.joblib"
        model_object_storage.put_bytes(
            key=storage_key,
            content=buffer.getvalue(),
            content_type="application/octet-stream",
        )

        model.status = ModelStatus.READY
        model.metrics = metrics
        model.training_report = bundle["training_report"]
        model.storage_ref = storage_key
        model.error = None
        model_repository.update(model)

        async_operation_repository.update(
            op_id,
            status=AsyncOperationStatus.SUCCEEDED,
            result={"stage": "done", "progress_pct": 100, "metrics": metrics},
        )
        return {"status": "ok", "model_id": model_id, "metrics": metrics}
    except Exception as exc:
        model.status = ModelStatus.FAILED
        model.error = str(exc)
        model_repository.update(model)
        async_operation_repository.update(
            op_id, status=AsyncOperationStatus.FAILED, error=str(exc)
        )
        raise
