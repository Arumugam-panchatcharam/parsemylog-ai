"""
Log Anomaly Detection Pipeline
================================

Multi-method ensemble anomaly detection for Drain3 log templates,
designed to scale to 500+ CPE devices.

Detection Methods
-----------------
1. **TF-IDF + Isolation Forest** -- Treats each time window's template
   distribution as a TF-IDF vector and uses Isolation Forest to flag
   windows with unusual template distributions.

2. **GRU Sequence Model** -- Lightweight 2-layer GRU optimized for small
   template vocabularies (<1000 classes). Predicts next template ID and
   flags unexpected sequences. 33% fewer parameters than LSTM.

3. **Autoencoder Pattern Detector** -- Trains on TF-IDF vectors of normal
   template distributions, flags windows with high reconstruction error.
   Excellent for detecting novel patterns in ripgrep-filtered logs.

4. **DeepLog (LSTM)** -- Learns the normal sequence of template IDs and
   flags sequences whose next-template probability falls below a threshold.
   Lightweight PyTorch LSTM that trains in seconds on single-CPE data.

5. **Frequency Anomaly (Statistical)** -- Detects templates with abnormal
   occurrence counts using z-score / IQR on the per-window frequency matrix.

6. **Semantic Novelty** -- Computes the cosine distance of each template's
   embedding from the centroid of its domain cluster. Templates far from
   the centroid are flagged as semantically novel (never-before-seen error).

7. **Ensemble Scorer** -- Combines per-method anomaly scores into a single
   weighted anomaly score with configurable weights. Returns ranked results
   with explanations.

Data Flow
---------
::

    Drain3 parquet (timestamp, loglines, template)
        |
        +---> TfIdfAnomalyDetector       ---> per-window anomaly scores
        +---> GRULogDetector              ---> per-sequence anomaly scores (PRIMARY)
        +---> AutoencoderLogDetector      ---> per-window reconstruction errors (CO-PRIMARY)
        +---> DeepLogDetector             ---> per-sequence anomaly scores (OPTIONAL)
        +---> FrequencyAnomalyDetector    ---> per-template anomaly flags
        +---> SemanticNoveltyDetector     ---> per-template novelty scores (OPTIONAL)
        |
        +---> EnsembleScorer              ---> final ranked anomalies

Usage:
    >>> from logai.ml.log_anomaly import LogAnomalyPipeline
    >>> # Fast mode (recommended for 500 CPE fleet)
    >>> pipeline = LogAnomalyPipeline(
    ...     enable_gru=True,
    ...     enable_autoencoder=True,
    ...     enable_deeplog=False,
    ...     enable_semantic=False,
    ... )
    >>> results = pipeline.analyze(parquet_path="/path/to/wireless_rg.parquet")
"""

from __future__ import annotations

import logging
import math
import warnings
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import threading

import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from sklearn.ensemble import IsolationForest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import LabelEncoder

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")

# Global lock for thread-safe model loading in parallel contexts
_MODEL_LOAD_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AnomalyResult:
    """Single anomaly detection result."""
    template: str
    score: float  # 0.0 (normal) to 1.0 (highly anomalous)
    methods: Dict[str, float]  # per-method scores
    evidence: List[str]  # human-readable reasons
    sample_loglines: List[str] = field(default_factory=list)
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    count: int = 0
    category: Optional[str] = None  # domain/category of the log


@dataclass
class LogAnomalyReport:
    """Complete anomaly report for a single CPE / domain."""
    cpe_id: str
    domain: str
    total_lines: int
    total_templates: int
    anomaly_count: int
    anomalies: List[AnomalyResult]
    method_stats: Dict[str, Any]
    processing_time_ms: float


# ---------------------------------------------------------------------------
# Method 1: TF-IDF + Isolation Forest
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Method 1: TF-IDF + Isolation Forest (DEPRECATED - use IsolationForestEmbeddingDetector)
# ---------------------------------------------------------------------------

