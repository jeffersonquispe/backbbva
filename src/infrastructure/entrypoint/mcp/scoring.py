from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import shap

from src.infrastructure.workflows.celery.model_training import build_feature_frame


def score_row(bundle: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """Reproduces the exact feature matrix used at training time (fixed
    rule_vocab, fixed column order, fixed categorical categories) for one
    row, scores it, calibrates it, and attaches the top-5 SHAP
    contributions - same shape as the newArquitecture+XGboost branch's
    score_xus()."""
    X, _ = build_feature_frame(
        [row], bundle["feature_transforms"], rule_vocab=bundle["rule_vocab"]
    )
    X = X.reindex(columns=bundle["columns"], fill_value=np.nan)
    for col, categories in bundle["cat_categories"].items():
        X[col] = pd.Categorical(X[col].astype(str), categories=categories)

    model = bundle["model"]
    p_raw = float(model.predict_proba(X)[:, 1][0])
    p_cal = float(bundle["isotonic"].transform([p_raw])[0])

    try:
        explainer = shap.TreeExplainer(model)
        values = np.asarray(explainer(X).values)[0]
        top_idx = np.argsort(np.abs(values))[::-1][:5]
        top_features = [
            {
                "feature": bundle["columns"][i],
                "contribution": round(float(values[i]), 4),
                "value": str(X.iloc[0, i]),
            }
            for i in top_idx
        ]
    except Exception:
        top_features = []

    return {
        "score": round(p_cal, 4),
        "score_raw": round(p_raw, 4),
        "top_features": top_features,
    }
