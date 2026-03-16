"""
Advanced auto-preprocessing pipeline.
Handles: datetime parsing, frequency detection, missing values, outliers,
         stationarity, normalization, feature engineering.
"""
import pandas as pd
import numpy as np
from typing import Tuple, Dict, Any, List, Optional


# ─── Semantic synonym libraries for column role detection ─────────────────────

DATE_SYNONYMS = {
    "exact": [
        "date", "datetime", "timestamp", "time", "dt", "ts",
        "period", "week", "month", "year", "day", "hour",
        "date_time", "order_date", "sale_date", "purchase_date",
        "transaction_date", "invoice_date", "record_date", "event_date",
        "created_at", "created", "updated_at", "updated", "occurred_at",
        "reported_date", "log_date", "entry_date",
    ],
    "partial": [
        "date", "time", "stamp", "period", "week", "month",
        "year", "day", "hour", "temporal", "when", "occurred",
    ],
}

TARGET_SYNONYMS = {
    "exact": [
        "target", "y", "value", "values", "sales", "sale",
        "revenue", "revenues", "demand", "demands", "price", "prices",
        "amount", "amounts", "count", "counts", "quantity", "qty",
        "total", "totals", "volume", "units", "cost", "costs",
        "income", "profit", "output", "measure", "metric",
        "forecast", "actual", "observed", "series",
    ],
    "partial": [
        "sale", "rev", "demand", "price", "amount", "qty",
        "count", "total", "volume", "unit", "cost", "income",
        "profit", "output", "target", "value", "metric", "measure",
    ],
}

EXOG_SYNONYMS = {
    "partial": [
        "temp", "weather", "holiday", "promo", "promotion",
        "discount", "event", "flag", "indicator", "feature",
        "rate", "index", "gdp", "inflation", "population",
        "region", "category", "segment", "channel",
    ],
}


def _score_date_column(col: str, series: pd.Series) -> int:
    """Score a column for being a date column (0–100)."""
    score = 0
    col_lower = col.lower().strip()
    col_clean = col_lower.replace("_", " ").replace("-", " ")

    # Dtype bonus (highest priority)
    if pd.api.types.is_datetime64_any_dtype(series):
        score += 45

    # Exact name match
    if col_lower in DATE_SYNONYMS["exact"] or col_clean in DATE_SYNONYMS["exact"]:
        score += 35
    else:
        # Partial keyword match
        for kw in DATE_SYNONYMS["partial"]:
            if kw in col_lower:
                score += 20
                break

    # Try parsing top values as dates (FIX Bug 13: removed deprecated infer_datetime_format)
    if score < 40 and series.dtype == object:
        try:
            parsed = pd.to_datetime(series.dropna().head(30))
            if len(parsed) > 0:
                score += 30
        except Exception:
            pass
    elif pd.api.types.is_datetime64_any_dtype(series):
        score = min(score + 10, 100)  # extra boost for confirmed datetime dtype

    # Uniqueness: dates should be mostly unique
    try:
        unique_ratio = series.nunique() / max(len(series), 1)
        if unique_ratio > 0.8:
            score += 5
    except Exception:
        pass

    return min(score, 100)


def _score_target_column(col: str, series: pd.Series, date_col: Optional[str]) -> int:
    """Score a column for being the forecast target (0–100)."""
    if col == date_col:
        return 0
    score = 0
    col_lower = col.lower().strip()
    col_clean = col_lower.replace("_", " ").replace("-", " ")

    # Must be numeric
    if not pd.api.types.is_numeric_dtype(series):
        return 0
    # All-NaN column is useless as a target
    if series.notna().sum() == 0:
        return 0
    score += 20

    # Exact name match
    if col_lower in TARGET_SYNONYMS["exact"] or col_clean in TARGET_SYNONYMS["exact"]:
        score += 40
    else:
        # Partial keyword match
        for kw in TARGET_SYNONYMS["partial"]:
            if kw in col_lower:
                score += 20
                break

    # Variability: target should vary over time
    try:
        cv = series.std() / (abs(series.mean()) + 1e-9)
        if cv > 0.05:
            score += 10
        if cv > 0.2:
            score += 5
    except Exception:
        pass

    # Non-null ratio
    try:
        nonnull_ratio = series.notna().mean()
        if nonnull_ratio > 0.8:
            score += 5
    except Exception:
        pass

    return min(score, 100)


