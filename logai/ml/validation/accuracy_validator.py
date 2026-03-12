"""
Accuracy Validator
==================

Validates ML pipeline accuracy against ground truth datasets.

Computes standard classification metrics:
- Precision: TP / (TP + FP)
- Recall: TP / (TP + FN)
- F1 Score: 2 * (Precision * Recall) / (Precision + Recall)
- ROC-AUC: Area under ROC curve for ensemble scores
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class AccuracyMetrics:
    """Accuracy metrics for anomaly detection."""
    precision: float
    recall: float
    f1_score: float
    roc_auc: Optional[float] = None
    true_positives: int = 0
    false_positives: int = 0
    true_negatives: int = 0
    false_negatives: int = 0
    total_predictions: int = 0


@dataclass
class MethodAccuracyResults:
    """Accuracy results for all methods."""
    ensemble: AccuracyMetrics
    per_method: Dict[str, AccuracyMetrics]
    confusion_matrix: Dict[str, Any]


class AccuracyValidator:
    """
    Validates ML pipeline accuracy against ground truth datasets.
    
    Compares detected anomalies with ground truth labels and computes
    precision, recall, F1, and ROC-AUC metrics.
    """
    
    def __init__(self, score_threshold: float = 0.5):
        """
        Args:
            score_threshold: Minimum anomaly score to classify as positive.
                           Default 0.5 balances precision/recall.
        """
        self.score_threshold = score_threshold
    
    def validate_log_detection(
        self,
        pipeline: Any,
        ground_truth_data: Any,
    ) -> MethodAccuracyResults:
        """
        Validate log anomaly detection against ground truth.
        
        Args:
            pipeline: LogAnomalyPipeline instance.
            ground_truth_data: GroundTruthDataset with labeled anomalies.
        
        Returns:
            MethodAccuracyResults with metrics for ensemble and per-method.
        """
        from logai.ml.validation.ground_truth import GroundTruthDataset
        
        if not isinstance(ground_truth_data, GroundTruthDataset):
            raise ValueError("ground_truth_data must be GroundTruthDataset")
        
        # Run ML pipeline on ground truth data
        report = pipeline.analyze(
            df=ground_truth_data.df,
            cpe_id="validation",
            domain="test",
            top_n=1000,
        )
        
        # Extract ground truth labels
        gt_templates = set(label.template for label in ground_truth_data.anomaly_labels)
        all_templates = set(ground_truth_data.df["template"].unique())
        
        # Compute ensemble metrics
        predicted_anomalies = set(a.template for a in report.anomalies if a.score >= self.score_threshold)
        ensemble_metrics = self._compute_metrics(
            predicted_anomalies, gt_templates, all_templates
        )
        
        # Add ROC-AUC for ensemble
        if report.anomalies:
            ensemble_metrics.roc_auc = self._compute_roc_auc(
                report.anomalies, gt_templates
            )
        
        # Compute per-method metrics
        per_method = {}
        
        # TF-IDF
        tfidf_anomalies = self._extract_method_anomalies(
            report.anomalies, "tfidf", self.score_threshold * 0.8
        )
        per_method["tfidf"] = self._compute_metrics(
            tfidf_anomalies, gt_templates, all_templates
        )
        
        # GRU
        gru_anomalies = self._extract_method_anomalies(
            report.anomalies, "gru", self.score_threshold * 0.8
        )
        per_method["gru"] = self._compute_metrics(
            gru_anomalies, gt_templates, all_templates
        )
        
        # Autoencoder
        autoencoder_anomalies = self._extract_method_anomalies(
            report.anomalies, "autoencoder", self.score_threshold * 0.8
        )
        per_method["autoencoder"] = self._compute_metrics(
            autoencoder_anomalies, gt_templates, all_templates
        )
        
        # DeepLog (if enabled)
        deeplog_anomalies = self._extract_method_anomalies(
            report.anomalies, "deeplog", self.score_threshold * 0.8
        )
        per_method["deeplog"] = self._compute_metrics(
            deeplog_anomalies, gt_templates, all_templates
        )
        
        # Frequency
        frequency_anomalies = self._extract_method_anomalies(
            report.anomalies, "frequency", self.score_threshold * 0.8
        )
        per_method["frequency"] = self._compute_metrics(
            frequency_anomalies, gt_templates, all_templates
        )
        
        # Semantic (if enabled)
        semantic_anomalies = self._extract_method_anomalies(
            report.anomalies, "semantic", self.score_threshold * 0.8
        )
        per_method["semantic"] = self._compute_metrics(
            semantic_anomalies, gt_templates, all_templates
        )
        
        # Build confusion matrix
        confusion_matrix = {
            "true_positives": ensemble_metrics.true_positives,
            "false_positives": ensemble_metrics.false_positives,
            "true_negatives": ensemble_metrics.true_negatives,
            "false_negatives": ensemble_metrics.false_negatives,
        }
        
        return MethodAccuracyResults(
            ensemble=ensemble_metrics,
            per_method=per_method,
            confusion_matrix=confusion_matrix,
        )
    
    def validate_telemetry_detection(
        self,
        pipeline: Any,
        ground_truth_data: Any,
    ) -> AccuracyMetrics:
        """
        Validate telemetry anomaly detection against ground truth.
        
        Args:
            pipeline: TelemetryAnomalyPipeline instance.
            ground_truth_data: Ground truth telemetry data with labels.
        
        Returns:
            AccuracyMetrics for telemetry detection.
        """
        # Implementation would be similar to log detection
        # For now, return placeholder
        logger.warning("[AccuracyValidator] Telemetry validation not yet implemented")
        return AccuracyMetrics(
            precision=0.0, recall=0.0, f1_score=0.0,
            true_positives=0, false_positives=0,
            true_negatives=0, false_negatives=0,
        )
    
    def _extract_method_anomalies(
        self,
        anomalies: List[Any],
        method: str,
        threshold: float,
    ) -> set:
        """Extract templates flagged by a specific method."""
        method_anomalies = set()
        for anom in anomalies:
            if hasattr(anom, 'methods') and method in anom.methods:
                if anom.methods[method] >= threshold:
                    method_anomalies.add(anom.template)
        return method_anomalies
    
    def _compute_metrics(
        self,
        predicted: set,
        ground_truth: set,
        all_templates: set,
    ) -> AccuracyMetrics:
        """Compute classification metrics."""
        tp = len(predicted & ground_truth)
        fp = len(predicted - ground_truth)
        fn = len(ground_truth - predicted)
        tn = len(all_templates - predicted - ground_truth)
        
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        
        return AccuracyMetrics(
            precision=precision,
            recall=recall,
            f1_score=f1,
            true_positives=tp,
            false_positives=fp,
            true_negatives=tn,
            false_negatives=fn,
            total_predictions=len(predicted),
        )
    
    def _compute_roc_auc(
        self,
        anomalies: List[Any],
        ground_truth: set,
    ) -> float:
        """Compute ROC-AUC score for ensemble predictions."""
        try:
            from sklearn.metrics import roc_auc_score
            
            # Build binary labels and scores
            y_true = []
            y_scores = []
            
            for anom in anomalies:
                y_true.append(1 if anom.template in ground_truth else 0)
                y_scores.append(anom.score)
            
            if len(set(y_true)) < 2:
                return 0.5
            
            return roc_auc_score(y_true, y_scores)
        except Exception as e:
            logger.warning(f"[AccuracyValidator] Failed to compute ROC-AUC: {e}")
            return None


def validate_pipeline(
    pipeline: Any,
    ground_truth_data: Any,
    score_threshold: float = 0.5,
) -> MethodAccuracyResults:
    """
    Convenience function to validate a pipeline.
    
    Args:
        pipeline: LogAnomalyPipeline instance.
        ground_truth_data: GroundTruthDataset with labeled anomalies.
        score_threshold: Minimum score to classify as anomaly.
    
    Returns:
        MethodAccuracyResults with metrics for all methods.
    """
    validator = AccuracyValidator(score_threshold=score_threshold)
    return validator.validate_log_detection(pipeline, ground_truth_data)
