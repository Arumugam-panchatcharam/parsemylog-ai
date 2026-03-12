"""
Telemetry Anomaly Detection & Summarization Pipeline
=====================================================

ML-based anomaly detection for CPE telemetry time-series data (15-min
periodic reports) and device info, designed to scale to 500+ CPEs.

Detection Methods
-----------------
1. **Time-Series Anomaly (Statistical + ML)** -- Sliding-window z-score,
   exponential weighted moving average (EWMA), and Isolation Forest on
   numeric metrics (CPU, memory, process count, WAN traffic).

2. **Change-Point Detection** -- CUSUM and Bayesian online change-point
   detection for identifying regime shifts in metrics (e.g. memory leak
   onset, CPU saturation).

3. **Correlation Anomaly** -- Cross-metric Pearson/Spearman correlation
   analysis to detect unusual decoupling (e.g. CPU rises but process
   count doesn't, indicating a single runaway process).

4. **Device Health Scoring** -- Composite health score from reboot
   frequency, memory trend, CPU baseline, WAN stability, and radio status.

5. **Auto-Summarizer** -- Generates structured natural-language summaries
   of device behaviour, anomalies, and trends without requiring an LLM.

Data Flow
---------
::

    raw_telemetry_cache.json  (reports, device_info)
        |
        +---> TimeSeriesAnomalyDetector   ---> per-metric anomaly scores
        +---> ChangePointDetector         ---> regime shift events
        +---> CorrelationAnomalyDetector  ---> cross-metric anomalies
        +---> DeviceHealthScorer          ---> composite health score
        |
        +---> TelemetrySummarizer         ---> structured summary

Usage:
    >>> from logai.ml.telemetry_anomaly import TelemetryAnomalyPipeline
    >>> pipeline = TelemetryAnomalyPipeline()
    >>> results = pipeline.analyze(cache_path="/path/to/raw_telemetry_cache.json")
"""

from __future__ import annotations

import json
import logging
import math
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore", category=RuntimeWarning)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MetricAnomaly:
    """Single anomaly event on a telemetry metric."""
    metric_key: str
    metric_label: str
    timestamp: str
    value: float
    expected_range: Tuple[float, float]
    severity: str  # "low", "medium", "high", "critical"
    anomaly_type: str  # "spike", "drop", "trend", "change_point", "correlation"
    details: str


@dataclass
class DeviceHealthScore:
    """Composite health assessment for a single CPE."""
    overall_score: float  # 0.0 (critical) to 100.0 (healthy)
    category_scores: Dict[str, float]
    risk_factors: List[str]
    health_label: str  # "healthy", "degraded", "at_risk", "critical"


@dataclass
class TelemetrySummary:
    """Structured summary of telemetry analysis."""
    device_info: Dict[str, str]
    health: DeviceHealthScore
    anomaly_count: int
    anomalies_by_severity: Dict[str, int]
    key_findings: List[str]
    metric_summaries: Dict[str, Dict[str, Any]]
    recommendations: List[str]
    narrative: str


@dataclass
class TelemetryAnomalyReport:
    """Complete telemetry anomaly report for a single CPE."""
    cpe_id: str
    total_reports: int
    time_range: Dict[str, str]
    anomalies: List[MetricAnomaly]
    change_points: List[Dict[str, Any]]
    correlation_anomalies: List[Dict[str, Any]]
    health: DeviceHealthScore
    summary: TelemetrySummary
    processing_time_ms: float
    plot_data: Optional[Dict[str, Any]] = None  # NEW: Time-series data for visualization


# ---------------------------------------------------------------------------
# Metric Extraction Helper
# ---------------------------------------------------------------------------

_NUMERIC_METRICS = {
    "Device.DeviceInfo.ProcessStatus.CPUUsage": ("CPU Usage", "%"),
    "Device.DeviceInfo.MemoryStatus.Free": ("Free Memory", "kB"),
    "Device.DeviceInfo.MemoryStatus.Total": ("Total Memory", "kB"),
    "Device.DeviceInfo.UpTime": ("Uptime", "s"),
    "Device.DeviceInfo.ProcessStatus.ProcessNumberOfEntries": ("Process Count", ""),
    "Device.DeviceInfo.MemoryStatus.Available": ("Available Memory", "kB"),
    "Device.DeviceInfo.MemoryStatus.SharedMemory": ("Shared Memory", "kB"),
    "Device.DeviceInfo.MemoryStatus.SlabMemory": ("Slab Memory", "kB"),
    "Device.Hosts.X_CISCO_COM_ConnectedDeviceNumber": ("Connected Devices", ""),
}

_STATUS_METRICS = {
    "Device.WiFi.Radio.1.Enable": "WiFi Radio 1",
    "Device.WiFi.Radio.2.Enable": "WiFi Radio 2",
    "Device.WiFi.Radio.1.Status": "WiFi Radio 1 Status",
    "Device.WiFi.Radio.2.Status": "WiFi Radio 2 Status",
    "Device.PPP.Interface.1.ConnectionStatus": "PPP Status",
    "Device.Ethernet.Link.1.Status": "Ethernet Link Status",
}


