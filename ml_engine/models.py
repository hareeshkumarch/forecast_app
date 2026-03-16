"""
Forecasting models: ARIMA, SARIMA, ARIMAX, Prophet, Holt-Winters, LSTM, Transformer.
Each model returns: metrics, predictions, forecast, residuals, parameters.
All use async-compatible callbacks for progress reporting.
"""
import numpy as np
import warnings
import time
import pandas as pd

# Heavy ML Imports
import os
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
import tensorflow as tf
tf.get_logger().setLevel("ERROR")
from sklearn.preprocessing import MinMaxScaler
from prophet import Prophet
import logging
logging.getLogger("prophet").setLevel(logging.WARNING)
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)

import random
random.seed(42)
np.random.seed(42)
tf.keras.utils.set_random_seed(42)

warnings.filterwarnings("ignore")

def _safe_float(v):
    """Convert to Python float, handling numpy types and NaN/Inf."""
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, np.bool_)):
        v = float(v)
    if isinstance(v, float):
        if np.isnan(v) or np.isinf(v):
            return None
        return round(v, 6)
    if isinstance(v, (int,)):
        return v
    try:
        return round(float(v), 6)
    except:
        return None

def _compute_metrics(actual, predicted, aic=None, bic=None):
    """Compute forecast accuracy metrics. Handles NaN, Inf, and zero-division safely."""
    actual = np.array(actual, dtype=float)
    predicted = np.array(predicted, dtype=float)
    # Align lengths
    n = min(len(actual), len(predicted))
    actual, predicted = actual[:n], predicted[:n]
    # Remove NaN pairs
    mask = np.isfinite(actual) & np.isfinite(predicted)
    a, p = actual[mask], predicted[mask]
    if len(a) == 0:
        return {"mae": None, "rmse": None, "mape": None, "r2": None}

    mae = float(np.mean(np.abs(a - p)))
    rmse = float(np.sqrt(np.mean((a - p) ** 2)))

    # MAPE: skip points where actual == 0 to avoid division by zero
    nonzero_mask = a != 0
    if nonzero_mask.sum() > 0:
        mape = float(np.mean(np.abs((a[nonzero_mask] - p[nonzero_mask]) / a[nonzero_mask])) * 100)
    else:
        mape = None  # All actuals are zero — MAPE undefined

    ss_res = np.sum((a - p) ** 2)
    ss_tot = np.sum((a - np.mean(a)) ** 2)
    r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else None

    result = {"mae": round(mae, 4), "rmse": round(rmse, 4), "mape": round(mape, 4) if mape is not None else None, "r2": round(r2, 4) if r2 is not None else None}
    if aic is not None:
        result["aic"] = round(float(aic), 2)
    if bic is not None:
        result["bic"] = round(float(bic), 2)
    return result

def _build_output(dates, actual, predicted, forecast_dates, forecast_vals, lower, upper, residuals, metrics, params, train_time, tuning_combinations=None):
    """Standard output format for all models."""
    preds = []
    for i in range(len(dates)):
        preds.append({
            "date": str(dates[i]),
            "actual": _safe_float(actual[i]) if i < len(actual) else None,
            "predicted": _safe_float(predicted[i]) if i < len(predicted) else None,
        })
    fc = []
    for i in range(len(forecast_dates)):
        fc.append({
            "date": str(forecast_dates[i]),
            "predicted": _safe_float(forecast_vals[i]),
            "lower": _safe_float(lower[i]) if lower is not None and i < len(lower) else None,
            "upper": _safe_float(upper[i]) if upper is not None and i < len(upper) else None,
        })
    res = [_safe_float(r) for r in residuals] if residuals is not None else []
    output = {
        "metrics": metrics,
        "predictions": preds,
        "forecast": fc,
        "residuals": res,
        "parameters": {k: _safe_float(v) if isinstance(v, (int, float, np.integer, np.floating)) else str(v) for k, v in (params or {}).items()},
        "training_time": round(train_time, 3),
    }
    if tuning_combinations is not None:
        output["tuning_metrics"] = {
            "combinations_tested": tuning_combinations,
            "selected_params": output["parameters"]
        }
    return output


