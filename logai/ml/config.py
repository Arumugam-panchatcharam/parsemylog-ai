"""
ML Anomaly Detection Configuration
===================================

Configuration classes and default hyperparameters for ML-based anomaly
detection pipelines.

Optimized for ripgrep-filtered logs with <1000 unique templates per domain.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class LogAnomalyConfig:
    """Configuration for log anomaly detection pipeline."""
    
    # TF-IDF + Isolation Forest
    tfidf_window_minutes: int = 15
    tfidf_contamination: float = 0.05
    tfidf_n_estimators: int = 200
    tfidf_max_features: int = 5000
    
    # GRU Sequence Model (PRIMARY for <1000 templates)
    gru_window_size: int = 10
    gru_hidden_size: int = 64
    gru_num_layers: int = 2
    gru_epochs: int = 12  # Optimized for small vocabulary
    gru_batch_size: int = 256
    gru_learning_rate: float = 0.001
    gru_top_k: int = 9
    gru_dropout: float = 0.2
    gru_max_train_samples: int = 50000
    
    # Autoencoder Pattern Detector (CO-PRIMARY for <1000 templates)
    autoencoder_window_minutes: int = 15
    autoencoder_encoding_dim: int = 32  # Aggressive compression (31:1)
    autoencoder_epochs: int = 18  # Sweet spot for <1000 features
    autoencoder_batch_size: int = 64
    autoencoder_learning_rate: float = 0.001
    autoencoder_threshold_percentile: float = 95.0
    autoencoder_max_features: int = 1000
    autoencoder_dropout: float = 0.2
    
    # DeepLog LSTM (OPTIONAL - over-parameterized for <1000)
    deeplog_window_size: int = 10
    deeplog_hidden_size: int = 64
    deeplog_num_layers: int = 2
    deeplog_epochs: int = 20
    deeplog_batch_size: int = 256
    deeplog_learning_rate: float = 0.001
    deeplog_top_k: int = 9
    deeplog_max_train_samples: int = 50000
    
    # Frequency Anomaly (Statistical)
    frequency_window_minutes: int = 15
    frequency_zscore_threshold: float = 3.0
    frequency_iqr_multiplier: float = 1.5
    frequency_min_windows: int = 4
    
    # Semantic Novelty (OPTIONAL - slower)
    semantic_novelty_threshold: float = 0.65
    semantic_model_name: str = "BAAI/bge-small-en-v1.5"
    
    # Ensemble Weights (optimized for <1000 template space)
    ensemble_weights: Dict[str, float] = field(default_factory=lambda: {
        "tfidf": 0.20,       # Excellent for distribution anomalies
        "gru": 0.25,         # PRIMARY: Best sequence model for small vocab
        "autoencoder": 0.25, # CO-PRIMARY: Best for novel pattern detection
        "frequency": 0.15,   # Statistical backup
        "deeplog": 0.05,     # OPTIONAL: Over-parameterized for <1000
        "semantic": 0.10,    # OPTIONAL: Useful but slower
    })
    
    # Method enablement flags
    enable_gru: bool = True          # Recommended: ON
    enable_autoencoder: bool = True  # Recommended: ON
    enable_deeplog: bool = False     # Recommended: OFF (use GRU instead)
    enable_semantic: bool = False    # Recommended: OFF (use selectively)


@dataclass
class TelemetryAnomalyConfig:
    """Configuration for telemetry anomaly detection pipeline."""
    
    # Time-series anomaly detection
    zscore_threshold: float = 2.5
    ewma_span: int = 5
    ewma_threshold: float = 2.0
    isolation_contamination: float = 0.08
    min_points: int = 5
    
    # Change-point detection (CUSUM)
    cusum_threshold: float = 5.0
    cusum_drift: float = 0.5
    min_segment_length: int = 3
    
    # Correlation anomaly detection
    min_correlation: float = 0.3
    min_samples: int = 8
    
    # Device health scoring weights
    health_weights: Dict[str, float] = field(default_factory=lambda: {
        "memory": 0.25,
        "cpu": 0.20,
        "stability": 0.25,
        "connectivity": 0.15,
        "anomaly_load": 0.15,
    })


@dataclass
class FleetAnalyzerConfig:
    """Configuration for fleet-level anomaly analysis."""
    
    # Parallel processing
    max_workers: int = 8
    chunk_size: int = 50  # Process in batches for memory management
    
    # Clustering
    min_cluster_size: int = 3
    max_clusters: int = 10
    
    # Outlier detection
    outlier_z_threshold: float = 1.5
    max_outliers_reported: int = 50
    
    # Pattern analysis
    systemic_threshold: float = 0.3  # Patterns affecting >30% of fleet
    widespread_threshold: float = 0.1
    
    # Model caching
    enable_domain_level_caching: bool = True
    cache_max_age_hours: int = 24
    template_drift_threshold: float = 0.20  # Retrain if >20% new templates


@dataclass
class ValidationConfig:
    """Configuration for validation and testing."""
    
    # Accuracy validation
    ground_truth_normal_lines: int = 1000
    ground_truth_anomaly_count: int = 50
    
    # Performance validation
    benchmark_cpe_counts: list = field(default_factory=lambda: [1, 10, 50, 100, 500])
    performance_target_minutes: int = 10  # For 500 CPEs
    memory_target_gb: int = 8
    
    # Test thresholds
    min_precision: float = 0.85
    min_recall: float = 0.85
    min_f1: float = 0.85
    max_false_positive_rate: float = 0.10


# Default configurations
DEFAULT_LOG_CONFIG = LogAnomalyConfig()
DEFAULT_TELEMETRY_CONFIG = TelemetryAnomalyConfig()
DEFAULT_FLEET_CONFIG = FleetAnalyzerConfig()
DEFAULT_VALIDATION_CONFIG = ValidationConfig()


def get_fast_mode_config() -> LogAnomalyConfig:
    """
    Fast mode configuration for 500 CPE fleet.
    
    Recommended for production use. Enables GRU and Autoencoder only.
    Expected performance: 6-7 minutes for 500 CPEs.
    """
    config = LogAnomalyConfig()
    config.enable_gru = True
    config.enable_autoencoder = True
    config.enable_deeplog = False
    config.enable_semantic = False
    return config


def get_accuracy_mode_config() -> LogAnomalyConfig:
    """
    Accuracy mode configuration for critical CPEs.
    
    Enables all methods for maximum accuracy.
    Expected performance: 10-12 minutes for 500 CPEs.
    """
    config = LogAnomalyConfig()
    config.enable_gru = True
    config.enable_autoencoder = True
    config.enable_deeplog = True
    config.enable_semantic = True
    return config


def get_lightning_mode_config() -> LogAnomalyConfig:
    """
    Lightning mode configuration for quick analysis.
    
    Statistical methods only (TF-IDF + Frequency).
    Expected performance: 2-3 minutes for 500 CPEs.
    """
    config = LogAnomalyConfig()
    config.enable_gru = False
    config.enable_autoencoder = False
    config.enable_deeplog = False
    config.enable_semantic = False
    return config