class TfIdfAnomalyDetector:
    """
    DEPRECATED: Use IsolationForestEmbeddingDetector instead.
    
    Treats each time window as a "document" where tokens are template IDs.
    Builds a TF-IDF matrix over windows and applies Isolation Forest.

    Anomalous windows have unusual template distributions -- e.g. a burst
    of error templates that never appeared before, or a sudden absence of
    normal templates.
    """

    def __init__(
        self,
        window_minutes: int = 15,
        contamination: float = 0.05,
        n_estimators: int = 200,
        max_features: int = 5000,
    ):
        self.window_minutes = window_minutes
        self.contamination = contamination
        self.n_estimators = n_estimators
        self.max_features = max_features
        self._vectorizer: Optional[TfidfVectorizer] = None
        self._model: Optional[IsolationForest] = None

    def detect(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Run TF-IDF + Isolation Forest on windowed template distributions.

        Args:
            df: DataFrame with columns [timestamp, template].

        Returns:
            Dict with 'window_scores', 'anomalous_windows', 'template_importances'.
        """
        if df.empty or "template" not in df.columns:
            return {"window_scores": [], "anomalous_windows": [], "template_importances": {}}

        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.dropna(subset=["timestamp"])
        if df.empty:
            return {"window_scores": [], "anomalous_windows": [], "template_importances": {}}

        windows = self._build_windows(df)
        if len(windows) < 4:
            return {"window_scores": [], "anomalous_windows": [], "template_importances": {}}

        docs = [" ".join(w["templates"]) for w in windows]

        self._vectorizer = TfidfVectorizer(
            max_features=self.max_features,
            token_pattern=r"(?u)\S+",
        )
        tfidf_matrix = self._vectorizer.fit_transform(docs)

        self._model = IsolationForest(
            n_estimators=self.n_estimators,
            contamination=min(self.contamination, 0.5),
            random_state=42,
            n_jobs=-1,
        )
        predictions = self._model.fit_predict(tfidf_matrix)
        raw_scores = self._model.decision_function(tfidf_matrix)

        score_min, score_max = raw_scores.min(), raw_scores.max()
        score_range = score_max - score_min if score_max != score_min else 1.0
        norm_scores = 1.0 - (raw_scores - score_min) / score_range

        window_scores = []
        anomalous_windows = []
        for i, w in enumerate(windows):
            entry = {
                "window_start": w["start"].isoformat() if pd.notna(w["start"]) else "",
                "window_end": w["end"].isoformat() if pd.notna(w["end"]) else "",
                "line_count": w["count"],
                "anomaly_score": float(norm_scores[i]),
                "is_anomaly": bool(predictions[i] == -1),
                "unique_templates": len(set(w["templates"])),
            }
            window_scores.append(entry)
            if predictions[i] == -1:
                anomalous_windows.append(entry)

        template_importances = {}
        if self._vectorizer:
            feature_names = self._vectorizer.get_feature_names_out()
            mean_tfidf = np.asarray(tfidf_matrix.mean(axis=0)).flatten()
            for j, name in enumerate(feature_names):
                template_importances[name] = float(mean_tfidf[j])

        return {
            "window_scores": window_scores,
            "anomalous_windows": anomalous_windows,
            "template_importances": template_importances,
        }

    def _build_windows(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """Split DataFrame into fixed-size time windows."""
        freq = f"{self.window_minutes}min"
        df = df.set_index("timestamp").sort_index()

        windows = []
        for start, group in df.resample(freq):
            if group.empty:
                continue
            templates = group["template"].astype(str).tolist()
            tmpl_ids = [f"T{hash(t) % 100000:05d}" for t in templates]
            windows.append({
                "start": start,
                "end": start + pd.Timedelta(minutes=self.window_minutes),
                "templates": tmpl_ids,
                "raw_templates": templates,
                "count": len(templates),
            })
        return windows


# ---------------------------------------------------------------------------
# Method 2: DeepLog -- LSTM Sequence Anomaly (DEPRECATED - use GRU with embeddings)
# ---------------------------------------------------------------------------

class DeepLogDetector:
    """
    DEPRECATED: Use GRULogDetector with use_embeddings=True instead.
    
    LSTM-based sequence anomaly detection inspired by the DeepLog paper
    (Du et al., CCS 2017).

    Learns the normal sequential order of log template IDs, then flags
    sequences where the actual next template has low predicted probability.

    Uses a lightweight single-layer LSTM that trains in seconds on
    single-CPE data (typically < 50k templates).
    """

    def __init__(
        self,
        window_size: int = 10,
        hidden_size: int = 64,
        num_layers: int = 2,
        epochs: int = 20,
        batch_size: int = 256,
        learning_rate: float = 0.001,
        top_k: int = 9,
        max_train_samples: int = 50000,
    ):
        self.window_size = window_size
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.epochs = epochs
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.top_k = top_k
        self.max_train_samples = max_train_samples
        self._model = None
        self._encoder: Optional[LabelEncoder] = None
        self._is_trained = False

    def detect(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Train on the template sequence and detect anomalous subsequences.

        Args:
            df: DataFrame with columns [timestamp, template], sorted by time.

        Returns:
            Dict with 'sequence_anomalies', 'anomaly_rate', 'model_stats'.
        """
        try:
            import torch
            import torch.nn as nn
            from torch.utils.data import DataLoader, TensorDataset
        except ImportError:
            logger.warning("[DeepLog] PyTorch not available, skipping LSTM detection")
            return {"sequence_anomalies": [], "anomaly_rate": 0.0, "model_stats": {}}

        if df.empty or len(df) < self.window_size + 1:
            return {"sequence_anomalies": [], "anomaly_rate": 0.0, "model_stats": {}}

        templates = df["template"].astype(str).values
        self._encoder = LabelEncoder()
        encoded = self._encoder.fit_transform(templates)
        num_classes = len(self._encoder.classes_)

        if num_classes < 3:
            return {"sequence_anomalies": [], "anomaly_rate": 0.0,
                    "model_stats": {"reason": "too_few_classes"}}

        X, y = self._build_sequences(encoded)
        if len(X) < 10:
            return {"sequence_anomalies": [], "anomaly_rate": 0.0,
                    "model_stats": {"reason": "too_few_sequences"}}

        if len(X) > self.max_train_samples:
            indices = np.random.choice(len(X), self.max_train_samples, replace=False)
            X, y = X[indices], y[indices]

        X_tensor = torch.LongTensor(X)
        y_tensor = torch.LongTensor(y)
        dataset = TensorDataset(X_tensor, y_tensor)
        loader = DataLoader(dataset, batch_size=self.batch_size, shuffle=True)

        model = _DeepLogLSTM(num_classes, self.hidden_size, self.num_layers)
        device = torch.device("cpu")
        model = model.to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=self.learning_rate)
        criterion = nn.CrossEntropyLoss()

        model.train()
        for epoch in range(self.epochs):
            total_loss = 0.0
            for batch_x, batch_y in loader:
                batch_x, batch_y = batch_x.to(device), batch_y.to(device)
                optimizer.zero_grad()
                output = model(batch_x, num_classes)
                loss = criterion(output, batch_y)
                loss.backward()
                optimizer.step()
                total_loss += loss.item()

        model.eval()
        sequence_anomalies = []
        anomaly_count = 0

        all_X = torch.LongTensor(self._build_sequences(encoded)[0])
        all_y = self._build_sequences(encoded)[1]

        with torch.no_grad():
            for start_idx in range(0, len(all_X), self.batch_size):
                batch_x = all_X[start_idx:start_idx + self.batch_size].to(device)
                batch_y_np = all_y[start_idx:start_idx + self.batch_size]
                output = model(batch_x, num_classes)
                probs = torch.softmax(output, dim=1)
                top_k_vals, top_k_idx = torch.topk(probs, min(self.top_k, num_classes), dim=1)

                for i in range(len(batch_x)):
                    actual = batch_y_np[i]
                    predicted_set = top_k_idx[i].cpu().numpy()
                    if actual not in predicted_set:
                        anomaly_count += 1
                        pos = start_idx + i + self.window_size
                        if pos < len(templates):
                            seq_templates = templates[pos - self.window_size:pos + 1].tolist()
                            actual_prob = float(probs[i, actual].cpu())
                            sequence_anomalies.append({
                                "position": int(pos),
                                "expected_top_k": [
                                    self._encoder.classes_[idx] for idx in predicted_set
                                    if idx < len(self._encoder.classes_)
                                ][:5],
                                "actual_template": str(templates[pos]),
                                "actual_probability": actual_prob,
                                "sequence_context": seq_templates[-5:],
                            })

        total_sequences = len(all_X)
        anomaly_rate = anomaly_count / total_sequences if total_sequences > 0 else 0.0

        MAX_REPORTED = 200
        if len(sequence_anomalies) > MAX_REPORTED:
            sequence_anomalies.sort(key=lambda x: x["actual_probability"])
            sequence_anomalies = sequence_anomalies[:MAX_REPORTED]

        self._is_trained = True
        self._model = model

        return {
            "sequence_anomalies": sequence_anomalies,
            "anomaly_rate": float(anomaly_rate),
            "model_stats": {
                "num_classes": num_classes,
                "total_sequences": total_sequences,
                "anomaly_count": anomaly_count,
                "epochs": self.epochs,
                "window_size": self.window_size,
                "top_k": self.top_k,
            },
        }

    def _build_sequences(self, encoded: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Build sliding-window (input, target) pairs from the encoded sequence."""
        X, y = [], []
        for i in range(len(encoded) - self.window_size):
            X.append(encoded[i:i + self.window_size])
            y.append(encoded[i + self.window_size])
        return np.array(X), np.array(y)


class _DeepLogLSTM:
    """Lightweight LSTM model for DeepLog sequence prediction."""

    def __new__(cls, num_classes, hidden_size, num_layers):
        try:
            import torch.nn as nn
            return _DeepLogLSTMImpl(num_classes, hidden_size, num_layers)
        except ImportError:
            return None


def _build_deeplog_lstm_class():
    """Build the LSTM class lazily to avoid import errors when torch is unavailable."""
    try:
        import torch
        import torch.nn as nn

        class DeepLogLSTMImpl(nn.Module):
            def __init__(self, num_classes, hidden_size, num_layers):
                super().__init__()
                self.hidden_size = hidden_size
                self.num_layers = num_layers
                self.embedding = nn.Embedding(num_classes, hidden_size)
                self.lstm = nn.LSTM(
                    hidden_size, hidden_size, num_layers,
                    batch_first=True, dropout=0.1 if num_layers > 1 else 0.0,
                )
                self.fc = nn.Linear(hidden_size, num_classes)

            def forward(self, x, num_classes=None):
                embedded = self.embedding(x)
                lstm_out, _ = self.lstm(embedded)
                out = self.fc(lstm_out[:, -1, :])
                return out

        return DeepLogLSTMImpl
    except ImportError:
        return None


_DeepLogLSTMImpl = _build_deeplog_lstm_class()


# ---------------------------------------------------------------------------
# Method 2b: GRU -- Sequence Anomaly (Optimized for <1000 templates)
# ---------------------------------------------------------------------------

class GRULogDetector:
    """
    GRU-based sequence anomaly detection optimized for ripgrep-filtered logs.
    
    Supports two modes:
    1. Template ID mode (legacy): Embedding(vocab_size, 64) -> GRU -> predict next ID
    2. Embedding vector mode (NEW): Direct 384-dim embeddings -> GRU -> predict next embedding
    
    Embedding mode benefits:
    - Richer semantic features (384-dim vs. 1-dim ID)
    - Captures semantic similarity in sequences
    - More robust to template variations
    - Consistent with vector-based pipeline
    
    Architecture (embedding mode):
        Input: (batch, seq_len, 384) -> GRU(384, 128, num_layers=2) 
        -> Linear(128, 384) -> Cosine similarity loss
    
    Training strategy:
        - Epochs: 12 (optimized for <1000 classes)
        - Batch size: 256
        - Learning rate: 0.001
        - Max training samples: 50K
    """

    def __init__(
        self,
        window_size: int = 10,
        hidden_size: int = 128,  # Increased for embedding mode
        num_layers: int = 2,
        epochs: int = 12,
        batch_size: int = 256,
        learning_rate: float = 0.001,
        top_k: int = 9,
        max_train_samples: int = 50000,
        dropout: float = 0.2,
        cache_dir: Optional[Path] = None,
        use_embeddings: bool = True,  # NEW: Use 384-dim embeddings
        embedding_dim: int = 384,  # BGE-small embedding size
    ):
        self.window_size = window_size
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.epochs = epochs
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.top_k = top_k
        self.max_train_samples = max_train_samples
        self.dropout = dropout
        self.cache_dir = cache_dir
        self.use_embeddings = use_embeddings
        self.embedding_dim = embedding_dim
        self._model = None
        self._encoder: Optional[LabelEncoder] = None
        self._is_trained = False
        self._vocab: Optional[Dict[str, int]] = None

    def detect(
        self, 
        df: pd.DataFrame, 
        domain: str = "unknown",
        embeddings_dict: Optional[Dict[str, np.ndarray]] = None,
    ) -> Dict[str, Any]:
        """
        Train on the template sequence and detect anomalous subsequences.

        Args:
            df: DataFrame with columns [timestamp, template], sorted by time.
            domain: Domain name for model caching.
            embeddings_dict: {template_str: 384-dim embedding} (required if use_embeddings=True)

        Returns:
            Dict with 'sequence_anomalies', 'anomaly_rate', 'model_stats'.
        """
        try:
            import torch
            import torch.nn as nn
            from torch.utils.data import DataLoader, TensorDataset
        except ImportError:
            logger.warning("[GRU] PyTorch not available, skipping GRU detection")
            return {"sequence_anomalies": [], "anomaly_rate": 0.0, "model_stats": {}}

        if df.empty or len(df) < self.window_size + 1:
            return {"sequence_anomalies": [], "anomaly_rate": 0.0, "model_stats": {}}

        templates = df["template"].astype(str).values
        
        # NEW: Embedding mode
        if self.use_embeddings:
            if embeddings_dict is None:
                logger.warning("[GRU] embeddings_dict required for embedding mode")
                return {"sequence_anomalies": [], "anomaly_rate": 0.0, "model_stats": {}}
            
            return self._detect_with_embeddings(templates, domain, embeddings_dict, torch, nn, DataLoader, TensorDataset)
        
        # Legacy: Template ID mode
        return self._detect_with_template_ids(templates, domain, torch, nn, DataLoader, TensorDataset)
    
    def _detect_with_template_ids(self, templates, domain, torch, nn, DataLoader, TensorDataset):
        """Legacy method using template IDs."""
        
        # Try loading from cache first
        cached_model = None
        if self.cache_dir:
            cached_model = self._try_load_from_cache(domain, templates)
        
        if cached_model is not None:
            self._model, self._vocab, self._encoder = cached_model
            num_classes = len(self._encoder.classes_)
            logger.info(f"[GRU] Using cached model for domain '{domain}'")
        else:
            # Train new model
            self._encoder = LabelEncoder()
            encoded = self._encoder.fit_transform(templates)
            num_classes = len(self._encoder.classes_)

            if num_classes < 3:
                return {"sequence_anomalies": [], "anomaly_rate": 0.0,
                        "model_stats": {"reason": "too_few_classes"}}

            X, y = self._build_sequences(encoded)
            if len(X) < 10:
                return {"sequence_anomalies": [], "anomaly_rate": 0.0,
                        "model_stats": {"reason": "too_few_sequences"}}

            if len(X) > self.max_train_samples:
                indices = np.random.choice(len(X), self.max_train_samples, replace=False)
                X, y = X[indices], y[indices]

            X_tensor = torch.LongTensor(X)
            y_tensor = torch.LongTensor(y)
            dataset = TensorDataset(X_tensor, y_tensor)
            loader = DataLoader(dataset, batch_size=self.batch_size, shuffle=True)

            model = _GRULogModel(num_classes, self.hidden_size, self.num_layers, self.dropout)
            device = torch.device("cpu")
            model = model.to(device)
            optimizer = torch.optim.Adam(model.parameters(), lr=self.learning_rate)
            criterion = nn.CrossEntropyLoss()

            model.train()
            for epoch in range(self.epochs):
                total_loss = 0.0
                for batch_x, batch_y in loader:
                    batch_x, batch_y = batch_x.to(device), batch_y.to(device)
                    optimizer.zero_grad()
                    output = model(batch_x, num_classes)
                    loss = criterion(output, batch_y)
                    loss.backward()
                    optimizer.step()
                    total_loss += loss.item()

            model.eval()
            self._model = model
            
            # Save to cache
            if self.cache_dir:
                self._save_to_cache(domain, model, self._encoder)
        
        # Re-encode templates if we loaded from cache
        encoded = self._encoder.transform(templates)
        
        device = torch.device("cpu")
        sequence_anomalies = []
        anomaly_count = 0

        all_X = torch.LongTensor(self._build_sequences(encoded)[0])
        all_y = self._build_sequences(encoded)[1]

        with torch.no_grad():
            for start_idx in range(0, len(all_X), self.batch_size):
                batch_x = all_X[start_idx:start_idx + self.batch_size].to(device)
                batch_y_np = all_y[start_idx:start_idx + self.batch_size]
                output = self._model(batch_x, num_classes)
                probs = torch.softmax(output, dim=1)
                top_k_vals, top_k_idx = torch.topk(probs, min(self.top_k, num_classes), dim=1)

                for i in range(len(batch_x)):
                    actual = batch_y_np[i]
                    predicted_set = top_k_idx[i].cpu().numpy()
                    if actual not in predicted_set:
                        anomaly_count += 1
                        pos = start_idx + i + self.window_size
                        if pos < len(templates):
                            seq_templates = templates[pos - self.window_size:pos + 1].tolist()
                            actual_prob = float(probs[i, actual].cpu())
                            sequence_anomalies.append({
                                "position": int(pos),
                                "expected_top_k": [
                                    self._encoder.classes_[idx] for idx in predicted_set
                                    if idx < len(self._encoder.classes_)
                                ][:5],
                                "actual_template": str(templates[pos]),
                                "actual_probability": actual_prob,
                                "sequence_context": seq_templates[-5:],
                            })

        total_sequences = len(all_X)
        anomaly_rate = anomaly_count / total_sequences if total_sequences > 0 else 0.0

        MAX_REPORTED = 200
        if len(sequence_anomalies) > MAX_REPORTED:
            sequence_anomalies.sort(key=lambda x: x["actual_probability"])
            sequence_anomalies = sequence_anomalies[:MAX_REPORTED]

        self._is_trained = True

        return {
            "sequence_anomalies": sequence_anomalies,
            "anomaly_rate": float(anomaly_rate),
            "model_stats": {
                "num_classes": num_classes,
                "total_sequences": total_sequences,
                "anomaly_count": anomaly_count,
                "epochs": self.epochs,
                "window_size": self.window_size,
                "top_k": self.top_k,
                "model_type": "GRU",
            },
        }
    
    def _detect_with_embeddings(
        self, 
        templates, 
        domain, 
        embeddings_dict, 
        torch, 
        nn, 
        DataLoader, 
        TensorDataset
    ):
        """NEW: Detection using 384-dim embedding vectors."""
        # Build embedding sequence
        embedding_vectors = []
        valid_templates = []
        for t in templates:
            if t in embeddings_dict:
                embedding_vectors.append(embeddings_dict[t])
                valid_templates.append(t)
        
        if len(embedding_vectors) < self.window_size + 1:
            logger.warning(f"[GRU-Embed] Not enough embeddings: {len(embedding_vectors)}")
            return {"sequence_anomalies": [], "anomaly_rate": 0.0, "model_stats": {}}
        
        embedding_vectors = np.array(embedding_vectors)  # Shape: (T, 384)
        valid_templates = np.array(valid_templates)
        
        # Build sequences: (X: [t-w, ..., t-1], y: t)
        X_embed, y_embed = [], []
        for i in range(len(embedding_vectors) - self.window_size):
            X_embed.append(embedding_vectors[i:i + self.window_size])
            y_embed.append(embedding_vectors[i + self.window_size])
        
        X_embed = np.array(X_embed)  # Shape: (N, window_size, 384)
        y_embed = np.array(y_embed)  # Shape: (N, 384)
        
        if len(X_embed) < 10:
            return {"sequence_anomalies": [], "anomaly_rate": 0.0,
                    "model_stats": {"reason": "too_few_sequences"}}
        
        # Sample if too many
        if len(X_embed) > self.max_train_samples:
            indices = np.random.choice(len(X_embed), self.max_train_samples, replace=False)
            X_embed, y_embed = X_embed[indices], y_embed[indices]
        
        # Build model
        model = _GRUEmbeddingModel(
            input_dim=self.embedding_dim,
            hidden_size=self.hidden_size,
            num_layers=self.num_layers,
            dropout=self.dropout,
        )
        device = torch.device("cpu")
        model = model.to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=self.learning_rate)
        
        # Cosine embedding loss
        cosine_loss = nn.CosineEmbeddingLoss()
        
        # Convert to tensors
        X_tensor = torch.FloatTensor(X_embed)
        y_tensor = torch.FloatTensor(y_embed)
        dataset = TensorDataset(X_tensor, y_tensor)
        loader = DataLoader(dataset, batch_size=self.batch_size, shuffle=True)
        
        # Train
        model.train()
        for epoch in range(self.epochs):
            total_loss = 0.0
            for batch_x, batch_y in loader:
                batch_x, batch_y = batch_x.to(device), batch_y.to(device)
                optimizer.zero_grad()
                output = model(batch_x)
                # Cosine loss: target=1 (similar), target=-1 (dissimilar)
                target = torch.ones(len(batch_x), device=device)
                loss = cosine_loss(output, batch_y, target)
                loss.backward()
                optimizer.step()
                total_loss += loss.item()
        
        model.eval()
        self._model = model
        
        # Inference: detect anomalies
        sequence_anomalies = []
        anomaly_count = 0
        
        # Rebuild full sequences for inference
        X_all, y_all = [], []
        for i in range(len(embedding_vectors) - self.window_size):
            X_all.append(embedding_vectors[i:i + self.window_size])
            y_all.append(embedding_vectors[i + self.window_size])
        
        X_all = torch.FloatTensor(np.array(X_all))
        y_all = torch.FloatTensor(np.array(y_all))
        
        with torch.no_grad():
            for start_idx in range(0, len(X_all), self.batch_size):
                batch_x = X_all[start_idx:start_idx + self.batch_size].to(device)
                batch_y = y_all[start_idx:start_idx + self.batch_size].to(device)
                output = model(batch_x)
                
                # Cosine similarity (1 = identical, -1 = opposite)
                cosine_sim = nn.functional.cosine_similarity(output, batch_y, dim=1)
                
                # Anomaly if similarity < threshold (e.g., 0.7)
                threshold = 0.7
                for i in range(len(batch_x)):
                    sim = float(cosine_sim[i])
                    if sim < threshold:
                        anomaly_count += 1
                        pos = start_idx + i + self.window_size
                        if pos < len(valid_templates):
                            seq_templates = valid_templates[pos - self.window_size:pos + 1].tolist()
                            sequence_anomalies.append({
                                "position": int(pos),
                                "actual_template": str(valid_templates[pos]),
                                "cosine_similarity": sim,
                                "sequence_context": seq_templates[-5:],
                            })
        
        total_sequences = len(X_all)
        anomaly_rate = anomaly_count / total_sequences if total_sequences > 0 else 0.0
        
        MAX_REPORTED = 200
        if len(sequence_anomalies) > MAX_REPORTED:
            sequence_anomalies.sort(key=lambda x: x["cosine_similarity"])
            sequence_anomalies = sequence_anomalies[:MAX_REPORTED]
        
        logger.info(
            f"[GRU-Embed] Domain '{domain}': {anomaly_count}/{total_sequences} anomalies "
            f"({anomaly_rate:.1%}), reporting top {len(sequence_anomalies)}"
        )
        
        return {
            "sequence_anomalies": sequence_anomalies,
            "anomaly_rate": anomaly_rate,
            "model_stats": {
                "total_sequences": total_sequences,
                "anomaly_count": anomaly_count,
                "epochs": self.epochs,
                "window_size": self.window_size,
                "model_type": "GRU-Embedding",
                "embedding_dim": self.embedding_dim,
            },
        }

    def _build_sequences(self, encoded: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Build sliding-window (input, target) pairs from the encoded sequence."""
        X, y = [], []
        for i in range(len(encoded) - self.window_size):
            X.append(encoded[i:i + self.window_size])
            y.append(encoded[i + self.window_size])
        return np.array(X), np.array(y)
    
    def _try_load_from_cache(self, domain: str, templates: np.ndarray):
        """Try to load model from cache."""
        try:
            from logai.ml.model_cache import ModelCache
            
            cache = ModelCache(self.cache_dir)
            config = {
                "hidden_size": self.hidden_size,
                "num_layers": self.num_layers,
                "dropout": self.dropout,
                "window_size": self.window_size,
            }
            
            unique_templates = np.unique(templates)
            result = cache.load_gru_model(
                domain=domain,
                current_vocab_size=len(unique_templates),
                config=config,
                model_class=_GRULogModel,
            )
            
            if result is not None:
                model, vocab = result
                # Rebuild encoder from vocab
                encoder = LabelEncoder()
                encoder.classes_ = np.array(list(vocab.keys()))
                return (model, vocab, encoder)
            
            return None
        except Exception as e:
            logger.warning(f"[GRU] Cache load failed: {e}")
            return None
    
    def _save_to_cache(self, domain: str, model, encoder: LabelEncoder):
        """Save model to cache."""
        try:
            from logai.ml.model_cache import ModelCache
            
            cache = ModelCache(self.cache_dir)
            vocab = {cls: idx for idx, cls in enumerate(encoder.classes_)}
            config = {
                "hidden_size": self.hidden_size,
                "num_layers": self.num_layers,
                "dropout": self.dropout,
                "window_size": self.window_size,
            }
            
            cache.save_gru_model(
                domain=domain,
                model=model,
                vocab=vocab,
                config=config,
            )
        except Exception as e:
            logger.warning(f"[GRU] Cache save failed: {e}")


class _GRULogModel:
    """Lightweight GRU model for sequence prediction."""

    def __new__(cls, num_classes, hidden_size, num_layers, dropout):
        try:
            import torch.nn as nn
            return _GRULogModelImpl(num_classes, hidden_size, num_layers, dropout)
        except ImportError:
            return None


def _build_gru_model_class():
    """Build the GRU class lazily to avoid import errors when torch is unavailable."""
    try:
        import torch
        import torch.nn as nn

        class GRULogModelImpl(nn.Module):
            def __init__(self, num_classes, hidden_size, num_layers, dropout):
                super().__init__()
                self.hidden_size = hidden_size
                self.num_layers = num_layers
                self.embedding = nn.Embedding(num_classes, hidden_size)
                self.gru = nn.GRU(
                    hidden_size, hidden_size, num_layers,
                    batch_first=True, dropout=dropout if num_layers > 1 else 0.0,
                )
                self.fc = nn.Linear(hidden_size, num_classes)

            def forward(self, x, num_classes=None):
                embedded = self.embedding(x)
                gru_out, _ = self.gru(embedded)
                out = self.fc(gru_out[:, -1, :])
                return out

        return GRULogModelImpl
    except ImportError:
        return None


_GRULogModelImpl = _build_gru_model_class()


# NEW: GRU model for embeddings
def _build_gru_embedding_model_class():
    """Build GRU model for 384-dim embeddings."""
    try:
        import torch
        import torch.nn as nn

        class GRUEmbeddingModelImpl(nn.Module):
            def __init__(self, input_dim, hidden_size, num_layers, dropout):
                super().__init__()
                self.hidden_size = hidden_size
                self.num_layers = num_layers
                self.gru = nn.GRU(
                    input_dim, hidden_size, num_layers,
                    batch_first=True, dropout=dropout if num_layers > 1 else 0.0,
                )
                self.fc = nn.Linear(hidden_size, input_dim)

            def forward(self, x):
                # x: (batch, seq_len, 384)
                gru_out, _ = self.gru(x)  # (batch, seq_len, hidden)
                out = self.fc(gru_out[:, -1, :])  # (batch, 384)
                return out

        return GRUEmbeddingModelImpl
    except ImportError:
        return None


_GRUEmbeddingModelImpl = _build_gru_embedding_model_class()


class _GRUEmbeddingModel:
    """GRU model for embedding vectors."""

    def __new__(cls, input_dim, hidden_size, num_layers, dropout):
        try:
            import torch.nn as nn
            return _GRUEmbeddingModelImpl(input_dim, hidden_size, num_layers, dropout)
        except ImportError:
            return None


# ---------------------------------------------------------------------------
# Method 3: Frequency Anomaly Detector (DEPRECATED - use VectorSimilarityDetector)
# ---------------------------------------------------------------------------

class FrequencyAnomalyDetector:
    """
    DEPRECATED: Use VectorSimilarityDetector instead.
    
    Detects templates with statistically abnormal occurrence frequency.

    Uses a combination of z-score and IQR-based outlier detection on
    per-window template counts. Works well for:
    - Sudden bursts (e.g. error storm)
    - Rare templates appearing for the first time
    - Templates vanishing from a window they normally appear in
    """

    def __init__(
        self,
        window_minutes: int = 15,
        zscore_threshold: float = 3.0,
        iqr_multiplier: float = 1.5,
        min_windows: int = 4,
    ):
        self.window_minutes = window_minutes
        self.zscore_threshold = zscore_threshold
        self.iqr_multiplier = iqr_multiplier
        self.min_windows = min_windows

    def detect(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Detect frequency anomalies across time windows.

        Returns:
            Dict with 'template_anomalies', 'burst_events', 'rarity_scores'.
        """
        if df.empty or "template" not in df.columns:
            return {"template_anomalies": [], "burst_events": [], "rarity_scores": {}}

        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.dropna(subset=["timestamp"])
        if df.empty:
            return {"template_anomalies": [], "burst_events": [], "rarity_scores": {}}

        freq = f"{self.window_minutes}min"
        df = df.set_index("timestamp").sort_index()

        window_counts = defaultdict(list)
        window_labels = []
        for start, group in df.resample(freq):
            if group.empty:
                continue
            window_labels.append(start)
            counts = Counter(group["template"].astype(str))
            for template in counts:
                window_counts[template].append(counts[template])
            for template in window_counts:
                if template not in counts:
                    window_counts[template].append(0)

        all_templates = list(window_counts.keys())
        if not all_templates or len(window_labels) < self.min_windows:
            return {"template_anomalies": [], "burst_events": [], "rarity_scores": {}}

        template_anomalies = []
        burst_events = []
        rarity_scores = {}

        total_global = sum(sum(v) for v in window_counts.values())

        for template, counts_list in window_counts.items():
            arr = np.array(counts_list, dtype=float)
            total = arr.sum()
            mean_count = arr.mean()
            std_count = arr.std()

            rarity = 1.0 - (total / total_global) if total_global > 0 else 1.0
            rarity_scores[template] = float(rarity)

            if std_count > 0 and len(arr) >= self.min_windows:
                z_scores = (arr - mean_count) / std_count
                for i, z in enumerate(z_scores):
                    if abs(z) > self.zscore_threshold:
                        anomaly_type = "burst" if z > 0 else "dropout"
                        entry = {
                            "template": template,
                            "window_index": i,
                            "window_start": window_labels[i].isoformat() if i < len(window_labels) else "",
                            "count": int(arr[i]),
                            "mean_count": float(mean_count),
                            "zscore": float(z),
                            "anomaly_type": anomaly_type,
                        }
                        template_anomalies.append(entry)
                        if anomaly_type == "burst":
                            burst_events.append(entry)

            q1 = np.percentile(arr, 25) if len(arr) >= 4 else 0
            q3 = np.percentile(arr, 75) if len(arr) >= 4 else arr.max()
            iqr = q3 - q1
            if iqr > 0:
                upper = q3 + self.iqr_multiplier * iqr
                for i, val in enumerate(arr):
                    if val > upper and not any(
                        a["template"] == template and a["window_index"] == i
                        for a in template_anomalies
                    ):
                        template_anomalies.append({
                            "template": template,
                            "window_index": i,
                            "window_start": window_labels[i].isoformat() if i < len(window_labels) else "",
                            "count": int(val),
                            "mean_count": float(mean_count),
                            "zscore": float((val - mean_count) / std_count) if std_count > 0 else 0.0,
                            "anomaly_type": "iqr_outlier",
                        })

        template_anomalies.sort(key=lambda x: abs(x.get("zscore", 0)), reverse=True)

        return {
            "template_anomalies": template_anomalies[:500],
            "burst_events": burst_events[:100],
            "rarity_scores": dict(sorted(rarity_scores.items(), key=lambda x: -x[1])[:200]),
        }


# ---------------------------------------------------------------------------
# Method 4: Vector Similarity Detector (NEW - Qdrant-based)
# ---------------------------------------------------------------------------

class VectorSimilarityDetector:
    """
    Hybrid vector similarity anomaly detection using Qdrant embeddings.
    
    Combines three complementary approaches:
    1. KNN Distance: Templates far from their K nearest neighbors
    2. Cluster Distance: Templates far from their cluster centroid
    3. Temporal Drift: Current templates drifting from historical baseline
    
    All methods operate on the existing 384-dim BGE embeddings stored in Qdrant,
    leveraging the infrastructure already used for RAG indexing.
    """
    
    def __init__(
        self,
        qdrant_store: Any,
        knn_k: int = 10,
        cluster_method: str = "kmeans",
        n_clusters: int = 5,
        temporal_window_days: int = 7,
        weights: Optional[Dict[str, float]] = None,
    ):
        """
        Args:
            qdrant_store: QdrantEmbeddingStore instance
            knn_k: Number of nearest neighbors for KNN score
            cluster_method: 'kmeans' or 'dbscan'
            n_clusters: Number of clusters for K-means
            temporal_window_days: Days of history for temporal baseline
            weights: Method weights {'knn': 0.4, 'cluster': 0.3, 'temporal': 0.3}
        """
        self.qdrant_store = qdrant_store
        self.knn_k = knn_k
        self.cluster_method = cluster_method
        self.n_clusters = n_clusters
        self.temporal_window_days = temporal_window_days
        self.weights = weights or {"knn": 0.4, "cluster": 0.3, "temporal": 0.3}
        
    def detect(
        self, 
        df: pd.DataFrame,
        embeddings_dict: Optional[Dict[str, np.ndarray]] = None,
    ) -> Dict[str, Any]:
        """
        Detect anomalous templates using hybrid vector similarity.
        
        Args:
            df: DataFrame with 'template' column
            embeddings_dict: Optional pre-computed embeddings {template: vector}
            
        Returns:
            Dict with 'anomaly_scores', 'knn_scores', 'cluster_scores', 'temporal_scores'
        """
        if df.empty or "template" not in df.columns:
            return {
                "anomaly_scores": {},
                "knn_scores": {},
                "cluster_scores": {},
                "temporal_scores": {},
            }
        
        unique_templates = df["template"].astype(str).unique().tolist()
        if len(unique_templates) < 3:
            return {
                "anomaly_scores": {},
                "knn_scores": {},
                "cluster_scores": {},
                "temporal_scores": {},
            }
        
        # Get embeddings (from dict or Qdrant)
        if embeddings_dict is None:
            embeddings_dict = self._get_embeddings_from_qdrant(unique_templates)
        
        if not embeddings_dict or len(embeddings_dict) < 3:
            logger.warning("[VectorSimilarity] Not enough embeddings available")
            return {
                "anomaly_scores": {},
                "knn_scores": {},
                "cluster_scores": {},
                "temporal_scores": {},
            }
        
        # Convert to matrix
        templates_list = list(embeddings_dict.keys())
        embeddings_matrix = np.array([embeddings_dict[t] for t in templates_list])
        
        # Compute individual scores
        knn_scores = self._compute_knn_scores(embeddings_matrix, templates_list)
        cluster_scores = self._compute_cluster_scores(embeddings_matrix, templates_list)
        temporal_scores = self._compute_temporal_scores(embeddings_matrix, templates_list)
        
        # Combine scores
        anomaly_scores = {}
        for template in templates_list:
            combined = (
                self.weights["knn"] * knn_scores.get(template, 0.0) +
                self.weights["cluster"] * cluster_scores.get(template, 0.0) +
                self.weights["temporal"] * temporal_scores.get(template, 0.0)
            )
            anomaly_scores[template] = float(combined)
        
        return {
            "anomaly_scores": anomaly_scores,
            "knn_scores": knn_scores,
            "cluster_scores": cluster_scores,
            "temporal_scores": temporal_scores,
        }
    
    def _get_embeddings_from_qdrant(self, templates: List[str]) -> Dict[str, np.ndarray]:
        """Query Qdrant for template embeddings."""
        embeddings_dict = {}
        try:
            # Search for each template to get its embedding
            for template in templates:
                results = self.qdrant_store.search(template, top_k=1)
                if results and len(results) > 0:
                    # Get the embedding from Qdrant (assuming it's stored)
                    # For now, we'll re-embed using the same model
                    embedding = self.qdrant_store.model.encode([template], normalize_embeddings=True)[0]
                    embeddings_dict[template] = np.array(embedding)
        except Exception as e:
            logger.warning(f"[VectorSimilarity] Error getting embeddings: {e}")
        
        return embeddings_dict
    
    def _compute_knn_scores(
        self, 
        embeddings: np.ndarray, 
        templates: List[str]
    ) -> Dict[str, float]:
        """
        Compute KNN-based anomaly scores.
        Templates far from their K nearest neighbors get high scores.
        """
        from sklearn.metrics.pairwise import cosine_distances
        
        try:
            # Ensure embeddings are normalized and finite
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1.0, norms)  # Avoid division by zero
            embeddings = embeddings / norms
            
            # Replace any NaN or Inf values
            embeddings = np.nan_to_num(embeddings, nan=0.0, posinf=0.0, neginf=0.0)
            
            # Compute pairwise distances with error handling
            with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
                distances = cosine_distances(embeddings, embeddings)
                distances = np.nan_to_num(distances, nan=1.0, posinf=1.0, neginf=0.0)
            
            knn_scores = {}
            for i, template in enumerate(templates):
                # Get K nearest neighbors (excluding self)
                row = distances[i]
                k_nearest = np.sort(row)[1:self.knn_k + 1]  # Exclude self (dist=0)
                
                # Average distance to K neighbors
                avg_dist = k_nearest.mean() if len(k_nearest) > 0 else 0.0
                knn_scores[template] = float(avg_dist)
            
            # Normalize to [0, 1]
            if knn_scores:
                min_score = min(knn_scores.values())
                max_score = max(knn_scores.values())
                score_range = max_score - min_score if max_score > min_score else 1.0
                knn_scores = {
                    t: (s - min_score) / score_range 
                    for t, s in knn_scores.items()
                }
            
            return knn_scores
        except Exception as e:
            logger.warning(f"[VectorSimilarity] KNN scoring failed: {e}")
            return {t: 0.0 for t in templates}
    
    def _compute_cluster_scores(
        self, 
        embeddings: np.ndarray, 
        templates: List[str]
    ) -> Dict[str, float]:
        """
        Compute cluster-based anomaly scores.
        Templates far from their cluster centroid get high scores.
        """
        from sklearn.cluster import KMeans
        from sklearn.metrics.pairwise import cosine_distances
        
        try:
            # Ensure embeddings are normalized and finite
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1.0, norms)
            embeddings = embeddings / norms
            embeddings = np.nan_to_num(embeddings, nan=0.0, posinf=0.0, neginf=0.0)
            
            # Cluster embeddings
            n_clusters = min(self.n_clusters, len(templates) // 2)
            if n_clusters < 2:
                return {t: 0.0 for t in templates}
            
            with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
                kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
                labels = kmeans.fit_predict(embeddings)
                centroids = kmeans.cluster_centers_
            
            # Compute distance to assigned centroid
            cluster_scores = {}
            for i, template in enumerate(templates):
                cluster_id = labels[i]
                centroid = centroids[cluster_id].reshape(1, -1)
                embedding = embeddings[i].reshape(1, -1)
                
                with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
                    distance = cosine_distances(embedding, centroid)[0][0]
                    distance = np.nan_to_num(distance, nan=0.5, posinf=1.0, neginf=0.0)
                
                cluster_scores[template] = float(distance)
            
            # Normalize to [0, 1]
            if cluster_scores:
                min_score = min(cluster_scores.values())
                max_score = max(cluster_scores.values())
                score_range = max_score - min_score if max_score > min_score else 1.0
                cluster_scores = {
                    t: (s - min_score) / score_range 
                    for t, s in cluster_scores.items()
                }
            
            return cluster_scores
        except Exception as e:
            logger.warning(f"[VectorSimilarity] Cluster scoring failed: {e}")
            return {t: 0.0 for t in templates}
    
    def _compute_temporal_scores(
        self, 
        embeddings: np.ndarray, 
        templates: List[str]
    ) -> Dict[str, float]:
        """
        Compute temporal drift scores.
        Templates drifting from historical baseline get high scores.
        
        For now, we use the centroid of current templates as baseline.
        In production, this would compare against cached historical centroid.
        """
        from sklearn.metrics.pairwise import cosine_distances
        
        try:
            # Ensure embeddings are normalized and finite
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1.0, norms)
            embeddings = embeddings / norms
            embeddings = np.nan_to_num(embeddings, nan=0.0, posinf=0.0, neginf=0.0)
            
            # Compute baseline (centroid of all current templates)
            baseline = embeddings.mean(axis=0, keepdims=True)
            baseline_norm = np.linalg.norm(baseline)
            if baseline_norm > 0:
                baseline = baseline / baseline_norm
            baseline = np.nan_to_num(baseline, nan=0.0, posinf=0.0, neginf=0.0)
            
            # Compute distance from each template to baseline
            temporal_scores = {}
            with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
                distances = cosine_distances(embeddings, baseline)
                distances = np.nan_to_num(distances, nan=0.5, posinf=1.0, neginf=0.0)
            
            for i, template in enumerate(templates):
                temporal_scores[template] = float(distances[i][0])
            
            # Normalize to [0, 1]
            if temporal_scores:
                min_score = min(temporal_scores.values())
                max_score = max(temporal_scores.values())
                score_range = max_score - min_score if max_score > min_score else 1.0
                temporal_scores = {
                    t: (s - min_score) / score_range 
                    for t, s in temporal_scores.items()
                }
            
            return temporal_scores
        except Exception as e:
            logger.warning(f"[VectorSimilarity] Temporal scoring failed: {e}")
            return {t: 0.0 for t in templates}
        
        # Compute centroid of current templates (baseline)
        centroid = embeddings.mean(axis=0, keepdims=True)
        
        # Compute distance from each template to centroid
        distances = cosine_distances(embeddings, centroid).flatten()
        
        temporal_scores = {t: float(d) for t, d in zip(templates, distances)}
        
        # Normalize to [0, 1]
        if temporal_scores:
            min_score = min(temporal_scores.values())
            max_score = max(temporal_scores.values())
            score_range = max_score - min_score if max_score != min_score else 1.0
            temporal_scores = {
                t: (s - min_score) / score_range 
                for t, s in temporal_scores.items()
            }
        
        return temporal_scores


# ---------------------------------------------------------------------------
# Method 5: Semantic Novelty Detector (DEPRECATED - use VectorSimilarityDetector)
# ---------------------------------------------------------------------------

class SemanticNoveltyDetector:
    """
    DEPRECATED: Use VectorSimilarityDetector instead.
    
    Detects semantically novel templates by computing cosine distance from
    the domain centroid in embedding space.

    Templates that are far from the centroid represent new error patterns
    not seen in normal operation. Uses the same BGE embedding model already
    loaded by the RAG indexer to avoid extra memory.
    """

    def __init__(
        self,
        novelty_threshold: float = 0.65,
        shared_model: Optional[Any] = None,
        model_name: str = "BAAI/bge-small-en-v1.5",
    ):
        self.novelty_threshold = novelty_threshold
        self._model = shared_model
        self._model_name = model_name

    def detect(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Compute semantic novelty scores for unique templates.

        Returns:
            Dict with 'novelty_scores', 'novel_templates', 'centroid_distances'.
        """
        if df.empty or "template" not in df.columns:
            return {"novelty_scores": {}, "novel_templates": [], "centroid_distances": {}}

        unique_templates = df["template"].astype(str).unique().tolist()
        if len(unique_templates) < 3:
            return {"novelty_scores": {}, "novel_templates": [], "centroid_distances": {}}

        embeddings = self._get_embeddings(unique_templates)
        if embeddings is None:
            return {"novelty_scores": {}, "novel_templates": [], "centroid_distances": {}}

        centroid = embeddings.mean(axis=0, keepdims=True)

        from sklearn.metrics.pairwise import cosine_distances
        distances = cosine_distances(embeddings, centroid).flatten()

        dist_min, dist_max = distances.min(), distances.max()
        dist_range = dist_max - dist_min if dist_max != dist_min else 1.0
        norm_distances = (distances - dist_min) / dist_range

        novelty_scores = {}
        novel_templates = []
        centroid_distances = {}

        for i, template in enumerate(unique_templates):
            score = float(norm_distances[i])
            novelty_scores[template] = score
            centroid_distances[template] = float(distances[i])
            if score > self.novelty_threshold:
                novel_templates.append({
                    "template": template,
                    "novelty_score": score,
                    "centroid_distance": float(distances[i]),
                })

        novel_templates.sort(key=lambda x: -x["novelty_score"])

        return {
            "novelty_scores": novelty_scores,
            "novel_templates": novel_templates[:100],
            "centroid_distances": centroid_distances,
        }

    def _get_embeddings(self, texts: List[str]) -> Optional[np.ndarray]:
        """Encode texts using SentenceTransformer."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self._model_name)
            except Exception as e:
                logger.warning(f"[SemanticNovelty] Cannot load model: {e}")
                return None

        try:
            embeddings = self._model.encode(
                texts, show_progress_bar=False, batch_size=128, normalize_embeddings=True
            )
            return np.array(embeddings)
        except Exception as e:
            logger.warning(f"[SemanticNovelty] Encoding failed: {e}")
            return None


# ---------------------------------------------------------------------------
# Method 6: IsolationForest on Embeddings (NEW)
# ---------------------------------------------------------------------------

class IsolationForestEmbeddingDetector:
    """
    IsolationForest anomaly detection on 384-dim BGE embeddings.
    
    Replaces TF-IDF + IsolationForest with semantic embedding-based outlier
    detection. Operates directly on vector space for richer anomaly signals.
    
    Benefits:
    - Semantic outlier detection (vs. frequency-based)
    - Detects truly novel templates in embedding space
    - No TF-IDF vectorization overhead
    - Consistent with other embedding-based methods
    """
    
    def __init__(
        self,
        contamination: float = 0.08,
        n_estimators: int = 100,
        max_samples: str = 'auto',
        random_state: int = 42,
    ):
        """
        Args:
            contamination: Expected proportion of anomalies (default: 8%)
            n_estimators: Number of trees in forest
            max_samples: Samples to draw for training each tree
            random_state: Random seed for reproducibility
        """
        self.contamination = contamination
        self.n_estimators = n_estimators
        self.max_samples = max_samples
        self.random_state = random_state
        
    def detect(
        self, 
        df: pd.DataFrame,
        embeddings_dict: Dict[str, np.ndarray],
    ) -> Dict[str, Any]:
        """
        Detect anomalous templates using IsolationForest on embeddings.
        
        Args:
            df: DataFrame with template column
            embeddings_dict: {template_str: 384-dim embedding vector}
            
        Returns:
            Dict with 'anomaly_scores', 'anomalous_templates', 'n_anomalies'
        """
        if df.empty or "template" not in df.columns:
            return {
                "anomaly_scores": {},
                "anomalous_templates": [],
                "n_anomalies": 0,
            }
        
        unique_templates = df["template"].astype(str).unique().tolist()
        if len(unique_templates) < 3:
            return {
                "anomaly_scores": {},
                "anomalous_templates": [],
                "n_anomalies": 0,
            }
        
        # Build embedding matrix
        valid_templates = [t for t in unique_templates if t in embeddings_dict]
        if len(valid_templates) < 3:
            logger.warning("[IsolationForestEmbed] Not enough embeddings")
            return {
                "anomaly_scores": {},
                "anomalous_templates": [],
                "n_anomalies": 0,
            }
        
        embeddings = np.array([embeddings_dict[t] for t in valid_templates])
        
        # Fit IsolationForest
        from sklearn.ensemble import IsolationForest
        
        iso_forest = IsolationForest(
            contamination=self.contamination,
            n_estimators=self.n_estimators,
            max_samples=self.max_samples,
            random_state=self.random_state,
        )
        
        try:
            # Predict: -1 for anomalies, 1 for inliers
            predictions = iso_forest.fit_predict(embeddings)
            
            # Get anomaly scores (lower = more anomalous)
            scores = iso_forest.score_samples(embeddings)
            
            # Normalize to [0, 1] where 1 = most anomalous
            scores_norm = 1.0 - ((scores - scores.min()) / (scores.max() - scores.min() + 1e-10))
            
            anomaly_scores = {t: float(s) for t, s in zip(valid_templates, scores_norm)}
            anomalous_templates = [t for t, p in zip(valid_templates, predictions) if p == -1]
            
            logger.info(
                f"[IsolationForestEmbed] Detected {len(anomalous_templates)} anomalies "
                f"out of {len(valid_templates)} templates"
            )
            
            return {
                "anomaly_scores": anomaly_scores,
                "anomalous_templates": anomalous_templates,
                "n_anomalies": len(anomalous_templates),
            }
        except Exception as e:
            logger.warning(f"[IsolationForestEmbed] Detection failed: {e}")
            return {
                "anomaly_scores": {},
                "anomalous_templates": [],
                "n_anomalies": 0,
            }


# ---------------------------------------------------------------------------
# Method 5: Autoencoder -- Pattern Anomaly (DEPRECATED - use IsolationForestEmbeddingDetector)
# ---------------------------------------------------------------------------

class AutoencoderLogDetector:
    """
    DEPRECATED: Use IsolationForestEmbeddingDetector instead.
    
    Autoencoder-based anomaly detection for ripgrep-filtered log templates.
    
    Trains on TF-IDF vectors of "normal" template distributions, flags windows
    with high reconstruction error as anomalous. Excellent for detecting:
    - Never-before-seen error templates
    - Unusual combinations of known templates
    - Sudden shifts in template distribution patterns
    
    Architecture:
        Input: TF-IDF vector (sparse, ~1000-dim)
        Encoder: Linear(1000 → 128 → 64 → 32) with ReLU + Dropout(0.2)
        Decoder: Linear(32 → 64 → 128 → 1000) with ReLU + Dropout(0.2)
        Loss: MSE(input, reconstruction)
        
    Optimization for small template space:
        - Encoding dimension: 32 (aggressive compression ratio of 31:1)
        - Training: 18 epochs (sweet spot for <1000 features)
        - Anomaly threshold: 95th percentile of training reconstruction errors
    """

    def __init__(
        self,
        window_minutes: int = 15,
        encoding_dim: int = 32,
        epochs: int = 18,
        batch_size: int = 64,
        learning_rate: float = 0.001,
        threshold_percentile: float = 95.0,
        max_features: int = 1000,
        dropout: float = 0.2,
        cache_dir: Optional[Path] = None,
    ):
        self.window_minutes = window_minutes
        self.encoding_dim = encoding_dim
        self.epochs = epochs
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.threshold_percentile = threshold_percentile
        self.max_features = max_features
        self.dropout = dropout
        self.cache_dir = cache_dir
        self._model = None
        self._vectorizer: Optional[TfidfVectorizer] = None
        self._threshold = None

    def detect(self, df: pd.DataFrame, domain: str = "unknown") -> Dict[str, Any]:
        """
        Train autoencoder on template distributions and detect anomalous windows.

        Args:
            df: DataFrame with columns [timestamp, template].
            domain: Domain name for model caching.

        Returns:
            Dict with 'window_anomalies', 'reconstruction_errors', 'model_stats'.
        """
        try:
            import torch
            import torch.nn as nn
            from torch.utils.data import DataLoader, TensorDataset
        except ImportError:
            logger.warning("[Autoencoder] PyTorch not available, skipping detection")
            return {"window_anomalies": [], "reconstruction_errors": {}, "model_stats": {}}

        if df.empty or "template" not in df.columns:
            return {"window_anomalies": [], "reconstruction_errors": {}, "model_stats": {}}

        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.dropna(subset=["timestamp"])
        if df.empty:
            return {"window_anomalies": [], "reconstruction_errors": {}, "model_stats": {}}

        windows = self._build_windows(df)
        if len(windows) < 4:
            return {"window_anomalies": [], "reconstruction_errors": {}, "model_stats": {}}

        docs = [" ".join(w["templates"]) for w in windows]

        self._vectorizer = TfidfVectorizer(
            max_features=self.max_features,
            token_pattern=r"(?u)\S+",
        )
        tfidf_matrix = self._vectorizer.fit_transform(docs)
        X = tfidf_matrix.toarray()

        if X.shape[1] < 3:
            return {"window_anomalies": [], "reconstruction_errors": {}, 
                    "model_stats": {"reason": "too_few_features"}}

        input_dim = X.shape[1]
        X_tensor = torch.FloatTensor(X)
        dataset = TensorDataset(X_tensor, X_tensor)
        loader = DataLoader(dataset, batch_size=self.batch_size, shuffle=True)

        model = _AutoencoderModel(input_dim, self.encoding_dim, self.dropout)
        device = torch.device("cpu")
        model = model.to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=self.learning_rate)
        criterion = nn.MSELoss()

        model.train()
        for epoch in range(self.epochs):
            total_loss = 0.0
            for batch_x, _ in loader:
                batch_x = batch_x.to(device)
                optimizer.zero_grad()
                reconstructed = model(batch_x)
                loss = criterion(reconstructed, batch_x)
                loss.backward()
                optimizer.step()
                total_loss += loss.item()

        model.eval()
        with torch.no_grad():
            X_tensor_full = torch.FloatTensor(X).to(device)
            reconstructed = model(X_tensor_full)
            reconstruction_errors = torch.mean((X_tensor_full - reconstructed) ** 2, dim=1).cpu().numpy()

        self._threshold = np.percentile(reconstruction_errors, self.threshold_percentile)

        window_anomalies = []
        reconstruction_error_dict = {}
        for i, (error, window) in enumerate(zip(reconstruction_errors, windows)):
            window_key = window["start"].isoformat() if pd.notna(window["start"]) else f"window_{i}"
            reconstruction_error_dict[window_key] = float(error)
            
            if error > self._threshold:
                window_anomalies.append({
                    "window_index": i,
                    "window_start": window["start"].isoformat() if pd.notna(window["start"]) else "",
                    "window_end": window["end"].isoformat() if pd.notna(window["end"]) else "",
                    "reconstruction_error": float(error),
                    "threshold": float(self._threshold),
                    "severity": "high" if error > self._threshold * 1.5 else "medium",
                    "unique_templates": len(set(window["raw_templates"])),
                    "line_count": window["count"],
                })

        self._model = model
        window_anomalies.sort(key=lambda x: -x["reconstruction_error"])

        return {
            "window_anomalies": window_anomalies[:100],
            "reconstruction_errors": reconstruction_error_dict,
            "model_stats": {
                "input_dim": input_dim,
                "encoding_dim": self.encoding_dim,
                "num_windows": len(windows),
                "anomaly_threshold": float(self._threshold),
                "epochs": self.epochs,
                "mean_reconstruction_error": float(np.mean(reconstruction_errors)),
                "std_reconstruction_error": float(np.std(reconstruction_errors)),
            },
        }

    def _build_windows(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """Split DataFrame into fixed-size time windows."""
        freq = f"{self.window_minutes}min"
        df = df.set_index("timestamp").sort_index()

        windows = []
        for start, group in df.resample(freq):
            if group.empty:
                continue
            templates = group["template"].astype(str).tolist()
            tmpl_ids = [f"T{hash(t) % 100000:05d}" for t in templates]
            windows.append({
                "start": start,
                "end": start + pd.Timedelta(minutes=self.window_minutes),
                "templates": tmpl_ids,
                "raw_templates": templates,
                "count": len(templates),
            })
        return windows


class _AutoencoderModel:
    """Autoencoder model for template distribution reconstruction."""

    def __new__(cls, input_dim, encoding_dim, dropout):
        try:
            import torch.nn as nn
            return _AutoencoderModelImpl(input_dim, encoding_dim, dropout)
        except ImportError:
            return None


def _build_autoencoder_model_class():
    """Build the Autoencoder class lazily to avoid import errors when torch is unavailable."""
    try:
        import torch
        import torch.nn as nn

        class AutoencoderModelImpl(nn.Module):
            def __init__(self, input_dim, encoding_dim, dropout):
                super().__init__()
                self.input_dim = input_dim
                self.encoding_dim = encoding_dim
                
                # Encoder: input -> 128 -> 64 -> encoding_dim
                self.encoder = nn.Sequential(
                    nn.Linear(input_dim, 128),
                    nn.ReLU(),
                    nn.Dropout(dropout),
                    nn.Linear(128, 64),
                    nn.ReLU(),
                    nn.Dropout(dropout),
                    nn.Linear(64, encoding_dim),
                    nn.ReLU(),
                )
                
                # Decoder: encoding_dim -> 64 -> 128 -> input
                self.decoder = nn.Sequential(
                    nn.Linear(encoding_dim, 64),
                    nn.ReLU(),
                    nn.Dropout(dropout),
                    nn.Linear(64, 128),
                    nn.ReLU(),
                    nn.Dropout(dropout),
                    nn.Linear(128, input_dim),
                )

            def forward(self, x):
                encoded = self.encoder(x)
                decoded = self.decoder(encoded)
                return decoded

        return AutoencoderModelImpl
    except ImportError:
        return None


_AutoencoderModelImpl = _build_autoencoder_model_class()


# ---------------------------------------------------------------------------
# Ensemble Scorer
# ---------------------------------------------------------------------------

class EnsembleScorer:
    """
    Combines anomaly signals from all detectors into a single ranked output.

    NEW: Supports vector-based methods (vector_similarity, GRU-embedding, isolation_forest)
    and legacy methods (tfidf, deeplog, frequency, semantic, autoencoder).

    Each method contributes a per-template score in [0, 1]. The ensemble
    computes a weighted average and returns the top anomalies with
    human-readable explanations.
    """

    DEFAULT_WEIGHTS = {
        # NEW: Vector-based methods (preferred)
        "vector_similarity": 0.40,  # KNN + cluster + temporal
        "gru": 0.40,                # GRU on embeddings
        "isolation_forest": 0.20,   # IsolationForest on embeddings
        
        # Legacy methods (deprecated)
        "tfidf": 0.20,
        "autoencoder": 0.25,
        "frequency": 0.15,
        "deeplog": 0.05,
        "semantic": 0.10,
    }

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = weights or self.DEFAULT_WEIGHTS

    def score(
        self,
        df: pd.DataFrame,
        tfidf_results: Dict[str, Any],
        deeplog_results: Dict[str, Any],
        frequency_results: Dict[str, Any],
        semantic_results: Dict[str, Any],
        gru_results: Optional[Dict[str, Any]] = None,
        autoencoder_results: Optional[Dict[str, Any]] = None,
        vector_results: Optional[Dict[str, Any]] = None,  # NEW
        isolation_forest_results: Optional[Dict[str, Any]] = None,  # NEW
        top_n: int = 50,
        domain: str = "unknown",
    ) -> List[AnomalyResult]:
        """
        Combine all detector outputs into ranked anomaly results.

        Returns:
            List of AnomalyResult sorted by descending anomaly score.
        """
        all_templates = set()
        if not df.empty and "template" in df.columns:
            all_templates = set(df["template"].astype(str).unique())

        template_scores: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {
                "tfidf": 0.0, "deeplog": 0.0, "gru": 0.0, 
                "autoencoder": 0.0, "frequency": 0.0, "semantic": 0.0,
                "vector_similarity": 0.0, "isolation_forest": 0.0,  # NEW
            }
        )

        # NEW: Vector similarity scores
        if vector_results:
            vector_scores = vector_results.get("anomaly_scores", {})
            for tmpl, score in vector_scores.items():
                template_scores[tmpl]["vector_similarity"] = score

        # NEW: IsolationForest scores
        if isolation_forest_results:
            iso_scores = isolation_forest_results.get("anomaly_scores", {})
            for tmpl, score in iso_scores.items():
                template_scores[tmpl]["isolation_forest"] = score

        # TF-IDF scores
        tfidf_importances = tfidf_results.get("template_importances", {})
        for w in tfidf_results.get("anomalous_windows", []):
            score = w.get("anomaly_score", 0.0)
            for tmpl in all_templates:
                tid = f"T{hash(tmpl) % 100000:05d}"
                if tid in tfidf_importances:
                    template_scores[tmpl]["tfidf"] = max(
                        template_scores[tmpl]["tfidf"], score * tfidf_importances.get(tid, 0.0)
                    )

        # DeepLog scores
        anomaly_rate = deeplog_results.get("anomaly_rate", 0.0)
        for seq in deeplog_results.get("sequence_anomalies", []):
            tmpl = seq.get("actual_template", "")
            prob = 1.0 - seq.get("actual_probability", 1.0)
            if tmpl:
                template_scores[tmpl]["deeplog"] = max(
                    template_scores[tmpl]["deeplog"], prob
                )

        # Frequency scores
        for anom in frequency_results.get("template_anomalies", []):
            tmpl = anom.get("template", "")
            zscore = abs(anom.get("zscore", 0.0))
            norm = min(zscore / 5.0, 1.0)
            if tmpl:
                template_scores[tmpl]["frequency"] = max(
                    template_scores[tmpl]["frequency"], norm
                )

        # Semantic scores
        novelty_scores = semantic_results.get("novelty_scores", {})
        for tmpl, nscore in novelty_scores.items():
            template_scores[tmpl]["semantic"] = max(
                template_scores[tmpl]["semantic"], nscore
            )

        # GRU scores (NEW: supports both embedding and ID mode)
        if gru_results:
            for seq in gru_results.get("sequence_anomalies", []):
                tmpl = seq.get("actual_template", "")
                # Check for embedding mode (cosine_similarity) or ID mode (actual_probability)
                if "cosine_similarity" in seq:
                    # Embedding mode: low cosine = high anomaly
                    score = 1.0 - seq["cosine_similarity"]
                else:
                    # ID mode: low probability = high anomaly
                    prob = 1.0 - seq.get("actual_probability", 1.0)
                    score = prob
                
                if tmpl:
                    template_scores[tmpl]["gru"] = max(
                        template_scores[tmpl]["gru"], score
                    )

        # Autoencoder scores
        if autoencoder_results:
            window_anomalies = autoencoder_results.get("window_anomalies", [])
            if window_anomalies:
                reconstruction_errors = autoencoder_results.get("reconstruction_errors", {})
                threshold = autoencoder_results.get("model_stats", {}).get("anomaly_threshold", 0.0)
                if threshold > 0:
                    for tmpl in all_templates:
                        max_score = 0.0
                        for anom in window_anomalies:
                            error = anom.get("reconstruction_error", 0.0)
                            norm_score = min(error / threshold, 2.0) / 2.0
                            max_score = max(max_score, norm_score)
                        if max_score > 0:
                            template_scores[tmpl]["autoencoder"] = max_score

        results = []
        template_counts = Counter(df["template"].astype(str)) if not df.empty else {}

        for tmpl, method_scores in template_scores.items():
            active_weights = {}
            for method, w in self.weights.items():
                if method_scores.get(method, 0.0) > 0:
                    active_weights[method] = w

            if not active_weights:
                continue

            total_weight = sum(active_weights.values())
            if total_weight == 0:
                continue

            combined = sum(
                method_scores[m] * w for m, w in active_weights.items()
            ) / total_weight

            evidence = []
            # NEW: Vector-based evidence
            if method_scores["vector_similarity"] > 0.3:
                evidence.append(f"Anomalous in vector space (KNN+cluster+temporal score={method_scores['vector_similarity']:.2f})")
            if method_scores["isolation_forest"] > 0.3:
                evidence.append(f"Isolated in embedding space (IsolationForest score={method_scores['isolation_forest']:.2f})")
            
            # Legacy evidence
            if method_scores["tfidf"] > 0.3:
                evidence.append(f"Unusual in TF-IDF distribution (score={method_scores['tfidf']:.2f})")
            if method_scores["gru"] > 0.3:
                evidence.append(f"Unexpected in GRU sequence model (score={method_scores['gru']:.2f})")
            if method_scores["autoencoder"] > 0.3:
                evidence.append(f"High reconstruction error in pattern (score={method_scores['autoencoder']:.2f})")
            if method_scores["deeplog"] > 0.3:
                evidence.append(f"Unexpected in LSTM sequence model (prob_gap={method_scores['deeplog']:.2f})")
            if method_scores["frequency"] > 0.3:
                evidence.append(f"Abnormal frequency pattern (score={method_scores['frequency']:.2f})")
            if method_scores["semantic"] > 0.3:
                evidence.append(f"Semantically novel template (novelty={method_scores['semantic']:.2f})")

            if not evidence:
                continue

            sample_lines = []
            template_domain = None
            if not df.empty:
                matching = df[df["template"].astype(str) == tmpl]
                if not matching.empty:
                    if "loglines" in matching.columns:
                        sample_lines = matching["loglines"].head(3).tolist()
                    # Get domain from the dataframe if available
                    if "domain" in matching.columns:
                        template_domain = matching["domain"].iloc[0]

            # Use template's domain if available, otherwise fall back to analysis domain
            category = template_domain if template_domain else (domain if domain != "all" else None)

            results.append(AnomalyResult(
                template=tmpl,
                score=float(combined),
                methods=dict(method_scores),
                evidence=evidence,
                sample_loglines=sample_lines,
                count=template_counts.get(tmpl, 0),
                category=category,
            ))

        results.sort(key=lambda x: -x.score)
        return results[:top_n]


# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------

class LogAnomalyPipeline:
    """
    End-to-end log anomaly detection pipeline.

    NEW: Vector-based architecture leveraging Qdrant embeddings:
    - VectorSimilarityDetector (KNN + cluster + temporal)
    - GRU on embeddings
    - IsolationForest on embeddings

    Loads a Drain3 parquet, runs all detectors, and returns a ranked
    anomaly report with ensemble scores and human-readable explanations.

    Designed for single-CPE analysis. For fleet-level (500 CPE) analysis,
    use ``FleetLogAnalyzer`` in ``fleet_analyzer.py``.
    """

    def __init__(
        self,
        window_minutes: int = 15,
        # NEW parameters
        enable_vector_similarity: bool = True,
        enable_gru: bool = True,
        enable_isolation_forest: bool = True,
        vector_weights: Optional[Dict[str, float]] = None,
        qdrant_url: str = "http://localhost:6333",
        qdrant_collection: Optional[str] = None,
        # Legacy parameters (deprecated)
        tfidf_contamination: float = 0.05,
        gru_epochs: int = 12,
        gru_top_k: int = 9,
        autoencoder_epochs: int = 18,
        autoencoder_encoding_dim: int = 32,
        deeplog_epochs: int = 20,
        deeplog_top_k: int = 9,
        frequency_zscore: float = 3.0,
        novelty_threshold: float = 0.65,
        ensemble_weights: Optional[Dict[str, float]] = None,
        shared_embedding_model: Optional[Any] = None,
        enable_autoencoder: bool = False,  # Deprecated
        enable_deeplog: bool = False,  # Deprecated
        enable_semantic: bool = False,  # Deprecated
        cache_dir: Optional[Path] = None,
    ):
        # NEW: Vector-based detectors
        # Note: We don't create QdrantEmbeddingStore here to avoid loading the 700MB model
        # We only need the Qdrant client URL and collection name for fetching vectors
        self.qdrant_url = qdrant_url
        self.qdrant_collection = qdrant_collection or "default"
        
        self.vector_detector = VectorSimilarityDetector(
            qdrant_store=None,  # Not needed for now
            knn_k=10,
            cluster_method="kmeans",
            n_clusters=5,
            temporal_window_days=7,
            weights=vector_weights or {"knn": 0.4, "cluster": 0.3, "temporal": 0.3},
        ) if enable_vector_similarity else None
        
        self.gru_detector = GRULogDetector(
            epochs=gru_epochs,
            top_k=gru_top_k,
            cache_dir=cache_dir,
            use_embeddings=True,  # NEW: Use embeddings
            embedding_dim=384,
            hidden_size=128,  # Increased for embedding mode
        ) if enable_gru else None
        
        self.isolation_forest_detector = IsolationForestEmbeddingDetector(
            contamination=tfidf_contamination,
            n_estimators=100,
        ) if enable_isolation_forest else None
        
        # Legacy detectors (deprecated, kept for backward compatibility)
        self.tfidf_detector = TfIdfAnomalyDetector(
            window_minutes=window_minutes,
            contamination=tfidf_contamination,
        ) if not enable_isolation_forest else None
        
        self.autoencoder_detector = AutoencoderLogDetector(
            window_minutes=window_minutes,
            encoding_dim=autoencoder_encoding_dim,
            epochs=autoencoder_epochs,
            cache_dir=cache_dir,
        ) if enable_autoencoder else None
        
        self.deeplog_detector = DeepLogDetector(
            epochs=deeplog_epochs,
            top_k=deeplog_top_k,
        ) if enable_deeplog else None

        self.frequency_detector = FrequencyAnomalyDetector(
            window_minutes=window_minutes,
            zscore_threshold=frequency_zscore,
        ) if not enable_vector_similarity else None
        
        self.semantic_detector = SemanticNoveltyDetector(
            novelty_threshold=novelty_threshold,
            shared_model=shared_embedding_model,
        ) if enable_semantic else None

        self.scorer = EnsembleScorer(weights=ensemble_weights)
        
        # Store configuration
        self.enable_vector_similarity = enable_vector_similarity
        self.enable_gru = enable_gru
        self.enable_isolation_forest = enable_isolation_forest

    def analyze(
        self,
        parquet_path: Optional[str] = None,
        df: Optional[pd.DataFrame] = None,
        cpe_id: str = "",
        domain: str = "",
        top_n: int = 50,
    ) -> LogAnomalyReport:
        """
        Run the full anomaly detection pipeline on a single CPE domain.

        Args:
            parquet_path: Path to Drain3 parquet file.
            df: Alternative: pre-loaded DataFrame.
            cpe_id: CPE identifier for the report.
            domain: Domain name (e.g. "wireless").
            top_n: Max anomalies to return.

        Returns:
            LogAnomalyReport with ranked anomalies and method statistics.
        """
        import time
        start_time = time.perf_counter()

        if df is None and parquet_path:
            path = Path(parquet_path)
            if not path.exists():
                return self._empty_report(cpe_id, domain, 0.0)
            df = pd.read_parquet(path)

        if df is None or df.empty:
            return self._empty_report(cpe_id, domain, 0.0)

        required_cols = {"timestamp", "template"}
        if not required_cols.issubset(df.columns):
            logger.warning(
                f"[LogAnomalyPipeline] Missing columns: "
                f"{required_cols - set(df.columns)}"
            )
            return self._empty_report(cpe_id, domain, 0.0)

        logger.info(
            f"[LogAnomalyPipeline] Analyzing {len(df)} lines, "
            f"cpe={cpe_id}, domain={domain}"
        )

        # NEW: Get embeddings for all templates if using vector-based methods
        embeddings_dict = {}
        if self.enable_vector_similarity or self.enable_gru or self.enable_isolation_forest:
            unique_templates = df["template"].astype(str).unique().tolist()
            logger.info(f"[LogAnomalyPipeline] Fetching embeddings for {len(unique_templates)} templates from Qdrant")
            logger.info(f"[LogAnomalyPipeline] Using collection: {self.qdrant_collection}")
            
            # Try to retrieve embeddings from Qdrant (they're already stored there!)
            # Use direct Qdrant client to avoid loading the 700MB model
            try:
                from qdrant_client import QdrantClient
                from qdrant_client.models import Filter, FieldCondition, MatchAny
                
                qdrant_client = QdrantClient(url=self.qdrant_url)
                
                # OPTIMIZED: Query only the templates we need for this CPE
                # Use filter to retrieve specific templates by their payload
                try:
                    # Try to use filter for targeted retrieval
                    scroll_result = qdrant_client.scroll(
                        collection_name=self.qdrant_collection,
                        scroll_filter=Filter(
                            must=[
                                FieldCondition(
                                    key="template",
                                    match=MatchAny(any=unique_templates[:100])  # Qdrant has limits on filter size
                                )
                            ]
                        ) if len(unique_templates) <= 100 else None,  # Fall back to full scroll if too many
                        limit=min(len(unique_templates) * 2, 10000),  # Fetch a bit more than needed
                        with_vectors=True,  # IMPORTANT: Include vectors in response
                        with_payload=True,
                    )
                except Exception:
                    # If filter fails, fall back to full scroll (legacy behavior)
                    scroll_result = qdrant_client.scroll(
                        collection_name=self.qdrant_collection,
                        limit=10000,  # Fetch all
                        with_vectors=True,
                        with_payload=True,
                    )
                
                # Build a mapping of template -> embedding
                qdrant_embeddings = {}
                for point in scroll_result[0]:  # scroll returns (points, next_offset)
                    if point.payload and "template" in point.payload:
                        template_text = point.payload["template"]
                        if point.vector:  # Vector is the embedding
                            qdrant_embeddings[template_text] = np.array(point.vector)
                
                # Map to our unique templates
                for template in unique_templates:
                    if template in qdrant_embeddings:
                        embeddings_dict[template] = qdrant_embeddings[template]
                
                logger.info(
                    f"[LogAnomalyPipeline] Retrieved {len(qdrant_embeddings)} embeddings from Qdrant, "
                    f"matched {len(embeddings_dict)}/{len(unique_templates)} needed templates"
                )
                
            except Exception as e:
                logger.warning(f"[LogAnomalyPipeline] Qdrant retrieval failed: {e}")
                logger.info(f"[LogAnomalyPipeline] Falling back to re-embedding all templates")
            
            # Re-embed any missing templates (fallback)
            if len(embeddings_dict) < len(unique_templates):
                missing = [t for t in unique_templates if t not in embeddings_dict]
                logger.info(f"[LogAnomalyPipeline] Re-embedding {len(missing)} missing templates")
                try:
                    # Thread-safe model loading using global lock
                    with _MODEL_LOAD_LOCK:
                        from sentence_transformers import SentenceTransformer
                        # Force CPU device to avoid MPS (Metal) issues in parallel/threaded contexts
                        # Set trust_remote_code=True explicitly to avoid warnings
                        model = SentenceTransformer(
                            "BAAI/bge-small-en-v1.5", 
                            device="cpu",
                            trust_remote_code=False
                        )
                    
                    # Embedding can happen outside the lock (model is now loaded)
                    missing_embeddings = model.encode(
                        missing, 
                        show_progress_bar=False, 
                        batch_size=128, 
                        normalize_embeddings=True
                    )
                    for t, emb in zip(missing, missing_embeddings):
                        embeddings_dict[t] = emb
                    logger.info(f"[LogAnomalyPipeline] Successfully re-embedded {len(missing)} templates")
                except Exception as e:
                    logger.error(f"[LogAnomalyPipeline] Re-embedding failed: {e}")
            
            logger.info(f"[LogAnomalyPipeline] Total embeddings ready: {len(embeddings_dict)}/{len(unique_templates)}")

        # Run detectors
        vector_results = (
            self.vector_detector.detect(df, embeddings_dict=embeddings_dict)
            if self.vector_detector
            else {"anomaly_scores": {}, "method_scores": {}}
        )

        gru_results = (
            self.gru_detector.detect(df, domain=domain, embeddings_dict=embeddings_dict)
            if self.gru_detector
            else {"sequence_anomalies": [], "anomaly_rate": 0.0, "model_stats": {}}
        )
        
        isolation_forest_results = (
            self.isolation_forest_detector.detect(df, embeddings_dict=embeddings_dict)
            if self.isolation_forest_detector
            else {"anomaly_scores": {}, "anomalous_templates": [], "n_anomalies": 0}
        )

        # Legacy detectors (only if new ones are disabled)
        tfidf_results = (
            self.tfidf_detector.detect(df)
            if self.tfidf_detector
            else {"anomalous_windows": [], "window_scores": []}
        )
        
        autoencoder_results = (
            self.autoencoder_detector.detect(df, domain=domain)
            if self.autoencoder_detector
            else {"window_anomalies": [], "reconstruction_errors": {}, "model_stats": {}}
        )

        deeplog_results = (
            self.deeplog_detector.detect(df)
            if self.deeplog_detector
            else {"sequence_anomalies": [], "anomaly_rate": 0.0, "model_stats": {}}
        )

        frequency_results = (
            self.frequency_detector.detect(df)
            if self.frequency_detector
            else {"template_anomalies": [], "burst_events": []}
        )

        semantic_results = (
            self.semantic_detector.detect(df)
            if self.semantic_detector
            else {"novelty_scores": {}, "novel_templates": [], "centroid_distances": {}}
        )

        anomalies = self.scorer.score(
            df, tfidf_results, deeplog_results, frequency_results, semantic_results,
            gru_results=gru_results, autoencoder_results=autoencoder_results,
            vector_results=vector_results,  # NEW
            isolation_forest_results=isolation_forest_results,  # NEW
            top_n=top_n, domain=domain,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        method_stats = {}
        
        # NEW methods
        if self.enable_vector_similarity:
            method_stats["vector_similarity"] = {
                "anomalous_templates": len(vector_results.get("anomaly_scores", {})),
                "method_scores": vector_results.get("method_scores", {}),
            }
        
        if self.enable_gru:
            method_stats["gru"] = {
                "anomaly_rate": gru_results.get("anomaly_rate", 0.0),
                "sequence_anomalies": len(gru_results.get("sequence_anomalies", [])),
                **gru_results.get("model_stats", {}),
            }
        
        if self.enable_isolation_forest:
            method_stats["isolation_forest"] = {
                "anomalous_templates": isolation_forest_results.get("n_anomalies", 0),
            }
        
        # Legacy methods (if enabled)
        if self.tfidf_detector:
            method_stats["tfidf"] = {
                "anomalous_windows": len(tfidf_results.get("anomalous_windows", [])),
                "total_windows": len(tfidf_results.get("window_scores", [])),
            }
        
        if self.autoencoder_detector:
            method_stats["autoencoder"] = {
                "window_anomalies": len(autoencoder_results.get("window_anomalies", [])),
                **autoencoder_results.get("model_stats", {}),
            }
        
        if self.deeplog_detector:
            method_stats["deeplog"] = {
                "anomaly_rate": deeplog_results.get("anomaly_rate", 0.0),
                "sequence_anomalies": len(deeplog_results.get("sequence_anomalies", [])),
                **deeplog_results.get("model_stats", {}),
            }
        
        if self.frequency_detector:
            method_stats["frequency"] = {
                "template_anomalies": len(frequency_results.get("template_anomalies", [])),
                "burst_events": len(frequency_results.get("burst_events", [])),
            }
        
        if self.semantic_detector:
            method_stats["semantic"] = {
                "novel_templates": len(semantic_results.get("novel_templates", [])),
            }

        return LogAnomalyReport(
            cpe_id=cpe_id,
            domain=domain,
            total_lines=len(df),
            total_templates=df["template"].nunique(),
            anomaly_count=len(anomalies),
            anomalies=anomalies,
            method_stats=method_stats,
            processing_time_ms=elapsed_ms,
        )

    def _empty_report(self, cpe_id: str, domain: str, elapsed: float) -> LogAnomalyReport:
        return LogAnomalyReport(
            cpe_id=cpe_id, domain=domain, total_lines=0, total_templates=0,
            anomaly_count=0, anomalies=[], method_stats={},
            processing_time_ms=elapsed,
        )