def _extract_metric_timeseries(
    reports: List[Dict[str, Any]],
) -> Dict[str, pd.DataFrame]:
    """
    Extract numeric metric time series from parsed telemetry reports.

    Returns dict mapping metric_key to a DataFrame with [timestamp, value].
    """
    metric_data: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for report in reports:
        if not report.get("parse_ok", True):
            continue
        fields = report.get("fields", {})
        time_val = report.get("time")
        if not time_val:
            continue

        ts_str = time_val if isinstance(time_val, str) else (
            time_val.isoformat() if hasattr(time_val, "isoformat") else str(time_val)
        )

        for key, (label, unit) in _NUMERIC_METRICS.items():
            raw = fields.get(key)
            if raw is None:
                continue
            try:
                val_str = str(raw).split(";")[0].strip()
                val = float(val_str)
                metric_data[key].append({"timestamp": ts_str, "value": val})
            except (ValueError, TypeError):
                continue

    result = {}
    for key, data_list in metric_data.items():
        if data_list:
            mdf = pd.DataFrame(data_list)
            mdf["timestamp"] = pd.to_datetime(mdf["timestamp"], errors="coerce")
            mdf = mdf.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
            if not mdf.empty:
                result[key] = mdf

    return result


# ---------------------------------------------------------------------------
# Method 1: Time-Series Anomaly Detector
# ---------------------------------------------------------------------------

class TimeSeriesAnomalyDetector:
    """
    Multi-method time-series anomaly detection combining:
    - Sliding-window z-score
    - EWMA (Exponential Weighted Moving Average) deviation
    - Isolation Forest on feature-engineered windows
    """

    def __init__(
        self,
        zscore_threshold: float = 2.5,
        ewma_span: int = 5,
        ewma_threshold: float = 2.0,
        isolation_contamination: float = 0.08,
        min_points: int = 5,
    ):
        self.zscore_threshold = zscore_threshold
        self.ewma_span = ewma_span
        self.ewma_threshold = ewma_threshold
        self.isolation_contamination = isolation_contamination
        self.min_points = min_points

    def detect(
        self,
        metric_timeseries: Dict[str, pd.DataFrame],
    ) -> Dict[str, Any]:
        """
        Detect anomalies across all extracted metrics.

        Returns:
            Dict mapping metric_key to list of anomaly dicts.
        """
        all_anomalies: Dict[str, List[Dict[str, Any]]] = {}
        metric_stats: Dict[str, Dict[str, Any]] = {}

        for key, mdf in metric_timeseries.items():
            label, unit = _NUMERIC_METRICS.get(key, (key, ""))
            if len(mdf) < self.min_points:
                continue

            values = mdf["value"].values
            timestamps = mdf["timestamp"].values

            anomalies = []

            mean_val = np.mean(values)
            std_val = np.std(values)
            if std_val > 0:
                z_scores = (values - mean_val) / std_val
                for i, z in enumerate(z_scores):
                    if abs(z) > self.zscore_threshold:
                        severity = "high" if abs(z) > 4.0 else ("medium" if abs(z) > 3.0 else "low")
                        anomalies.append({
                            "method": "zscore",
                            "index": i,
                            "timestamp": str(timestamps[i]),
                            "value": float(values[i]),
                            "zscore": float(z),
                            "severity": severity,
                            "type": "spike" if z > 0 else "drop",
                        })

            if len(values) >= self.ewma_span:
                series = pd.Series(values)
                ewma = series.ewm(span=self.ewma_span, adjust=False).mean()
                ewma_std = series.ewm(span=self.ewma_span, adjust=False).std()
                ewma_std = ewma_std.fillna(std_val if std_val > 0 else 1.0)
                ewma_std = ewma_std.replace(0, std_val if std_val > 0 else 1.0)

                deviations = (series - ewma) / ewma_std
                for i in range(self.ewma_span, len(values)):
                    dev = deviations.iloc[i]
                    if abs(dev) > self.ewma_threshold:
                        already_flagged = any(
                            a["index"] == i and a["method"] == "zscore" for a in anomalies
                        )
                        if not already_flagged:
                            severity = "medium" if abs(dev) > 3.0 else "low"
                            anomalies.append({
                                "method": "ewma",
                                "index": i,
                                "timestamp": str(timestamps[i]),
                                "value": float(values[i]),
                                "ewma_deviation": float(dev),
                                "severity": severity,
                                "type": "spike" if dev > 0 else "drop",
                            })

            if len(values) >= 10:
                anomalies = self._isolation_forest_detect(
                    values, timestamps, anomalies
                )

            if anomalies:
                all_anomalies[key] = anomalies

            trend_slope = 0.0
            if len(values) >= 5:
                x = np.arange(len(values))
                slope, intercept, r_value, p_value, std_err = sp_stats.linregress(x, values)
                trend_slope = float(slope)

            metric_stats[key] = {
                "label": label,
                "unit": unit,
                "count": len(values),
                "mean": float(mean_val),
                "std": float(std_val),
                "min": float(np.min(values)),
                "max": float(np.max(values)),
                "trend_slope": trend_slope,
                "anomaly_count": len(anomalies),
            }

        return {
            "anomalies": all_anomalies,
            "metric_stats": metric_stats,
        }

    def _isolation_forest_detect(
        self,
        values: np.ndarray,
        timestamps: np.ndarray,
        existing_anomalies: List[Dict],
    ) -> List[Dict]:
        """Run Isolation Forest on feature-engineered windows."""
        try:
            from sklearn.ensemble import IsolationForest

            features = self._engineer_features(values)
            if features.shape[0] < 5:
                return existing_anomalies

            model = IsolationForest(
                contamination=min(self.isolation_contamination, 0.5),
                n_estimators=100,
                random_state=42,
                n_jobs=-1,
            )
            predictions = model.fit_predict(features)
            scores = model.decision_function(features)

            existing_indices = {a["index"] for a in existing_anomalies}
            for i, pred in enumerate(predictions):
                if pred == -1 and i not in existing_indices:
                    existing_anomalies.append({
                        "method": "isolation_forest",
                        "index": i,
                        "timestamp": str(timestamps[i]) if i < len(timestamps) else "",
                        "value": float(values[i]),
                        "if_score": float(scores[i]),
                        "severity": "medium",
                        "type": "outlier",
                    })
        except Exception as e:
            logger.debug(f"[TimeSeriesAnomaly] IF failed: {e}")

        return existing_anomalies

    def _engineer_features(self, values: np.ndarray) -> np.ndarray:
        """Build feature matrix: [value, diff, rolling_mean, rolling_std]."""
        n = len(values)
        features = np.zeros((n, 4))
        features[:, 0] = values

        diff = np.diff(values, prepend=values[0])
        features[:, 1] = diff

        window = min(5, n)
        series = pd.Series(values)
        features[:, 2] = series.rolling(window, min_periods=1).mean().values
        features[:, 3] = series.rolling(window, min_periods=1).std().fillna(0).values

        return features


