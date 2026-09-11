"""Four disjoint partitions; fitted preprocessing and reproducible model artifact."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from time import monotonic

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import (accuracy_score, average_precision_score, brier_score_loss,
                             confusion_matrix, f1_score, log_loss, precision_score,
                             recall_score, roc_auc_score, roc_curve, precision_recall_curve)
from sklearn.calibration import calibration_curve
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

from src.application.ports.model_port import ModelRecord, TrainingConfig
from src.infrastructure.workflows.celery.historical_features import read_field, timestamp
from src.infrastructure.workflows.celery.model_training import build_feature_frame, target_vector, XGB_PARAMS, SEED


def split_indices(rows: list[dict], y: np.ndarray, config: TrainingConfig) -> dict[str, np.ndarray]:
    if len(rows) < 40:
        raise ValueError("Se necesitan al menos 40 registros para cuatro particiones independientes")
    indices = np.arange(len(rows))
    if config.split_strategy == "temporal":
        dates = np.array([timestamp(read_field(r, config.time_field), config.timezone).value for r in rows])
        indices = np.argsort(dates, kind="stable")
        sorted_dates = dates[indices]
        boundaries = [int(np.searchsorted(sorted_dates, sorted_dates[int(len(rows)*p)], side="left")) for p in (.6,.75,.85)]
        parts = np.split(indices, boundaries)
    else:
        train, rest = train_test_split(indices, test_size=.4, stratify=y, random_state=SEED)
        val, rest = train_test_split(rest, train_size=.375, stratify=y[rest], random_state=SEED)
        cal, test = train_test_split(rest, train_size=.4, stratify=y[rest], random_state=SEED)
        parts = [train, val, cal, test]
    result = dict(zip(("training", "validation", "calibration", "test"), parts))
    for name, part in result.items():
        if len(part) < 2 or len(np.unique(y[part])) != 2:
            raise ValueError(f"La partición {name} necesita ambas clases; amplía los datos o revisa la separación")
    return result


def threshold_metrics(y, probabilities, threshold):
    predicted = probabilities >= threshold
    tn, fp, fn, tp = confusion_matrix(y, predicted, labels=[0, 1]).ravel()
    return {"threshold": float(threshold), "precision": float(precision_score(y, predicted, zero_division=0)),
            "recall": float(recall_score(y, predicted, zero_division=0)),
            "f1": float(f1_score(y, predicted, zero_division=0)),
            "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn), "alerts": int(tp+fp)}


def _points(x, y, xname, yname):
    indices = np.unique(np.linspace(0, len(x)-1, min(100, len(x))).astype(int))
    return [{xname: float(x[i]), yname: float(y[i])} for i in indices]


def train_model_bundle(rows: list[dict], record: ModelRecord, progress=lambda stage, pct: None) -> dict:
    started = monotonic()
    config = record.training_config
    # Also enforce target isolation for older records and direct repository callers.
    sources = [v for f in record.feature_transforms if f.kind.value != "drop" for v in (f.field, f.reference_field)]
    sources += [v for f in record.historical_features for v in (f.field, f.reference_field, f.compare_field)]
    if any(source and (source == record.target_field or record.target_field.startswith(source + ".") or source.startswith(record.target_field + ".")) for source in sources):
        raise ValueError("El objetivo no puede usarse como característica")
    feature_configuration = deepcopy(getattr(record, "feature_configuration", None))
    if feature_configuration is not None:
        from src.domain.models.feature_recipe import validate_feature_definition
        feature_configuration = validate_feature_definition(feature_configuration, forbidden_paths=(record.target_field,))
    y = target_vector(rows, record.target_field, record.positive_labels)
    partitions = split_indices(rows, y, config)
    train_rows = [rows[i] for i in partitions["training"]]
    X, vocab = build_feature_frame(train_rows, record.feature_transforms,
                                  historical_features=record.historical_features, timezone=config.timezone,
                                  feature_configuration=feature_configuration)
    if X.empty or not X.notna().any().any():
        raise ValueError("Las características seleccionadas no generan datos utilizables")
    categories = {col: list(X[col].cat.categories) for col in X if str(X[col].dtype) == "category"}
    matrices = {"training": X}
    for name, indices in partitions.items():
        if name == "training":
            continue
        frame, _ = build_feature_frame([rows[i] for i in indices], record.feature_transforms, rule_vocab=vocab,
                                       historical_features=record.historical_features, timezone=config.timezone,
                                  feature_configuration=feature_configuration)
        frame = frame.reindex(columns=X.columns)
        for col, cats in categories.items():
            frame[col] = pd.Categorical(frame[col].astype(object), categories=cats)
        matrices[name] = frame
    labels = {name: y[indices] for name, indices in partitions.items()}
    params = dict(XGB_PARAMS)
    for key in ("n_estimators", "max_depth", "learning_rate", "subsample", "colsample_bytree", "reg_lambda", "min_child_weight"):
        params[key] = getattr(config, key)
    params["scale_pos_weight"] = config.scale_pos_weight if config.scale_pos_weight is not None else float((labels["training"] == 0).sum() / labels["training"].sum())
    params["early_stopping_rounds"] = config.early_stopping_rounds
    progress("training", 50)
    model = XGBClassifier(**params)
    model.fit(X, labels["training"], eval_set=[(X, labels["training"]), (matrices["validation"], labels["validation"])], verbose=False)
    progress("calibrating", 65)
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(model.predict_proba(matrices["calibration"])[:, 1], labels["calibration"])
    val_prob = calibrator.transform(model.predict_proba(matrices["validation"])[:, 1])
    # Select only on validation; test is never used to choose the operating point.
    candidates = np.linspace(.05, .95, 19)
    chosen = max((threshold_metrics(labels["validation"], val_prob, t) for t in candidates), key=lambda m: (m["f1"], m["precision"], m["threshold"]))
    progress("evaluating", 75)
    test_y = labels["test"]
    raw = model.predict_proba(matrices["test"])[:, 1]
    prob = calibrator.transform(raw)
    fixed = threshold_metrics(test_y, prob, chosen["threshold"])
    metrics = {"n_samples": float(len(rows)), "n_positive": float(y.sum()),
               **{f"n_{name}": float(len(indices)) for name, indices in partitions.items()},
               "roc_auc": float(roc_auc_score(test_y, prob)), "roc_auc_raw": float(roc_auc_score(test_y, raw)),
               "average_precision": float(average_precision_score(test_y, prob)),
               "brier_score": float(brier_score_loss(test_y, prob)), "log_loss": float(log_loss(test_y, prob, labels=[0,1])),
               "accuracy_at_0.5": float(accuracy_score(test_y, prob >= .5)),
               "f1_macro": float(f1_score(test_y, prob >= chosen["threshold"], average="macro")),
               **{k: float(v) for k,v in fixed.items()}}
    fpr, tpr, _ = roc_curve(test_y, prob)
    precision, recall, _ = precision_recall_curve(test_y, prob)
    observed, predicted = calibration_curve(test_y, prob, n_bins=10)
    losses = model.evals_result()
    loss_count = len(losses["validation_0"]["logloss"])
    loss_indices = np.unique(np.linspace(0,loss_count-1,min(100,loss_count)).astype(int))
    report = {
        "schema_version": 1, "evaluation_partition": "test", "threshold_selection": "validation_f1",
        "threshold": chosen["threshold"], "validation_metrics": chosen,
        "split_strategy": config.split_strategy, "timezone": config.timezone,
        "partitions": {name: {"rows": len(idx), "positive": int(y[idx].sum())} for name, idx in partitions.items()},
        "thresholds": [threshold_metrics(test_y, prob, t) for t in candidates],
        "roc_curve": _points(fpr,tpr,"fpr","tpr"), "precision_recall_curve": _points(recall,precision,"recall","precision"),
        "calibration_curve": _points(predicted,observed,"predicted","observed"),
        "learning_curve": [{"iteration": int(i+1), "training": losses["validation_0"]["logloss"][i], "validation": losses["validation_1"]["logloss"][i]} for i in loss_indices],
        "feature_importance": sorted([{"feature": str(c), "importance": float(v)} for c,v in zip(X.columns, model.feature_importances_)], key=lambda r: r["importance"], reverse=True)[:30],
        "best_iteration": int(model.best_iteration + 1) if config.early_stopping_rounds else loss_count,
        "feature_count": len(X.columns), "duration_seconds": round(monotonic()-started, 3),
        "effective_parameters": params,
        "dataset_sha256": hashlib.sha256(json.dumps(rows, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest(),
    }
    return {"schema_version": 2, "model": model, "isotonic": calibrator, "columns": list(X.columns),
            "cat_categories": categories, "rule_vocab": vocab, "feature_transforms": record.feature_transforms,
            "historical_features": record.historical_features, "training_config": asdict(config),
            "feature_configuration": feature_configuration,
            "threshold": chosen["threshold"], "metrics": metrics, "training_report": report, "tag": record.tag}