def train_arima(df, date_col, target_col, horizon, progress_cb=None, **kw):
    # FIX Bug 1: Removed LSTM look_back/epoch guard that was wrongly placed here.
    t0 = time.time()
    if progress_cb:
        progress_cb(0.1, "Fitting ARIMA model...")
    from statsmodels.tsa.arima.model import ARIMA
    y = df[target_col].values
    dates = df[date_col].values

    hp = kw.get("hyperparameters", {})
    auto_tune = kw.get("auto_tune", False)

    p_hp, d_hp, q_hp = hp.get("arima_p"), hp.get("arima_d"), hp.get("arima_q")

    combinations_tested = None
    # FIX Bug 6: Track whether any grid search combo succeeded; warn if not.
    if not auto_tune and p_hp is not None and d_hp is not None and q_hp is not None:
        best_order = (int(p_hp), int(d_hp), int(q_hp))
        if progress_cb:
            progress_cb(0.6, f"Using custom order: {best_order}")
    else:
        combinations_tested = 0
        best_aic = np.inf
        best_order = (1, 1, 1)
        any_succeeded = False
        for p in range(0, 3):
            for d in range(0, 2):
                for q in range(0, 3):
                    try:
                        combinations_tested += 1
                        m = ARIMA(y, order=(p, d, q))
                        r = m.fit()
                        if r.aic < best_aic:
                            best_aic = r.aic
                            best_order = (p, d, q)
                            any_succeeded = True
                    except Exception as e:
                        warnings.warn(f"ARIMA(p={p}, d={d}, q={q}) failed: {e}")
                        continue
        if not any_succeeded:
            warnings.warn("ARIMA grid search: all (p,d,q) combinations failed. Falling back to (1,1,1).")
        if progress_cb:
            progress_cb(0.6, f"Best auto order: {best_order}")

    model = ARIMA(y, order=best_order)
    result = model.fit()
    fitted = result.fittedvalues
    residuals = y - fitted

    fc = result.get_forecast(horizon)
    fc_mean = fc.predicted_mean
    ci = fc.conf_int()
    freq = pd.infer_freq(df[date_col]) or "D"
    last_date = pd.to_datetime(df[date_col]).values[-1]
    fc_dates = pd.date_range(start=last_date, periods=horizon + 1, freq=freq)[1:]

    ci_arr = np.asarray(ci)
    ci_lower = ci_arr[:, 0]
    ci_upper = ci_arr[:, 1]

    metrics = _compute_metrics(y, fitted, aic=result.aic, bic=result.bic)
    if progress_cb:
        progress_cb(1.0, "ARIMA complete")
    return _build_output(dates, y, fitted, fc_dates, fc_mean, ci_lower, ci_upper, residuals, metrics, {"order": str(best_order)}, time.time() - t0, tuning_combinations=combinations_tested)