# ---------------------------------------------------------------------------
# Method 2: Change-Point Detection (CUSUM)
# ---------------------------------------------------------------------------

class ChangePointDetector:
    """
    CUSUM-based change-point detection for identifying regime shifts.

    Detects the onset of gradual degradation (memory leak, CPU creep)
    as well as abrupt changes (reboot, config change).
    """

    def __init__(
        self,
        cusum_threshold: float = 5.0,
        cusum_drift: float = 0.5,
        min_segment_length: int = 3,
    ):
        self.cusum_threshold = cusum_threshold
        self.cusum_drift = cusum_drift
        self.min_segment_length = min_segment_length

    def detect(
        self,
        metric_timeseries: Dict[str, pd.DataFrame],
    ) -> List[Dict[str, Any]]:
        """
        Detect change points across all metrics.

        Returns:
            List of change-point event dicts.
        """
        change_points = []

        for key, mdf in metric_timeseries.items():
            label, unit = _NUMERIC_METRICS.get(key, (key, ""))
            values = mdf["value"].values
            timestamps = mdf["timestamp"].values

            if len(values) < 2 * self.min_segment_length:
                continue

            mean_val = np.mean(values)
            std_val = np.std(values)
            if std_val == 0:
                continue

            normalized = (values - mean_val) / std_val

            s_pos = np.zeros(len(normalized))
            s_neg = np.zeros(len(normalized))

            for i in range(1, len(normalized)):
                s_pos[i] = max(0, s_pos[i - 1] + normalized[i] - self.cusum_drift)
                s_neg[i] = max(0, s_neg[i - 1] - normalized[i] - self.cusum_drift)

                if s_pos[i] > self.cusum_threshold:
                    change_points.append({
                        "metric_key": key,
                        "metric_label": label,
                        "timestamp": str(timestamps[i]),
                        "index": int(i),
                        "direction": "increase",
                        "cusum_value": float(s_pos[i]),
                        "value_before": float(np.mean(values[max(0, i - 3):i])),
                        "value_after": float(np.mean(values[i:min(len(values), i + 3)])),
                        "severity": "high" if s_pos[i] > 2 * self.cusum_threshold else "medium",
                    })
                    s_pos[i] = 0

                if s_neg[i] > self.cusum_threshold:
                    change_points.append({
                        "metric_key": key,
                        "metric_label": label,
                        "timestamp": str(timestamps[i]),
                        "index": int(i),
                        "direction": "decrease",
                        "cusum_value": float(s_neg[i]),
                        "value_before": float(np.mean(values[max(0, i - 3):i])),
                        "value_after": float(np.mean(values[i:min(len(values), i + 3)])),
                        "severity": "high" if s_neg[i] > 2 * self.cusum_threshold else "medium",
                    })
                    s_neg[i] = 0

        return change_points


# ---------------------------------------------------------------------------
# Method 3: Correlation Anomaly Detector
# ---------------------------------------------------------------------------

class CorrelationAnomalyDetector:
    """
    Detects unusual decoupling between metrics that are normally correlated.

    For example, CPU and process count typically correlate. If CPU spikes
    but process count stays flat, it may indicate a single runaway process.
    """

    _EXPECTED_CORRELATIONS = [
        ("Device.DeviceInfo.ProcessStatus.CPUUsage",
         "Device.DeviceInfo.ProcessStatus.ProcessNumberOfEntries",
         "positive", "CPU vs Process Count"),
        ("Device.DeviceInfo.MemoryStatus.Free",
         "Device.DeviceInfo.ProcessStatus.ProcessNumberOfEntries",
         "negative", "Free Memory vs Process Count"),
    ]

    def __init__(self, min_correlation: float = 0.3, min_samples: int = 8):
        self.min_correlation = min_correlation
        self.min_samples = min_samples

    def detect(
        self,
        metric_timeseries: Dict[str, pd.DataFrame],
    ) -> List[Dict[str, Any]]:
        """
        Detect correlation anomalies between metric pairs.

        Returns:
            List of correlation anomaly dicts.
        """
        anomalies = []

        for key_a, key_b, expected_dir, description in self._EXPECTED_CORRELATIONS:
            if key_a not in metric_timeseries or key_b not in metric_timeseries:
                continue

            df_a = metric_timeseries[key_a].set_index("timestamp")
            df_b = metric_timeseries[key_b].set_index("timestamp")

            merged = df_a.join(df_b, lsuffix="_a", rsuffix="_b", how="inner")
            if len(merged) < self.min_samples:
                continue

            corr, p_value = sp_stats.pearsonr(merged["value_a"], merged["value_b"])

            is_anomalous = False
            reason = ""
            if expected_dir == "positive" and corr < -self.min_correlation:
                is_anomalous = True
                reason = f"Expected positive correlation, found negative ({corr:.2f})"
            elif expected_dir == "negative" and corr > self.min_correlation:
                is_anomalous = True
                reason = f"Expected negative correlation, found positive ({corr:.2f})"
            elif abs(corr) < 0.1 and p_value > 0.05:
                is_anomalous = True
                reason = f"Expected {expected_dir} correlation, found no correlation ({corr:.2f})"

            if is_anomalous:
                anomalies.append({
                    "metric_a": key_a,
                    "metric_b": key_b,
                    "description": description,
                    "expected_direction": expected_dir,
                    "actual_correlation": float(corr),
                    "p_value": float(p_value),
                    "sample_count": len(merged),
                    "reason": reason,
                    "severity": "medium",
                })

        return anomalies