def auto_detect_columns(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Detect date, target, and exogenous columns using deep semantic scoring.
    Returns confidence scores, mapping explanation, and suggestions.
    """
    # ── Score all columns ────────────────────────────────────────────────────
    date_scores: Dict[str, int] = {}
    for col in df.columns:
        date_scores[col] = _score_date_column(col, df[col])

    # Pick best date column
    date_col: Optional[str] = None
    if date_scores:
        best_date = max(date_scores, key=lambda c: date_scores[c])
        if date_scores[best_date] >= 30:
            date_col = best_date

    # If nothing found by scoring, brute-force parse
    if not date_col:
        for col in df.columns:
            if df[col].dtype == "object":
                try:
                    pd.to_datetime(df[col].dropna().head(20))
                    date_col = col
                    date_scores[col] = max(date_scores.get(col, 0), 40)
                    break
                except Exception:
                    pass

    # Score all numeric columns for target role
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    target_scores: Dict[str, int] = {}
    for col in numeric_cols:
        target_scores[col] = _score_target_column(col, df[col], date_col)

    target_col: Optional[str] = None
    if target_scores:
        best_target = max(target_scores, key=lambda c: target_scores[c])
        if target_scores[best_target] > 0:
            target_col = best_target

    # Exogenous: all remaining numeric columns
    exog_cols = [c for c in numeric_cols if c != target_col]

    # ── Build mapping_confidence dict ────────────────────────────────────────
    mapping_confidence: Dict[str, int] = {}
    for col in df.columns:
        if col == date_col:
            mapping_confidence[col] = date_scores.get(col, 0)
        elif col == target_col:
            mapping_confidence[col] = target_scores.get(col, 0)
        else:
            mapping_confidence[col] = 0

    # ── Build mapping suggestions (all candidates with reason) ───────────────
    mapping_suggestions = []
    for col, score in sorted(date_scores.items(), key=lambda x: -x[1]):
        if score >= 25:
            mapping_suggestions.append({
                "col": col,
                "role": "date",
                "confidence": score,
                "reason": "datetime dtype" if pd.api.types.is_datetime64_any_dtype(df[col])
                           else "keyword match + parseable as date",
                "is_selected": col == date_col,
            })
    for col, score in sorted(target_scores.items(), key=lambda x: -x[1]):
        if score >= 20:
            mapping_suggestions.append({
                "col": col,
                "role": "target",
                "confidence": score,
                "reason": "numeric + keyword match",
                "is_selected": col == target_col,
            })

    # ── Mapping warnings ─────────────────────────────────────────────────────
    mapping_warnings: List[str] = []
    date_candidates = [c for c, s in date_scores.items() if s >= 30 and c != date_col]
    if date_candidates:
        mapping_warnings.append(
            f"Multiple date-like columns found. Using '{date_col}' (highest confidence). "
            f"Alternatives: {', '.join(date_candidates[:3])}"
        )
    target_candidates = [c for c, s in target_scores.items() if s >= 30 and c != target_col]
    if target_candidates:
        mapping_warnings.append(
            f"Multiple target-like columns found. Using '{target_col}' (highest confidence). "
            f"Alternatives: {', '.join(target_candidates[:3])}"
        )
    if date_col and date_scores.get(date_col, 0) < 50:
        mapping_warnings.append(
            f"Date column '{date_col}' detected with low confidence ({date_scores.get(date_col, 0)}%). "
            "Please verify the selection."
        )
    if target_col and target_scores.get(target_col, 0) < 50:
        mapping_warnings.append(
            f"Target column '{target_col}' detected with low confidence ({target_scores.get(target_col, 0)}%). "
            "Please verify the selection."
        )

    # ── column_mapping summary dict ───────────────────────────────────────────
    column_mapping: Dict[str, str] = {}
    if date_col:
        column_mapping["date"] = date_col
    if target_col:
        column_mapping["target"] = target_col

    # ── Anomaly detection on target column ───────────────────────────────────
    anomalies = []
    if target_col and len(df) > 10:
        try:
            from sklearn.ensemble import IsolationForest
            iso = IsolationForest(contamination=0.05, random_state=42)
            y = df[target_col].copy()
            y = pd.to_numeric(y, errors='coerce')
            y = y.fillna(y.median()).values.reshape(-1, 1)
            preds = iso.fit_predict(y)
            outlier_indices = np.where(preds == -1)[0]
            for idx in outlier_indices:
                idx_val = int(idx)
                val = df[target_col].iloc[idx_val]
                if pd.isna(val):
                    continue
                anomalies.append({
                    "index": idx_val,
                    "date": str(df[date_col].iloc[idx_val]) if date_col and date_col in df.columns else "",
                    "value": float(val)
                })
        except Exception:
            pass

    return {
        "date_col": date_col,
        "target_col": target_col,
        "exog_cols": exog_cols,
        "anomalies": anomalies,
        "all_columns": df.columns.tolist(),
        "numeric_columns": numeric_cols,
        "dtypes": {c: str(df[c].dtype) for c in df.columns},
        "shape": list(df.shape),
        "preview": df.head(5).to_dict(orient="records"),
        # ── New semantic mapping metadata ──────────────────────────────────
        "mapping_confidence": mapping_confidence,
        "column_mapping": column_mapping,
        "mapping_suggestions": mapping_suggestions,
        "mapping_warnings": mapping_warnings,
    }


def detect_frequency(series: pd.Series) -> str:
    """Detect time series frequency from datetime index.
    FIX Bug 14: Added hourly and business-day frequency detection.
    """
    if len(series) < 3:
        return "D"
    diffs = series.diff().dropna()
    median_diff = diffs.median()
    # Convert to total hours for finer-grained detection
    total_hours = median_diff.total_seconds() / 3600 if hasattr(median_diff, 'total_seconds') else float(median_diff) / 3.6e12
    days = total_hours / 24

    if total_hours <= 1.5:
        return "H"       # Hourly
    elif total_hours <= 12:
        return "6H"      # Sub-daily (6-hour blocks)
    elif days <= 1.5:
        return "D"       # Daily
    elif days <= 5.5:
        return "B"       # Business day
    elif days <= 8:
        return "W"       # Weekly
    elif days <= 16:
        return "2W"      # Bi-weekly
    elif days <= 35:
        return "MS"      # Monthly
    elif days <= 100:
        return "QS"      # Quarterly
    else:
        return "YS"      # Yearly

def preprocess(df: pd.DataFrame, date_col: str, target_col: str,
               exog_cols: Optional[List[str]] = None,
               frequency: str = "auto",
               clean_anomalies: bool = False) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Full auto-preprocessing pipeline.
    Returns cleaned DataFrame and preprocessing report.
    """
    report = {
        "original_shape": list(df.shape),
        "steps": [],
        "warnings": [],
    }

    # 0. Minimum length guard
    if len(df) < 20:
        raise ValueError(
            f"Dataset too small: {len(df)} rows. A minimum of 20 rows is required for reliable forecasting."
        )

    # 0.1 Flatten MultiIndex columns (from Excel merged headers)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [" ".join(str(c) for c in col).strip() for col in df.columns]
        report["warnings"].append("Multi-level column headers detected and flattened to single level.")

    # 0.2 Deduplicate column names
    cols = list(df.columns)
    if len(cols) != len(set(cols)):
        seen: dict = {}
        new_cols = []
        for c in cols:
            if c in seen:
                seen[c] += 1
                new_cols.append(f"{c}_{seen[c]}")
            else:
                seen[c] = 0
                new_cols.append(c)
        df.columns = new_cols
        report["warnings"].append("Duplicate column names detected and renamed (e.g. 'value' → 'value_1').")

    try:
        # FIX Bug 13: removed deprecated infer_datetime_format=True (pandas 2.x auto-infers)
        df[date_col] = pd.to_datetime(df[date_col])
        report["steps"].append({"step": "datetime_parsing", "status": "success"})
    except Exception as e:
        # Try common formats
        for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"]:
            try:
                df[date_col] = pd.to_datetime(df[date_col], format=fmt)
                report["steps"].append({"step": "datetime_parsing", "status": "success", "format": fmt})
                break
            except:
                continue
        else:
            raise ValueError(f"Cannot parse datetime column '{date_col}': {e}")

    # 2. Sort by date
    df = df.sort_values(date_col).reset_index(drop=True)
    report["steps"].append({"step": "sort_by_date", "status": "success"})

    # 3. Detect frequency
    if frequency == "auto":
        frequency = detect_frequency(df[date_col])
    report["detected_frequency"] = frequency
    report["steps"].append({"step": "frequency_detection", "frequency": frequency})

    # 4. Handle duplicates
    dup_count = df.duplicated(subset=[date_col]).sum()
    if dup_count > 0:
        df = df.groupby(date_col).agg({
            target_col: "mean",
            **{c: "mean" for c in (exog_cols or []) if c in df.columns}
        }).reset_index()
        report["steps"].append({"step": "duplicate_removal", "removed": int(dup_count)})

    # 5. Set datetime index
    df = df.set_index(date_col)

    # 6. Ensure target is numeric
    df[target_col] = pd.to_numeric(df[target_col], errors="coerce")

    # 7. Handle missing values
    missing_before = int(df[target_col].isna().sum())

    if missing_before > 0:
        # Interpolate with method based on frequency
        if frequency in ("D", "W"):
            # First interpolate small gaps linearly
            df[target_col] = df[target_col].interpolate(method="time", limit=3)
            # Fill remaining large gaps using previous seasonal values if possible
            if frequency == "D" and len(df) > 7:
                df[target_col] = df[target_col].fillna(df[target_col].shift(7))
            elif frequency == "W" and len(df) > 52:
                df[target_col] = df[target_col].fillna(df[target_col].shift(52))
            # Fallback for remaining NaNs
            df[target_col] = df[target_col].interpolate(method="time")
        else:
            df[target_col] = df[target_col].interpolate(method="linear")
        # Forward/backward fill edges
        df[target_col] = df[target_col].ffill().bfill()
        report["steps"].append({"step": "missing_value_imputation", "target_missing": missing_before, "method": "interpolation+seasonal_fill"})

    # Handle exog missing values
    if exog_cols:
        for col in exog_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
                miss = int(df[col].isna().sum())
                if miss > 0:
                    df[col] = df[col].interpolate(method="linear").ffill().bfill()

    # 7.5 Optional Anomaly Smoothing via Isolation Forest
    _isoforest_ran = False
    if clean_anomalies and len(df) > 10:
        try:
            from sklearn.ensemble import IsolationForest
            iso = IsolationForest(contamination=0.05, random_state=42)
            y = df[target_col].fillna(df[target_col].median()).values.reshape(-1, 1)
            preds = iso.fit_predict(y)
            outlier_mask = preds == -1
            if outlier_mask.sum() > 0:
                df.loc[outlier_mask, target_col] = np.nan
                if frequency in ("D", "W") and isinstance(df.index, pd.DatetimeIndex):
                    df[target_col] = df[target_col].interpolate(method="time")
                else:
                    df[target_col] = df[target_col].interpolate(method="linear")
                df[target_col] = df[target_col].ffill().bfill()
                _isoforest_ran = True
                report["steps"].append({"step": "anomaly_smoothing", "anomalies_smoothed": int(outlier_mask.sum()), "method": "IsolationForest"})
        except Exception as e:
            report["warnings"].append(f"Anomaly smoothing failed: {str(e)}")

    # 8. Outlier clip via IQR — skip if IsolationForest already cleaned anomalies
    # FIX Bug 15: Use 2.5x IQR (less aggressive than 2.0x) to preserve more signal
    if not _isoforest_ran:
        q1 = df[target_col].quantile(0.25)
        q3 = df[target_col].quantile(0.75)
        iqr = q3 - q1
        lower = q1 - 2.5 * iqr
        upper = q3 + 2.5 * iqr
        outliers = ((df[target_col] < lower) | (df[target_col] > upper)).sum()
        if outliers > 0 and outliers < len(df) * 0.1:
            df[target_col] = df[target_col].clip(lower=lower, upper=upper)
            report["steps"].append({"step": "outlier_handling", "outliers_clipped": int(outliers), "method": "IQR_2.5x"})
        elif outliers > 0:
            report["warnings"].append(f"{outliers} outliers detected but not clipped (>10% of data)")

    # 9. Stationarity test (ADF)
    try:
        from statsmodels.tsa.stattools import adfuller
        adf_result = adfuller(df[target_col].dropna(), autolag="AIC")
        is_stationary = adf_result[1] < 0.05
        report["stationarity"] = {
            "is_stationary": is_stationary,
            "adf_statistic": round(float(adf_result[0]), 4),
            "p_value": round(float(adf_result[1]), 4),
            "critical_values": {k: round(float(v), 4) for k, v in adf_result[4].items()}
        }
        report["steps"].append({"step": "stationarity_test", "stationary": is_stationary, "p_value": round(float(adf_result[1]), 4)})
    except Exception as e:
        report["warnings"].append(f"Stationarity test failed: {str(e)}")

    # 10. Basic statistics
    report["statistics"] = {
        "mean": round(float(df[target_col].mean()), 2),
        "std": round(float(df[target_col].std()), 2),
        "min": round(float(df[target_col].min()), 2),
        "max": round(float(df[target_col].max()), 2),
        "median": round(float(df[target_col].median()), 2),
        "skewness": round(float(df[target_col].skew()), 4),
        "kurtosis": round(float(df[target_col].kurtosis()), 4),
    }

    # 11. Seasonality detection
    try:
        from statsmodels.tsa.seasonal import seasonal_decompose
        if len(df) >= 14:
            period = {"D": 7, "W": 52, "MS": 12, "QS": 4, "YS": 1, "2W": 26}.get(frequency, 7)
            period = min(period, len(df) // 2)
            if period >= 2:
                decomp = seasonal_decompose(df[target_col], model="additive", period=period, extrapolate_trend="freq")
                seasonal_strength = 1 - (decomp.resid.dropna().var() / (decomp.resid.dropna().var() + decomp.seasonal.dropna().var() + 1e-10))
                report["seasonality"] = {
                    "detected": bool(seasonal_strength > 0.3),
                    "strength": round(float(seasonal_strength), 4),
                    "period": period
                }
                report["steps"].append({"step": "seasonality_detection", "detected": bool(seasonal_strength > 0.3), "strength": round(float(seasonal_strength), 4)})
    except Exception as e:
        report["warnings"].append(f"Seasonality detection failed: {str(e)}")

    report["final_shape"] = list(df.shape)
    report["date_range"] = {
        "start": str(df.index.min()),
        "end": str(df.index.max()),
    }

    # Reset index for model consumption
    df = df.reset_index()

    return df, report