def train_sarima(df, date_col, target_col, horizon, progress_cb=None, **kw):
    t0 = time.time()
    if progress_cb:
        progress_cb(0.1, "Fitting SARIMA model...")
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    y = df[target_col].values
    dates = df[date_col].values
    freq = pd.infer_freq(df[date_col]) or "D"
    m_val = {"D": 7, "W": 52, "MS": 12, "QS": 4}.get(freq, 7)
    m_val = min(m_val, len(y) // 3)
    if m_val < 2:
        m_val = 2

    if progress_cb:
        progress_cb(0.3, f"Seasonal period: {m_val}")

    # Minimum data requirement: SARIMA needs at least 2 × seasonal period rows
    min_required = max(2 * m_val, 20)
    if len(y) < min_required:
        raise ValueError(
            f"SARIMA requires at least {min_required} rows for seasonal period {m_val}. "
            f"Got {len(y)} rows. Use ARIMA or Holt-Winters for shorter series."
        )

    auto_tune = kw.get("auto_tune", False)
    # FIX Bug 7: Initialize result = None before branching to prevent UnboundLocalError
    result = None
    best_model = None
    combinations_tested = None

    if auto_tune:
        combinations_tested = 0
        if progress_cb: progress_cb(0.4, "Auto-tuning SARIMA grid...")
        best_aic = np.inf
        for p in [0, 1]:
            for q in [0, 1]:
                for P in [0, 1]:
                    for Q in [0, 1]:
                        try:
                            combinations_tested += 1
                            m = SARIMAX(y, order=(p, 1, q), seasonal_order=(P, 1, Q, m_val), enforce_stationarity=False, enforce_invertibility=False)
                            r = m.fit(disp=False, maxiter=50)
                            if r.aic < best_aic:
                                best_aic = r.aic
                                best_model = r
                        except Exception as e:
                            warnings.warn(f"SARIMA(p={p},1,q={q})x(P={P},1,Q={Q},{m_val}) failed: {e}")
                            continue
        result = best_model

    if not auto_tune or result is None:
        try:
            model = SARIMAX(y, order=(1, 1, 1), seasonal_order=(1, 1, 1, m_val), enforce_stationarity=False, enforce_invertibility=False)
            result = model.fit(disp=False, maxiter=100)
        except Exception as e:
            warnings.warn(f"SARIMA (1,1,1)x(1,1,1,{m_val}) failed ({e}), falling back to simpler order")
            model = SARIMAX(y, order=(1, 1, 0), seasonal_order=(1, 0, 0, m_val), enforce_stationarity=False, enforce_invertibility=False)
            result = model.fit(disp=False, maxiter=100)

    fitted = result.fittedvalues
    residuals = y - fitted
    fc = result.get_forecast(horizon)
    fc_mean = fc.predicted_mean
    ci = fc.conf_int()
    last_date = pd.to_datetime(df[date_col]).values[-1]
    fc_dates = pd.date_range(start=last_date, periods=horizon + 1, freq=freq)[1:]
    ci_arr = np.asarray(ci)
    ci_lower = ci_arr[:, 0]
    ci_upper = ci_arr[:, 1]
    metrics = _compute_metrics(y, fitted, aic=result.aic, bic=result.bic)
    if progress_cb:
        progress_cb(1.0, "SARIMA complete")
    return _build_output(dates, y, fitted, fc_dates, fc_mean, ci_lower, ci_upper, residuals, metrics, {"order": "(1,1,1)", "seasonal_order": f"(1,1,1,{m_val})"}, time.time() - t0, tuning_combinations=combinations_tested)


def train_arimax(df, date_col, target_col, horizon, exog_cols=None, progress_cb=None, **kw):
    t0 = time.time()
    if progress_cb:
        progress_cb(0.1, "Fitting ARIMAX model...")
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    y = df[target_col].values
    dates = df[date_col].values

    exog = None
    if exog_cols and len(exog_cols) > 0:
        exog = df[exog_cols].values
    if exog is None or exog.shape[1] == 0:
        # Fallback: create lag features
        exog = np.column_stack([np.roll(y, 1), np.roll(y, 2)])
        exog[:2] = y[:2]  # fill initial NaN

    model = SARIMAX(y, exog=exog, order=(2, 1, 1), enforce_stationarity=False, enforce_invertibility=False)
    result = model.fit(disp=False, maxiter=100)
    fitted = result.fittedvalues
    residuals = y - fitted

    # FIX Bug 9: removed duplicate identical else-branch; both branches used same logic.
    # For forecast, tile last known exog values (held constant)
    last_exog = np.tile(exog[-1:], (horizon, 1))

    fc = result.get_forecast(horizon, exog=last_exog)
    fc_mean = fc.predicted_mean
    ci = fc.conf_int()
    freq = pd.infer_freq(df[date_col]) or "D"
    last_date = pd.to_datetime(df[date_col]).values[-1]
    fc_dates = pd.date_range(start=last_date, periods=horizon + 1, freq=freq)[1:]
    ci_arr = np.asarray(ci)
    ci_lower = ci_arr[:, 0]
    ci_upper = ci_arr[:, 1]
    metrics = _compute_metrics(y, fitted, aic=result.aic, bic=result.bic)
    if progress_cb:
        progress_cb(1.0, "ARIMAX complete")
    return _build_output(dates, y, fitted, fc_dates, fc_mean, ci_lower, ci_upper, residuals, metrics, {"order": "(2,1,1)", "exog_features": len(exog_cols) if exog_cols else "lag_features"}, time.time() - t0)


def train_prophet(df, date_col, target_col, horizon, exog_cols=None, progress_cb=None, **kw):
    t0 = time.time()
    if progress_cb:
        progress_cb(0.1, "Fitting Prophet model...")

    # Prepare Prophet format
    prophet_df = df[[date_col, target_col]].copy()
    prophet_df.columns = ["ds", "y"]
    prophet_df["ds"] = pd.to_datetime(prophet_df["ds"])

    if exog_cols and len(exog_cols) > 0:
        for col in exog_cols:
            prophet_df[col] = df[col].values

    hp = kw.get("hyperparameters", {})
    auto_tune = kw.get("auto_tune", False)

    def _create_model(cps):
        m = Prophet(changepoint_prior_scale=cps, yearly_seasonality="auto", weekly_seasonality="auto", daily_seasonality=False)
        if exog_cols and len(exog_cols) > 0:
            for col in exog_cols:
                m.add_regressor(col)
        return m

    if auto_tune:
        # FIX Bug 5: Use a time-series hold-out (last 20%) instead of in-sample RMSE
        combinations_tested = 0
        if progress_cb: progress_cb(0.3, "Auto-tuning Prophet...")
        best_rmse = np.inf
        best_cps = 0.05
        best_model = None
        n = len(prophet_df)
        cutoff_idx = int(n * 0.8)
        train_df = prophet_df.iloc[:cutoff_idx].copy()
        val_df = prophet_df.iloc[cutoff_idx:].copy()
        val_horizon = len(val_df)

        for cps_test in [0.001, 0.01, 0.05, 0.1, 0.5]:
            combinations_tested += 1
            try:
                m = _create_model(cps_test)
                m.fit(train_df)
                future_val = m.make_future_dataframe(periods=val_horizon, freq=pd.infer_freq(train_df["ds"]) or "D")
                if exog_cols and len(exog_cols) > 0:
                    for col in exog_cols:
                        last_val = train_df[col].iloc[-1]
                        future_val[col] = list(train_df[col]) + [last_val] * val_horizon
                fc_val = m.predict(future_val)
                val_pred = fc_val["yhat"].values[-val_horizon:]
                val_actual = val_df["y"].values[:len(val_pred)]
                rmse = np.sqrt(np.mean((val_actual - val_pred) ** 2))
                if rmse < best_rmse:
                    best_rmse = rmse
                    best_cps = cps_test
                    best_model = m
            except Exception as e:
                warnings.warn(f"Prophet tuning (cps={cps_test}) failed: {e}")
                continue
        cps = best_cps
        # Re-fit best model on full data for final predictions
        model = _create_model(cps)
        model.fit(prophet_df)
        if progress_cb: progress_cb(0.5, f"Selected cps: {cps} (hold-out RMSE: {best_rmse:.4f})")
    else:
        combinations_tested = None
        cps = float(hp.get("prophet_cps", 0.05))
        model = _create_model(cps)
        model.fit(prophet_df)

    if progress_cb:
        progress_cb(0.6, "Generating forecast...")

    freq = pd.infer_freq(df[date_col]) or "D"
    future = model.make_future_dataframe(periods=horizon, freq=freq)

    if exog_cols and len(exog_cols) > 0:
        for col in exog_cols:
            y_ex = prophet_df[col].values
            if len(y_ex) > 1:
                slope = (y_ex[-1] - y_ex[0]) / len(y_ex)
                drift = np.array([y_ex[-1] + slope * i for i in range(1, horizon + 1)])
                future[col] = list(y_ex) + list(drift)
            else:
                last_val = prophet_df[col].iloc[-1]
                future[col] = future[col].fillna(last_val)

    fc = model.predict(future)

    # Split into fitted and forecast
    n = len(prophet_df)
    fitted = fc["yhat"].values[:n]
    actual = prophet_df["y"].values
    residuals = actual - fitted

    fc_vals = fc["yhat"].values[n:]
    fc_lower = fc["yhat_lower"].values[n:]
    fc_upper = fc["yhat_upper"].values[n:]
    fc_dates = fc["ds"].values[n:]

    metrics = _compute_metrics(actual, fitted)
    if progress_cb:
        progress_cb(1.0, "Prophet complete")
    return _build_output(prophet_df["ds"].values, actual, fitted, fc_dates, fc_vals, fc_lower, fc_upper, residuals, metrics, {"changepoint_prior_scale": cps}, time.time() - t0, tuning_combinations=combinations_tested)


def train_holt_winters(df, date_col, target_col, horizon, progress_cb=None, **kw):
    t0 = time.time()
    if progress_cb:
        progress_cb(0.1, "Fitting Holt-Winters model...")
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    y = df[target_col].values
    dates = df[date_col].values
    freq = pd.infer_freq(df[date_col]) or "D"
    sp = {"D": 7, "W": 52, "MS": 12, "QS": 4}.get(freq, 7)
    sp = min(sp, len(y) // 3)

    auto_tune = kw.get("auto_tune", False)
    best_aic = np.inf
    # FIX Bug 8: Initialize result = None before branching to prevent UnboundLocalError
    result = None
    best_trend, best_seasonal = "add", "add"
    combinations_tested = None

    if auto_tune and sp >= 2 and len(y) >= 2 * sp:
        combinations_tested = 0
        if progress_cb: progress_cb(0.4, "Auto-tuning Holt-Winters grid...")
        for t in ["add", "mul"]:
            for s in ["add", "mul"]:
                try:
                    combinations_tested += 1
                    m = ExponentialSmoothing(y, trend=t, seasonal=s, seasonal_periods=sp)
                    r = m.fit(optimized=True)
                    if r.aic < best_aic:
                        best_aic = r.aic
                        result = r
                        best_trend, best_seasonal = t, s
                except Exception as e:
                    warnings.warn(f"Holt-Winters(trend={t}, seasonal={s}) failed: {e}")
                    continue

    if not auto_tune or result is None:
        try:
            if sp >= 2 and len(y) >= 2 * sp:
                model = ExponentialSmoothing(y, trend="add", seasonal="add", seasonal_periods=sp)
            else:
                model = ExponentialSmoothing(y, trend="add", seasonal=None)
            result = model.fit(optimized=True)
        except Exception as e:
            warnings.warn(f"Holt-Winters with seasonal failed ({e}), falling back to trend-only")
            model = ExponentialSmoothing(y, trend="add", seasonal=None)
            result = model.fit(optimized=True)

    fitted = result.fittedvalues
    residuals = y - fitted
    fc_vals = result.forecast(horizon)
    last_date = pd.to_datetime(df[date_col]).values[-1]
    fc_dates = pd.date_range(start=last_date, periods=horizon + 1, freq=freq)[1:]

    # FIX Bug 11: Widen CI with horizon (uncertainty grows with sqrt of step)
    std = np.std(residuals)
    steps = np.arange(1, horizon + 1)
    ci_width = 1.96 * std * np.sqrt(steps)
    lower = fc_vals - ci_width
    upper = fc_vals + ci_width

    metrics = _compute_metrics(y, fitted, aic=result.aic, bic=result.bic)
    if progress_cb:
        progress_cb(1.0, "Holt-Winters complete")
    return _build_output(dates, y, fitted, fc_dates, fc_vals, lower, upper, residuals, metrics, {"trend": best_trend, "seasonal": best_seasonal, "seasonal_periods": sp}, time.time() - t0, tuning_combinations=combinations_tested)


def _inverse_transform_col0(scaler: MinMaxScaler, scaled_vals: np.ndarray, num_features: int) -> np.ndarray:
    """
    FIX Bug 2 & 3: Correctly inverse-transform only the first feature (target column)
    from a multi-feature MinMaxScaler using sklearn's own inverse_transform.
    """
    dummy = np.zeros((len(scaled_vals), num_features))
    dummy[:, 0] = scaled_vals
    return scaler.inverse_transform(dummy)[:, 0]


def train_lstm(df, date_col, target_col, horizon, exog_cols=None, progress_cb=None, **kw):
    t0 = time.time()
    if progress_cb:
        progress_cb(0.05, "Building LSTM model...")

    if exog_cols and len(exog_cols) > 0:
        y_data = df[[target_col] + exog_cols].values
    else:
        y_data = df[[target_col]].values

    dates = df[date_col].values
    scaler = MinMaxScaler()

    auto_tune = kw.get("auto_tune", False)
    train_len = int(len(y_data) * 0.8)
    scaler.fit(y_data[:train_len])
    y_scaled = scaler.transform(y_data)

    look_back = min(30, len(y_data) // 4)
    if look_back < 3:
        look_back = 3

    num_features = y_data.shape[1]

    def _create_lstm():
        m = tf.keras.Sequential([
            tf.keras.layers.LSTM(64, return_sequences=True, input_shape=(look_back, num_features)),
            tf.keras.layers.Dropout(0.2),
            tf.keras.layers.LSTM(32),
            tf.keras.layers.Dropout(0.2),
            tf.keras.layers.Dense(1)
        ])
        m.compile(optimizer="adam", loss="mse")
        return m

    X, Y = [], []
    for i in range(look_back, len(y_scaled)):
        X.append(y_scaled[i - look_back:i, :])
        Y.append(y_scaled[i, 0])
    X, Y = np.array(X), np.array(Y)

    model = _create_lstm()
    hp = kw.get("hyperparameters", {})

    callbacks = []
    best_epochs = int(hp.get("lstm_epochs", 50))

    if auto_tune:
        epochs = 200  # Max epochs for early stopping
        early_stop = tf.keras.callbacks.EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True)
        callbacks.append(early_stop)

        # FIX Bug 12: Use simple 80% split of X for correct train/val alignment
        split_idx = int(len(X) * 0.8)
        X_train, X_val = X[:split_idx], X[split_idx:]
        Y_train, Y_val = Y[:split_idx], Y[split_idx:]

        class EpochProgressCallback(tf.keras.callbacks.Callback):
            def on_epoch_end(self, epoch, logs=None):
                if progress_cb:
                    val_loss = logs.get('val_loss', logs.get('loss', 0))
                    p = 0.1 + (0.3 * min(epoch + 1, epochs) / epochs)
                    progress_cb(p, f"Auto-Tune: Epoch {epoch+1} (Val Loss: {val_loss:.4f})", {"loss": val_loss, "epoch": epoch+1})
        callbacks.append(EpochProgressCallback())

        if progress_cb: progress_cb(0.1, "Auto-tuning LSTM (Early Stopping)...")
        if len(X_val) > 0:
            model.fit(X_train, Y_train, validation_data=(X_val, Y_val), epochs=epochs, batch_size=32, verbose=0, callbacks=callbacks)
            stopped_epoch = early_stop.stopped_epoch
            best_epochs = max(1, stopped_epoch - early_stop.patience + 1) if stopped_epoch > 0 else epochs
        else:
            model.fit(X, Y, epochs=epochs, batch_size=32, verbose=0, callbacks=callbacks)
            best_epochs = epochs
            
        if progress_cb: progress_cb(0.4, f"Auto-tune complete. Refitting on full data for {best_epochs} epochs...")
        
        # Refit on FULL data using the validated architecture
        # Do NOT refit the scaler to prevent data leakage (use the one fitted on train_len)
        y_scaled = scaler.transform(y_data)
        X, Y = [], []
        for i in range(look_back, len(y_scaled)):
            X.append(y_scaled[i - look_back:i, :])
            Y.append(y_scaled[i, 0])
        X, Y = np.array(X), np.array(Y)
        model = _create_lstm()
        
        class RefitProgressCallback(tf.keras.callbacks.Callback):
            def on_epoch_end(self, epoch, logs=None):
                if progress_cb:
                    loss = logs.get('loss', 0)
                    p = 0.4 + (0.3 * (epoch + 1) / best_epochs)
                    progress_cb(p, f"Refitting: Epoch {epoch+1}/{best_epochs} (Loss: {loss:.4f})", {"loss": loss, "epoch": epoch+1})
        model.fit(X, Y, epochs=best_epochs, batch_size=32, verbose=0, callbacks=[RefitProgressCallback()])
    else:
        if progress_cb:
            progress_cb(0.2, f"Training LSTM ({best_epochs} epochs)...")

        class EpochProgressCallback(tf.keras.callbacks.Callback):
            def on_epoch_end(self, epoch, logs=None):
                if progress_cb:
                    loss = logs.get('loss', 0)
                    p = 0.2 + (0.5 * (epoch + 1) / best_epochs)
                    progress_cb(p, f"Epoch {epoch+1}/{best_epochs} (Loss: {loss:.4f})", {"loss": loss, "epoch": epoch+1})
        callbacks.append(EpochProgressCallback())
        model.fit(X, Y, epochs=best_epochs, batch_size=32, verbose=0, callbacks=callbacks)

    if progress_cb:
        progress_cb(0.7, "Generating predictions...")

    pred_scaled = model.predict(X, verbose=0).flatten()

    # FIX Bug 2: Use correct inverse_transform via helper
    predicted = _inverse_transform_col0(scaler, pred_scaled, num_features)

    actual = y_data[look_back:, 0]
    residuals = actual - predicted

    # Forecast
    last_seq = y_scaled[-look_back:].reshape(1, look_back, num_features)
    fc_scaled = []

    exog_drifts = []
    if exog_cols and len(exog_cols) > 0:
        for ex_idx in range(1, num_features):
            ex_data = y_scaled[:, ex_idx]
            slope = (ex_data[-1] - ex_data[0]) / max(1, len(ex_data))
            exog_drifts.append(slope)

    for _ in range(horizon):
        next_val = model.predict(last_seq, verbose=0)[0, 0]
        fc_scaled.append(next_val)

        next_input = np.zeros(num_features)
        next_input[0] = next_val
        if num_features > 1:
            for ex_idx in range(1, num_features):
                next_input[ex_idx] = last_seq[0, -1, ex_idx] + exog_drifts[ex_idx-1]

        last_seq = np.roll(last_seq, -1, axis=1)
        last_seq[0, -1, :] = next_input

    fc_vals = _inverse_transform_col0(scaler, np.array(fc_scaled), num_features)

    # FIX Bug 11: Widen CI with horizon (uncertainty grows with sqrt of step)
    std = np.std(residuals) if len(residuals) > 0 else 0
    steps = np.arange(1, horizon + 1)
    ci_width = 1.96 * std * np.sqrt(steps)
    lower = fc_vals - ci_width
    upper = fc_vals + ci_width

    freq = pd.infer_freq(df[date_col]) or "D"
    last_date = pd.to_datetime(df[date_col]).values[-1]
    fc_dates = pd.date_range(start=last_date, periods=horizon + 1, freq=freq)[1:]

    fitted_full = np.full(len(y_data), np.nan)
    fitted_full[look_back:] = predicted
    metrics = _compute_metrics(actual, predicted)
    if progress_cb:
        progress_cb(1.0, "LSTM complete")
        
    # FIX: Clear TensorFlow session to prevent memory leaks in Celery worker
    tf.keras.backend.clear_session()
    
    return _build_output(dates, y_data[:, 0], fitted_full, fc_dates, fc_vals, lower, upper, residuals, metrics, {"look_back": look_back, "epochs": epochs, "units": "64,32", "exog_features": len(exog_cols) if exog_cols else 0}, time.time() - t0)


def train_transformer(df, date_col, target_col, horizon, exog_cols=None, progress_cb=None, **kw):
    t0 = time.time()
    if progress_cb:
        progress_cb(0.05, "Building Transformer model...")

    if exog_cols and len(exog_cols) > 0:
        y_data = df[[target_col] + exog_cols].values
    else:
        y_data = df[[target_col]].values

    dates = df[date_col].values
    scaler = MinMaxScaler()

    auto_tune = kw.get("auto_tune", False)
    train_len = int(len(y_data) * 0.8)
    scaler.fit(y_data[:train_len])
    y_scaled = scaler.transform(y_data)

    look_back = min(30, len(y_data) // 4)
    if look_back < 3:
        look_back = 3

    num_features = y_data.shape[1]

    def _create_transformer():
        # FIX Bug 4: Proper sinusoidal positional encoding instead of bare Dense
        inputs = tf.keras.Input(shape=(look_back, num_features))
        # Project input to model dimension
        proj = tf.keras.layers.Dense(32)(inputs)
        # Sinusoidal positional encoding (computed as a layer)
        positions = tf.cast(tf.range(look_back), dtype=tf.float32)
        dims = tf.cast(tf.range(0, 32, 2), dtype=tf.float32)
        angles = positions[:, tf.newaxis] / tf.pow(10000.0, dims[tf.newaxis, :] / 32.0)
        sin_enc = tf.math.sin(angles)
        cos_enc = tf.math.cos(angles)
        # Interleave sin/cos to produce (look_back, 32) positional encoding
        pos_enc = tf.reshape(
            tf.stack([sin_enc, cos_enc], axis=-1),
            (look_back, 32)
        )
        pos = tf.keras.layers.Lambda(lambda x: x + pos_enc)(proj)

        # Multi-head attention with proper residual connections
        attn = tf.keras.layers.MultiHeadAttention(num_heads=2, key_dim=16)(pos, pos)
        attn = tf.keras.layers.LayerNormalization()(attn + pos)
        ff = tf.keras.layers.Dense(64, activation="relu")(attn)
        ff = tf.keras.layers.Dense(32)(ff)
        ff = tf.keras.layers.LayerNormalization()(ff + attn)
        flat = tf.keras.layers.GlobalAveragePooling1D()(ff)
        flat = tf.keras.layers.Dropout(0.2)(flat)
        out = tf.keras.layers.Dense(1)(flat)
        model = tf.keras.Model(inputs, out)
        model.compile(optimizer="adam", loss="mse")
        return model

    X, Y = [], []
    for i in range(look_back, len(y_scaled)):
        X.append(y_scaled[i - look_back:i, :])
        Y.append(y_scaled[i, 0])
    X, Y = np.array(X), np.array(Y)

    model = _create_transformer()
    hp = kw.get("hyperparameters", {})

    callbacks = []
    best_epochs = int(hp.get("transformer_epochs", hp.get("lstm_epochs", 50)))

    if auto_tune:
        epochs = 200
        early_stop = tf.keras.callbacks.EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True)
        callbacks.append(early_stop)

        # FIX Bug 12: Use simple 80% split of X for correct train/val alignment
        split_idx = int(len(X) * 0.8)
        X_train, X_val = X[:split_idx], X[split_idx:]
        Y_train, Y_val = Y[:split_idx], Y[split_idx:]

        class EpochProgressCallback(tf.keras.callbacks.Callback):
            def on_epoch_end(self, epoch, logs=None):
                if progress_cb:
                    val_loss = logs.get('val_loss', logs.get('loss', 0))
                    p = 0.1 + (0.3 * min(epoch + 1, epochs) / epochs)
                    progress_cb(p, f"Auto-Tune: Epoch {epoch+1} (Val Loss: {val_loss:.4f})", {"loss": val_loss, "epoch": epoch+1})
        callbacks.append(EpochProgressCallback())

        if progress_cb: progress_cb(0.1, "Auto-tuning Transformer (Early Stopping)...")
        if len(X_val) > 0:
            model.fit(X_train, Y_train, validation_data=(X_val, Y_val), epochs=epochs, batch_size=32, verbose=0, callbacks=callbacks)
            stopped_epoch = early_stop.stopped_epoch
            best_epochs = max(1, stopped_epoch - early_stop.patience + 1) if stopped_epoch > 0 else epochs
        else:
            model.fit(X, Y, epochs=epochs, batch_size=32, verbose=0, callbacks=callbacks)
            best_epochs = epochs
            
        if progress_cb: progress_cb(0.4, f"Auto-tune complete. Refitting on full data for {best_epochs} epochs...")
        
        # Refit on FULL data using the validated architecture
        # Do NOT refit the scaler to prevent data leakage (use the one fitted on train_len)
        y_scaled = scaler.transform(y_data)
        X, Y = [], []
        for i in range(look_back, len(y_scaled)):
            X.append(y_scaled[i - look_back:i, :])
            Y.append(y_scaled[i, 0])
        X, Y = np.array(X), np.array(Y)
        model = _create_transformer()
        
        class RefitProgressCallback(tf.keras.callbacks.Callback):
            def on_epoch_end(self, epoch, logs=None):
                if progress_cb:
                    loss = logs.get('loss', 0)
                    p = 0.4 + (0.3 * (epoch + 1) / best_epochs)
                    progress_cb(p, f"Refitting: Epoch {epoch+1}/{best_epochs} (Loss: {loss:.4f})", {"loss": loss, "epoch": epoch+1})
        model.fit(X, Y, epochs=best_epochs, batch_size=32, verbose=0, callbacks=[RefitProgressCallback()])
    else:
        # FIX Bug 10: Support dedicated transformer_epochs hp key, fallback to lstm_epochs for compat
        if progress_cb:
            progress_cb(0.2, f"Training Transformer ({best_epochs} epochs)...")

        class EpochProgressCallback(tf.keras.callbacks.Callback):
            def on_epoch_end(self, epoch, logs=None):
                if progress_cb:
                    loss = logs.get('loss', 0)
                    p = 0.2 + (0.5 * (epoch + 1) / best_epochs)
                    progress_cb(p, f"Epoch {epoch+1}/{best_epochs} (Loss: {loss:.4f})", {"loss": loss, "epoch": epoch+1})
        callbacks.append(EpochProgressCallback())
        model.fit(X, Y, epochs=best_epochs, batch_size=32, verbose=0, callbacks=callbacks)

    if progress_cb:
        progress_cb(0.7, "Generating predictions...")

    pred_scaled = model.predict(X, verbose=0).flatten()

    # FIX Bug 3: Use correct inverse_transform via helper
    predicted = _inverse_transform_col0(scaler, pred_scaled, num_features)

    actual = y_data[look_back:, 0]
    residuals = actual - predicted

    last_seq = y_scaled[-look_back:].reshape(1, look_back, num_features)
    fc_scaled = []

    exog_drifts = []
    if exog_cols and len(exog_cols) > 0:
        for ex_idx in range(1, num_features):
            ex_data = y_scaled[:, ex_idx]
            slope = (ex_data[-1] - ex_data[0]) / max(1, len(ex_data))
            exog_drifts.append(slope)

    for _ in range(horizon):
        nv = model.predict(last_seq, verbose=0)[0, 0]
        fc_scaled.append(nv)

        next_input = np.zeros(num_features)
        next_input[0] = nv
        if num_features > 1:
            for ex_idx in range(1, num_features):
                next_input[ex_idx] = last_seq[0, -1, ex_idx] + exog_drifts[ex_idx-1]

        last_seq = np.roll(last_seq, -1, axis=1)
        last_seq[0, -1, :] = next_input

    fc_vals = _inverse_transform_col0(scaler, np.array(fc_scaled), num_features)

    # FIX Bug 11: Widen CI with horizon (uncertainty grows with sqrt of step)
    std = np.std(residuals) if len(residuals) > 0 else 0
    steps = np.arange(1, horizon + 1)
    ci_width = 1.96 * std * np.sqrt(steps)
    lower = fc_vals - ci_width
    upper = fc_vals + ci_width

    freq = pd.infer_freq(df[date_col]) or "D"
    last_date = pd.to_datetime(df[date_col]).values[-1]
    fc_dates = pd.date_range(start=last_date, periods=horizon + 1, freq=freq)[1:]

    fitted_full = np.full(len(y_data), np.nan)
    fitted_full[look_back:] = predicted
    metrics = _compute_metrics(actual, predicted)
    if progress_cb:
        progress_cb(1.0, "Transformer complete")
        
    # FIX: Clear TensorFlow session to prevent memory leaks in Celery worker
    tf.keras.backend.clear_session()
    
    return _build_output(dates, y_data[:, 0], fitted_full, fc_dates, fc_vals, lower, upper, residuals, metrics, {"look_back": look_back, "heads": 2, "key_dim": 16, "epochs": epochs, "exog_features": len(exog_cols) if exog_cols else 0}, time.time() - t0)


MODEL_REGISTRY = {
    "ARIMA": train_arima,
    "SARIMA": train_sarima,
    "ARIMAX": train_arimax,
    "Prophet": train_prophet,
    "Holt-Winters": train_holt_winters,
    "LSTM": train_lstm,
    "Transformer": train_transformer,
}