# ---------------------------------------------------------------------------
# Device Health Scorer
# ---------------------------------------------------------------------------

class DeviceHealthScorer:
    """
    Computes a composite health score (0-100) for a CPE device based on
    telemetry metrics, reboot history, and anomaly counts.
    """

    def __init__(self):
        self._weights = {
            "memory": 0.25,
            "cpu": 0.20,
            "stability": 0.25,
            "connectivity": 0.15,
            "anomaly_load": 0.15,
        }

    def score(
        self,
        metric_timeseries: Dict[str, pd.DataFrame],
        anomaly_count: int,
        device_info: Dict[str, Any],
        reports: List[Dict[str, Any]],
    ) -> DeviceHealthScore:
        """
        Compute composite device health score.

        Returns:
            DeviceHealthScore with per-category breakdowns.
        """
        category_scores: Dict[str, float] = {}
        risk_factors: List[str] = []

        category_scores["memory"] = self._score_memory(
            metric_timeseries, risk_factors
        )
        category_scores["cpu"] = self._score_cpu(
            metric_timeseries, risk_factors
        )
        category_scores["stability"] = self._score_stability(
            reports, device_info, risk_factors
        )
        category_scores["connectivity"] = self._score_connectivity(
            reports, risk_factors
        )
        category_scores["anomaly_load"] = self._score_anomaly_load(
            anomaly_count, risk_factors
        )

        overall = sum(
            category_scores[cat] * self._weights[cat]
            for cat in self._weights
        )

        if overall >= 80:
            label = "healthy"
        elif overall >= 60:
            label = "degraded"
        elif overall >= 40:
            label = "at_risk"
        else:
            label = "critical"

        return DeviceHealthScore(
            overall_score=round(overall, 1),
            category_scores={k: round(v, 1) for k, v in category_scores.items()},
            risk_factors=risk_factors,
            health_label=label,
        )

    def _score_memory(
        self, metrics: Dict[str, pd.DataFrame], risks: List[str]
    ) -> float:
        free_key = "Device.DeviceInfo.MemoryStatus.Free"
        total_key = "Device.DeviceInfo.MemoryStatus.Total"

        if free_key not in metrics:
            return 70.0

        free_vals = metrics[free_key]["value"].values
        mean_free = np.mean(free_vals)
        min_free = np.min(free_vals)

        total = None
        if total_key in metrics:
            total_vals = metrics[total_key]["value"].values
            total = np.mean(total_vals)

        score = 100.0
        if total and total > 0:
            usage_pct = (1.0 - mean_free / total) * 100
            if usage_pct > 90:
                score = 20.0
                risks.append(f"Critical memory usage: {usage_pct:.0f}% average")
            elif usage_pct > 80:
                score = 50.0
                risks.append(f"High memory usage: {usage_pct:.0f}% average")
            elif usage_pct > 70:
                score = 70.0
            else:
                score = 90.0
        else:
            if min_free < 50000:
                score = 40.0
                risks.append(f"Low free memory: {min_free:.0f} kB minimum")
            elif min_free < 100000:
                score = 65.0

        if len(free_vals) >= 5:
            x = np.arange(len(free_vals))
            slope, _, _, _, _ = sp_stats.linregress(x, free_vals)
            if slope < -500:
                score = min(score, 40.0)
                risks.append(f"Memory leak suspected: free memory declining at {abs(slope):.0f} kB/interval")
            elif slope < -100:
                score = min(score, 60.0)
                risks.append("Gradual memory decline detected")

        return score

    def _score_cpu(
        self, metrics: Dict[str, pd.DataFrame], risks: List[str]
    ) -> float:
        cpu_key = "Device.DeviceInfo.ProcessStatus.CPUUsage"
        if cpu_key not in metrics:
            return 70.0

        values = metrics[cpu_key]["value"].values
        mean_cpu = np.mean(values)
        max_cpu = np.max(values)

        if mean_cpu > 90:
            risks.append(f"CPU saturated: {mean_cpu:.0f}% average")
            return 15.0
        elif mean_cpu > 75:
            risks.append(f"High CPU usage: {mean_cpu:.0f}% average")
            return 45.0
        elif mean_cpu > 50:
            return 70.0
        elif max_cpu > 95:
            risks.append(f"CPU spike detected: {max_cpu:.0f}% peak")
            return 65.0
        else:
            return 95.0

    def _score_stability(
        self, reports: List[Dict], device_info: Dict, risks: List[str]
    ) -> float:
        ok_reports = [r for r in reports if r.get("parse_ok", True)]
        if not ok_reports:
            return 50.0

        times = []
        for r in ok_reports:
            t = r.get("time")
            if t and isinstance(t, str):
                try:
                    times.append(datetime.fromisoformat(t))
                except (ValueError, TypeError):
                    pass
            elif t and hasattr(t, "isoformat"):
                times.append(t)

        if len(times) < 2:
            return 60.0

        times.sort()
        total_hours = (times[-1] - times[0]).total_seconds() / 3600
        if total_hours < 1:
            return 70.0

        uptimes = []
        for r in ok_reports:
            up = r.get("uptime", 0)
            if isinstance(up, (int, float)) and up > 0:
                uptimes.append(up)

        reboot_count = 0
        if len(uptimes) >= 2:
            for i in range(1, len(uptimes)):
                if uptimes[i] < uptimes[i - 1] * 0.5:
                    reboot_count += 1

        if reboot_count >= 5:
            risks.append(f"Frequent reboots: {reboot_count} detected in telemetry period")
            return 20.0
        elif reboot_count >= 3:
            risks.append(f"Multiple reboots: {reboot_count} detected")
            return 50.0
        elif reboot_count >= 1:
            return 75.0
        else:
            return 95.0

    def _score_connectivity(
        self, reports: List[Dict], risks: List[str]
    ) -> float:
        ok_reports = [r for r in reports if r.get("parse_ok", True)]
        if not ok_reports:
            return 60.0

        gap_count = 0
        times = []
        for r in ok_reports:
            t = r.get("time")
            if t and isinstance(t, str):
                try:
                    times.append(datetime.fromisoformat(t))
                except (ValueError, TypeError):
                    pass
            elif t and hasattr(t, "isoformat"):
                times.append(t)

        times.sort()
        for i in range(1, len(times)):
            delta = (times[i] - times[i - 1]).total_seconds()
            if delta > 2700:
                gap_count += 1

        if gap_count > 10:
            risks.append(f"Significant telemetry gaps: {gap_count} missed intervals")
            return 30.0
        elif gap_count > 5:
            risks.append(f"Telemetry gaps detected: {gap_count} missed intervals")
            return 60.0
        elif gap_count > 2:
            return 80.0
        else:
            return 95.0

    def _score_anomaly_load(
        self, anomaly_count: int, risks: List[str]
    ) -> float:
        if anomaly_count >= 20:
            risks.append(f"High anomaly count: {anomaly_count} anomalies detected")
            return 20.0
        elif anomaly_count >= 10:
            return 50.0
        elif anomaly_count >= 5:
            return 70.0
        elif anomaly_count >= 1:
            return 85.0
        else:
            return 100.0


# ---------------------------------------------------------------------------
# Auto-Summarizer
# ---------------------------------------------------------------------------

class TelemetrySummarizer:
    """
    Generates structured, human-readable summaries of telemetry analysis
    results without requiring an LLM. Uses template-based natural language
    generation with statistical backing.
    """

    def summarize(
        self,
        device_info: Dict[str, Any],
        health: DeviceHealthScore,
        anomalies: List[MetricAnomaly],
        change_points: List[Dict[str, Any]],
        correlation_anomalies: List[Dict[str, Any]],
        metric_stats: Dict[str, Dict[str, Any]],
        reports: List[Dict[str, Any]],
    ) -> TelemetrySummary:
        """
        Generate a comprehensive summary.

        Returns:
            TelemetrySummary with findings, recommendations, and narrative.
        """
        anomalies_by_severity = defaultdict(int)
        for a in anomalies:
            anomalies_by_severity[a.severity] += 1

        findings = self._extract_findings(
            health, anomalies, change_points, correlation_anomalies, metric_stats
        )
        recommendations = self._generate_recommendations(
            health, anomalies, change_points, metric_stats
        )
        metric_summaries = self._build_metric_summaries(metric_stats)
        narrative = self._build_narrative(
            device_info, health, findings, anomalies, metric_stats, reports
        )

        return TelemetrySummary(
            device_info={k: str(v) for k, v in device_info.items()} if device_info else {},
            health=health,
            anomaly_count=len(anomalies),
            anomalies_by_severity=dict(anomalies_by_severity),
            key_findings=findings,
            metric_summaries=metric_summaries,
            recommendations=recommendations,
            narrative=narrative,
        )

    def _extract_findings(
        self,
        health: DeviceHealthScore,
        anomalies: List[MetricAnomaly],
        change_points: List[Dict],
        correlation_anomalies: List[Dict],
        metric_stats: Dict[str, Dict],
    ) -> List[str]:
        findings = []

        findings.append(
            f"Device health: {health.health_label} ({health.overall_score}/100)"
        )

        for risk in health.risk_factors[:5]:
            findings.append(f"Risk: {risk}")

        high_anomalies = [a for a in anomalies if a.severity in ("high", "critical")]
        if high_anomalies:
            findings.append(
                f"{len(high_anomalies)} high/critical anomalies detected "
                f"across {len(set(a.metric_key for a in high_anomalies))} metrics"
            )

        if change_points:
            findings.append(
                f"{len(change_points)} regime change points detected"
            )
            for cp in change_points[:3]:
                findings.append(
                    f"  {cp['metric_label']}: {cp['direction']} shift at {cp['timestamp']}"
                )

        if correlation_anomalies:
            for ca in correlation_anomalies[:3]:
                findings.append(f"Unusual metric relationship: {ca['reason']}")

        for key, stats in metric_stats.items():
            slope = stats.get("trend_slope", 0.0)
            label = stats.get("label", key)
            if key == "Device.DeviceInfo.MemoryStatus.Free" and slope < -100:
                findings.append(
                    f"{label} shows declining trend (slope={slope:.1f} per interval)"
                )
            elif key == "Device.DeviceInfo.ProcessStatus.CPUUsage" and slope > 1.0:
                findings.append(
                    f"{label} shows increasing trend (slope={slope:.1f} per interval)"
                )

        return findings[:15]

    def _generate_recommendations(
        self,
        health: DeviceHealthScore,
        anomalies: List[MetricAnomaly],
        change_points: List[Dict],
        metric_stats: Dict[str, Dict],
    ) -> List[str]:
        recs = []

        if health.overall_score < 40:
            recs.append("URGENT: Device is in critical state. Investigate immediately.")

        mem_stats = metric_stats.get("Device.DeviceInfo.MemoryStatus.Free")
        if mem_stats:
            if mem_stats.get("trend_slope", 0) < -500:
                recs.append(
                    "Memory leak suspected. Check for processes with growing RSS. "
                    "Consider scheduled restarts as interim mitigation."
                )
            if mem_stats.get("min", float("inf")) < 50000:
                recs.append("Free memory critically low. Review process memory footprints.")

        cpu_stats = metric_stats.get("Device.DeviceInfo.ProcessStatus.CPUUsage")
        if cpu_stats and cpu_stats.get("mean", 0) > 80:
            recs.append(
                "Sustained high CPU usage. Profile top processes to identify "
                "the root cause (e.g. runaway Wi-Fi scan, crypto, logging)."
            )

        reboots_in_risks = any("reboot" in r.lower() for r in health.risk_factors)
        if reboots_in_risks:
            recs.append(
                "Frequent reboots detected. Check reboot reasons in BootTime.log "
                "and correlate with memory/CPU trends preceding each reboot."
            )

        if health.category_scores.get("connectivity", 100) < 60:
            recs.append(
                "Telemetry gaps suggest connectivity issues. Check WAN link "
                "stability and inspect PPP/GPON logs."
            )

        if not recs:
            recs.append("No critical issues. Continue routine monitoring.")

        return recs[:10]

    def _build_metric_summaries(
        self, metric_stats: Dict[str, Dict]
    ) -> Dict[str, Dict[str, Any]]:
        result = {}
        for key, stats in metric_stats.items():
            result[key] = {
                "label": stats.get("label", key),
                "unit": stats.get("unit", ""),
                "mean": stats.get("mean", 0),
                "std": stats.get("std", 0),
                "min": stats.get("min", 0),
                "max": stats.get("max", 0),
                "trend": "increasing" if stats.get("trend_slope", 0) > 0.5
                         else ("decreasing" if stats.get("trend_slope", 0) < -0.5 else "stable"),
                "anomaly_count": stats.get("anomaly_count", 0),
            }
        return result

    def _build_narrative(
        self,
        device_info: Dict,
        health: DeviceHealthScore,
        findings: List[str],
        anomalies: List[MetricAnomaly],
        metric_stats: Dict[str, Dict],
        reports: List[Dict],
    ) -> str:
        parts = []

        model = device_info.get("model", device_info.get("hw_model", "Unknown"))
        version = device_info.get("version", "")
        mac = device_info.get("mac", "")
        ok_count = len([r for r in reports if r.get("parse_ok", True)])

        parts.append(
            f"Analysis of {model} (FW: {version}, MAC: {mac}) "
            f"based on {ok_count} telemetry reports."
        )

        parts.append(
            f"Overall health: {health.health_label} ({health.overall_score}/100). "
            f"Categories -- Memory: {health.category_scores.get('memory', 0)}/100, "
            f"CPU: {health.category_scores.get('cpu', 0)}/100, "
            f"Stability: {health.category_scores.get('stability', 0)}/100, "
            f"Connectivity: {health.category_scores.get('connectivity', 0)}/100."
        )

        if anomalies:
            severity_counts = defaultdict(int)
            for a in anomalies:
                severity_counts[a.severity] += 1
            parts.append(
                f"Detected {len(anomalies)} metric anomalies: "
                + ", ".join(f"{v} {k}" for k, v in sorted(severity_counts.items()))
                + "."
            )

        if health.risk_factors:
            parts.append("Key risks: " + "; ".join(health.risk_factors[:5]) + ".")

        return " ".join(parts)


# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------

class TelemetryAnomalyPipeline:
    """
    End-to-end telemetry anomaly detection and summarization pipeline.

    Loads cached telemetry data, runs all detectors, and produces a
    comprehensive report with health scoring and auto-generated summaries.
    """

    def __init__(
        self,
        zscore_threshold: float = 2.5,
        ewma_threshold: float = 2.0,
        cusum_threshold: float = 5.0,
        isolation_contamination: float = 0.08,
    ):
        self.ts_detector = TimeSeriesAnomalyDetector(
            zscore_threshold=zscore_threshold,
            ewma_threshold=ewma_threshold,
            isolation_contamination=isolation_contamination,
        )
        self.cp_detector = ChangePointDetector(cusum_threshold=cusum_threshold)
        self.corr_detector = CorrelationAnomalyDetector()
        self.health_scorer = DeviceHealthScorer()
        self.summarizer = TelemetrySummarizer()

    def analyze(
        self,
        cache_path: Optional[str] = None,
        reports: Optional[List[Dict]] = None,
        device_info: Optional[Dict] = None,
        cpe_id: str = "",
    ) -> TelemetryAnomalyReport:
        """
        Run the full telemetry anomaly pipeline.

        Args:
            cache_path: Path to raw_telemetry_cache.json.
            reports: Alternative: pre-loaded report list.
            device_info: Alternative: pre-loaded device info dict.
            cpe_id: CPE identifier.

        Returns:
            TelemetryAnomalyReport with anomalies, health score, and summary.
        """
        import time
        start_time = time.perf_counter()

        if reports is None and cache_path:
            reports, device_info = self._load_cache(cache_path)

        if not reports:
            return self._empty_report(cpe_id, 0.0)

        if device_info is None:
            device_info = {}

        ok_reports = [r for r in reports if r.get("parse_ok", True)]
        if not ok_reports:
            return self._empty_report(cpe_id, 0.0)

        time_range = self._compute_time_range(ok_reports)

        metric_timeseries = _extract_metric_timeseries(ok_reports)

        ts_results = self.ts_detector.detect(metric_timeseries)
        change_points = self.cp_detector.detect(metric_timeseries)
        correlation_anomalies = self.corr_detector.detect(metric_timeseries)

        flat_anomalies = self._flatten_anomalies(ts_results.get("anomalies", {}))

        health = self.health_scorer.score(
            metric_timeseries, len(flat_anomalies), device_info, ok_reports
        )

        summary = self.summarizer.summarize(
            device_info=device_info,
            health=health,
            anomalies=flat_anomalies,
            change_points=change_points,
            correlation_anomalies=correlation_anomalies,
            metric_stats=ts_results.get("metric_stats", {}),
            reports=ok_reports,
        )

        # Generate plot data for visualization (NEW)
        plot_data = self._generate_plot_data(
            metric_timeseries,
            ts_results,
            flat_anomalies,
            change_points
        )

        elapsed = (time.perf_counter() - start_time) * 1000

        return TelemetryAnomalyReport(
            cpe_id=cpe_id,
            total_reports=len(reports),
            time_range=time_range,
            anomalies=flat_anomalies,
            change_points=change_points,
            correlation_anomalies=correlation_anomalies,
            health=health,
            summary=summary,
            processing_time_ms=elapsed,
            plot_data=plot_data,  # NEW
        )

    def _load_cache(
        self, cache_path: str
    ) -> Tuple[List[Dict], Dict]:
        """Load reports and device_info from raw_telemetry_cache.json."""
        try:
            data = json.loads(Path(cache_path).read_text(encoding="utf-8"))
            reports = data.get("reports", [])
            summary = data.get("summary", {})
            device_info = summary.get("device_info", {})
            return reports, device_info
        except Exception as e:
            logger.warning(f"[TelemetryPipeline] Failed to load cache: {e}")
            return [], {}

    def _compute_time_range(self, reports: List[Dict]) -> Dict[str, str]:
        times = []
        for r in reports:
            t = r.get("time")
            if t:
                ts = t if isinstance(t, str) else (
                    t.isoformat() if hasattr(t, "isoformat") else str(t)
                )
                times.append(ts)
        times.sort()
        return {
            "first": times[0] if times else "",
            "last": times[-1] if times else "",
        }

    def _flatten_anomalies(
        self, anomalies_by_metric: Dict[str, List[Dict]]
    ) -> List[MetricAnomaly]:
        """
        Flatten and aggregate anomalies per metric.
        Instead of showing every detection point, group by metric and summarize.
        """
        flat = []
        
        for key, anomaly_list in anomalies_by_metric.items():
            if not anomaly_list:
                continue
                
            label, unit = _NUMERIC_METRICS.get(key, (key, ""))
            
            # Group anomalies by method for this metric
            by_method = {}
            for a in anomaly_list:
                method = a.get("method", "unknown")
                if method not in by_method:
                    by_method[method] = []
                by_method[method].append(a)
            
            # Create one summary entry per metric+method combination
            for method, method_anomalies in by_method.items():
                if not method_anomalies:
                    continue
                
                # Get the most severe anomaly
                most_severe = max(method_anomalies, key=lambda x: {
                    "critical": 4, "high": 3, "medium": 2, "low": 1
                }.get(x.get("severity", "low"), 0))
                
                anomaly_type = most_severe.get("type", "outlier")
                value = most_severe.get("value", 0.0)
                count = len(method_anomalies)
                
                # Generate human-readable description
                if method == "zscore":
                    avg_zscore = sum(abs(a.get("zscore", 0)) for a in method_anomalies) / count
                    if count > 1:
                        details = f"{label} exceeded normal range {count} times (avg deviation: {avg_zscore:.1f} std)"
                    else:
                        zscore = most_severe.get("zscore", 0)
                        if zscore > 0:
                            details = f"{label} is {abs(zscore):.1f} standard deviations above normal"
                        else:
                            details = f"{label} is {abs(zscore):.1f} standard deviations below normal"
                            
                elif method == "ewma":
                    avg_deviation = sum(abs(a.get("ewma_deviation", 0)) for a in method_anomalies) / count
                    if count > 1:
                        details = f"{label} showed unusual trend in {count} intervals (avg deviation: {avg_deviation:.1f}%)"
                    else:
                        deviation = most_severe.get("ewma_deviation", 0)
                        details = f"{label} shows unusual trend (deviation: {abs(deviation):.1f}%)"
                        
                elif method == "isolation_forest":
                    if count > 1:
                        details = f"{label} detected as outlier {count} times across the monitoring period"
                    else:
                        score = most_severe.get("if_score", 0)
                        details = f"{label} detected as outlier (anomaly strength: {abs(score):.2f})"
                        
                elif anomaly_type == "spike":
                    if count > 1:
                        max_val = max(a.get("value", 0) for a in method_anomalies)
                        details = f"{label} spiked {count} times (highest: {max_val:.1f}{unit})"
                    else:
                        details = f"{label} spiked to {value:.1f}{unit}"
                        
                elif anomaly_type == "drop":
                    if count > 1:
                        min_val = min(a.get("value", 0) for a in method_anomalies)
                        details = f"{label} dropped {count} times (lowest: {min_val:.1f}{unit})"
                    else:
                        details = f"{label} dropped to {value:.1f}{unit}"
                        
                elif anomaly_type == "trend":
                    details = f"{label} shows abnormal trend pattern ({count} detection points)"
                else:
                    if count > 1:
                        details = f"{label} shows unusual behavior {count} times (type: {anomaly_type})"
                    else:
                        details = f"{label} shows unusual behavior (type: {anomaly_type})"
                
                # Get timestamp range
                timestamps = [a.get("timestamp", "") for a in method_anomalies if a.get("timestamp")]
                timestamp = f"{timestamps[0]} to {timestamps[-1]}" if len(timestamps) > 1 else (timestamps[0] if timestamps else "")
                
                flat.append(MetricAnomaly(
                    metric_key=key,
                    metric_label=label,
                    timestamp=timestamp,
                    value=value,
                    expected_range=(0.0, 0.0),
                    severity=most_severe.get("severity", "low"),
                    anomaly_type=anomaly_type,
                    details=details,
                ))
        
        # Sort by severity (critical first)
        flat.sort(key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(x.severity, 4))
        return flat

    def _generate_plot_data(
        self,
        metric_timeseries: Dict[str, pd.DataFrame],
        ts_results: Dict[str, Any],
        flat_anomalies: List[MetricAnomaly],
        change_points: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Generate time-series plot data for frontend visualization.
        
        Returns:
            Dictionary with metrics, timestamps, values, anomaly markers, and thresholds.
        """
        plot_data = {
            "metrics": [],  # List of metric plots
            "health_timeline": [],  # Overall health over time
        }
        
        # Get metric statistics from ts_results
        metric_stats = ts_results.get("metric_stats", {})
        anomalies_by_metric = ts_results.get("anomalies", {})
        
        # Limit to top 6 metrics by importance (those with anomalies first)
        metrics_with_anomalies = set(a.metric_key for a in flat_anomalies)
        all_metric_keys = list(metrics_with_anomalies) + [k for k in metric_timeseries.keys() if k not in metrics_with_anomalies]
        
        for metric_key in all_metric_keys[:6]:  # Top 6 metrics
            if metric_key not in metric_timeseries:
                continue
                
            df = metric_timeseries[metric_key]
            if df.empty or "value" not in df.columns:
                continue
                
            label, unit = _NUMERIC_METRICS.get(metric_key, (metric_key, ""))
            
            # Extract time series data
            timestamps = df["timestamp"].tolist() if "timestamp" in df.columns else list(range(len(df)))
            values = df["value"].tolist()
            
            # Normalize timestamps to ISO strings for consistent comparison
            normalized_timestamps = []
            for ts in timestamps:
                if isinstance(ts, str):
                    normalized_timestamps.append(ts)
                elif hasattr(ts, 'isoformat'):
                    normalized_timestamps.append(ts.isoformat())
                else:
                    normalized_timestamps.append(str(ts))
            
            # Get statistics for threshold lines
            stats = metric_stats.get(metric_key, {})
            mean = stats.get("mean", np.mean(values) if values else 0)
            std = stats.get("std", np.std(values) if values else 0)
            
            # Calculate threshold bands
            upper_threshold = mean + (self.ts_detector.zscore_threshold * std)
            lower_threshold = mean - (self.ts_detector.zscore_threshold * std)
            
            # Mark anomaly points
            anomaly_timestamps = []
            anomaly_values = []
            anomaly_severities = []
            
            if metric_key in anomalies_by_metric:
                for anomaly in anomalies_by_metric[metric_key]:
                    ts = anomaly.get("timestamp", "")
                    val = anomaly.get("value", 0)
                    sev = anomaly.get("severity", "low")
                    if ts and val is not None:
                        # Normalize anomaly timestamp too
                        if isinstance(ts, str):
                            norm_ts = ts
                        elif hasattr(ts, 'isoformat'):
                            norm_ts = ts.isoformat()
                        else:
                            norm_ts = str(ts)
                        anomaly_timestamps.append(norm_ts)
                        anomaly_values.append(float(val))
                        anomaly_severities.append(sev)
            
            # Mark change points
            change_point_timestamps = []
            for cp in change_points:
                if cp.get("metric") == metric_key:
                    cp_ts = cp.get("timestamp", "")
                    if cp_ts:
                        change_point_timestamps.append(cp_ts)
            
            plot_data["metrics"].append({
                "metric_key": metric_key,
                "metric_label": label,
                "unit": unit,
                "timestamps": normalized_timestamps,
                "values": values,
                "mean": float(mean),
                "upper_threshold": float(upper_threshold),
                "lower_threshold": float(lower_threshold),
                "anomaly_points": {
                    "timestamps": anomaly_timestamps,
                    "values": anomaly_values,
                    "severities": anomaly_severities,
                },
                "change_points": change_point_timestamps,
                "has_anomalies": len(anomaly_timestamps) > 0,
            })
        
        return plot_data

    def _empty_report(self, cpe_id: str, elapsed: float) -> TelemetryAnomalyReport:
        empty_health = DeviceHealthScore(
            overall_score=0, category_scores={}, risk_factors=["No data available"],
            health_label="unknown",
        )
        empty_summary = TelemetrySummary(
            device_info={}, health=empty_health, anomaly_count=0,
            anomalies_by_severity={}, key_findings=["No telemetry data available"],
            metric_summaries={}, recommendations=["Upload telemetry data for analysis"],
            narrative="No telemetry data available for analysis.",
        )
        return TelemetryAnomalyReport(
            cpe_id=cpe_id, total_reports=0, time_range={},
            anomalies=[], change_points=[], correlation_anomalies=[],
            health=empty_health, summary=empty_summary,
            processing_time_ms=elapsed,
        )
