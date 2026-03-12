"""
ML Model Caching System
========================

Caches trained ML models (GRU, Autoencoder) per domain to avoid retraining
on every analysis run. Models are saved to disk with metadata (vocabulary,
hyperparameters) and loaded when compatible.

Cache Structure:
    user_uploads/{user_id}/{project_id}/.ml_cache/{domain}/
        ├── gru_model.pt           # PyTorch GRU weights
        ├── gru_vocab.json         # Template vocabulary + metadata
        ├── autoencoder_model.pt   # PyTorch Autoencoder weights
        ├── autoencoder_meta.json  # TF-IDF vectorizer + metadata

Cache Invalidation:
    - Models expire after 7 days (configurable)
    - Models invalidated if template count changes > 20%
    - Models invalidated if hyperparameters change
"""

import os
import json
import logging
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
import pickle

logger = logging.getLogger(__name__)


class ModelCache:
    """
    Manages persistent caching of trained ML models for log anomaly detection.
    """

    def __init__(
        self,
        cache_dir: Path,
        max_age_days: int = 7,
        vocab_change_threshold: float = 0.20,
    ):
        """
        Initialize model cache.

        Args:
            cache_dir: Root directory for model cache (e.g., project/.ml_cache)
            max_age_days: Number of days before cached models expire
            vocab_change_threshold: Maximum allowed vocabulary size change (0.20 = 20%)
        """
        self.cache_dir = Path(cache_dir)
        self.max_age_days = max_age_days
        self.vocab_change_threshold = vocab_change_threshold

    def get_cache_key(self, domain: str, model_type: str) -> Path:
        """
        Get cache directory path for a specific domain and model type.

        Args:
            domain: Domain name (e.g., "wireless", "system")
            model_type: "gru" or "autoencoder"

        Returns:
            Path to cache directory
        """
        domain_safe = domain.replace("/", "_").replace("..", "_")
        return self.cache_dir / domain_safe / model_type

    def _compute_config_hash(self, config: Dict[str, Any]) -> str:
        """Compute hash of model hyperparameters for cache validation."""
        config_str = json.dumps(config, sort_keys=True)
        return hashlib.md5(config_str.encode()).hexdigest()[:8]

    def save_gru_model(
        self,
        domain: str,
        model,
        vocab: Dict[str, int],
        config: Dict[str, Any],
    ) -> bool:
        """
        Save trained GRU model to cache.

        Args:
            domain: Domain name
            model: PyTorch GRU model
            vocab: Template vocabulary {template: idx}
            config: Model hyperparameters

        Returns:
            True if saved successfully
        """
        try:
            import torch

            cache_path = self.get_cache_key(domain, "gru")
            cache_path.mkdir(parents=True, exist_ok=True)

            # Save model weights
            model_file = cache_path / "model.pt"
            torch.save(model.state_dict(), model_file)

            # Save vocabulary and metadata
            meta = {
                "vocab": vocab,
                "vocab_size": len(vocab),
                "config": config,
                "config_hash": self._compute_config_hash(config),
                "cached_at": datetime.now().isoformat(),
                "domain": domain,
            }
            meta_file = cache_path / "metadata.json"
            with open(meta_file, "w") as f:
                json.dump(meta, f, indent=2)

            logger.info(f"[ModelCache] Saved GRU model for domain '{domain}' (vocab_size={len(vocab)})")
            return True

        except Exception as e:
            logger.warning(f"[ModelCache] Failed to save GRU model for '{domain}': {e}")
            return False

    def load_gru_model(
        self,
        domain: str,
        current_vocab_size: int,
        config: Dict[str, Any],
        model_class: Any,
    ) -> Optional[Tuple[Any, Dict[str, int]]]:
        """
        Load cached GRU model if valid.

        Args:
            domain: Domain name
            current_vocab_size: Current template vocabulary size
            config: Current model hyperparameters
            model_class: GRU model class for instantiation

        Returns:
            (model, vocab) if cache valid, None otherwise
        """
        try:
            import torch

            cache_path = self.get_cache_key(domain, "gru")
            model_file = cache_path / "model.pt"
            meta_file = cache_path / "metadata.json"

            if not model_file.exists() or not meta_file.exists():
                logger.debug(f"[ModelCache] GRU cache miss for domain '{domain}'")
                return None

            # Load metadata
            with open(meta_file, "r") as f:
                meta = json.load(f)

            # Validate cache
            if not self._is_cache_valid(meta, current_vocab_size, config):
                logger.info(f"[ModelCache] GRU cache invalid for domain '{domain}', will retrain")
                return None

            # Load model
            vocab = meta["vocab"]
            vocab_size = len(vocab)
            hidden_size = config.get("hidden_size", 64)
            num_layers = config.get("num_layers", 2)
            dropout = config.get("dropout", 0.2)

            model = model_class(vocab_size, hidden_size, num_layers, dropout)
            model.load_state_dict(torch.load(model_file, map_location="cpu"))
            model.eval()

            logger.info(f"[ModelCache] Loaded GRU model for domain '{domain}' from cache")
            return (model, vocab)

        except Exception as e:
            logger.warning(f"[ModelCache] Failed to load GRU model for '{domain}': {e}")
            return None

    def save_autoencoder_model(
        self,
        domain: str,
        model,
        vectorizer,
        threshold: float,
        config: Dict[str, Any],
    ) -> bool:
        """
        Save trained Autoencoder model to cache.

        Args:
            domain: Domain name
            model: PyTorch Autoencoder model
            vectorizer: Fitted TfidfVectorizer
            threshold: Anomaly detection threshold
            config: Model hyperparameters

        Returns:
            True if saved successfully
        """
        try:
            import torch

            cache_path = self.get_cache_key(domain, "autoencoder")
            cache_path.mkdir(parents=True, exist_ok=True)

            # Save model weights
            model_file = cache_path / "model.pt"
            torch.save(model.state_dict(), model_file)

            # Save vectorizer
            vectorizer_file = cache_path / "vectorizer.pkl"
            with open(vectorizer_file, "wb") as f:
                pickle.dump(vectorizer, f)

            # Save metadata
            meta = {
                "threshold": threshold,
                "vocab_size": len(vectorizer.vocabulary_) if vectorizer else 0,
                "config": config,
                "config_hash": self._compute_config_hash(config),
                "cached_at": datetime.now().isoformat(),
                "domain": domain,
            }
            meta_file = cache_path / "metadata.json"
            with open(meta_file, "w") as f:
                json.dump(meta, f, indent=2)

            logger.info(f"[ModelCache] Saved Autoencoder model for domain '{domain}'")
            return True

        except Exception as e:
            logger.warning(f"[ModelCache] Failed to save Autoencoder model for '{domain}': {e}")
            return False

    def load_autoencoder_model(
        self,
        domain: str,
        current_feature_count: int,
        config: Dict[str, Any],
        model_class: Any,
    ) -> Optional[Tuple[Any, Any, float]]:
        """
        Load cached Autoencoder model if valid.

        Args:
            domain: Domain name
            current_feature_count: Current feature count (approx vocab size)
            config: Current model hyperparameters
            model_class: Autoencoder model class

        Returns:
            (model, vectorizer, threshold) if cache valid, None otherwise
        """
        try:
            import torch

            cache_path = self.get_cache_key(domain, "autoencoder")
            model_file = cache_path / "model.pt"
            vectorizer_file = cache_path / "vectorizer.pkl"
            meta_file = cache_path / "metadata.json"

            if not all(p.exists() for p in [model_file, vectorizer_file, meta_file]):
                logger.debug(f"[ModelCache] Autoencoder cache miss for domain '{domain}'")
                return None

            # Load metadata
            with open(meta_file, "r") as f:
                meta = json.load(f)

            # Validate cache
            if not self._is_cache_valid(meta, current_feature_count, config):
                logger.info(f"[ModelCache] Autoencoder cache invalid for domain '{domain}', will retrain")
                return None

            # Load vectorizer
            with open(vectorizer_file, "rb") as f:
                vectorizer = pickle.load(f)

            # Load model
            input_dim = len(vectorizer.vocabulary_)
            encoding_dim = config.get("encoding_dim", 32)
            dropout = config.get("dropout", 0.2)

            model = model_class(input_dim, encoding_dim, dropout)
            model.load_state_dict(torch.load(model_file, map_location="cpu"))
            model.eval()

            threshold = meta["threshold"]

            logger.info(f"[ModelCache] Loaded Autoencoder model for domain '{domain}' from cache")
            return (model, vectorizer, threshold)

        except Exception as e:
            logger.warning(f"[ModelCache] Failed to load Autoencoder model for '{domain}': {e}")
            return None

    def _is_cache_valid(
        self,
        meta: Dict[str, Any],
        current_size: int,
        config: Dict[str, Any],
    ) -> bool:
        """
        Check if cached model is still valid.

        Invalidation rules:
            - Cache older than max_age_days
            - Vocabulary/feature size changed by > vocab_change_threshold
            - Hyperparameters changed (config_hash mismatch)
        """
        # Check age
        try:
            cached_at = datetime.fromisoformat(meta["cached_at"])
            age = datetime.now() - cached_at
            if age > timedelta(days=self.max_age_days):
                logger.debug(f"[ModelCache] Cache expired (age={age.days}d)")
                return False
        except Exception:
            return False

        # Check vocabulary size change
        cached_size = meta.get("vocab_size", 0)
        if cached_size == 0:
            return False

        size_change = abs(current_size - cached_size) / cached_size
        if size_change > self.vocab_change_threshold:
            logger.debug(
                f"[ModelCache] Vocab size changed too much: "
                f"{cached_size} -> {current_size} ({size_change:.1%})"
            )
            return False

        # Check config hash
        current_hash = self._compute_config_hash(config)
        cached_hash = meta.get("config_hash", "")
        if current_hash != cached_hash:
            logger.debug(f"[ModelCache] Config mismatch: {cached_hash} != {current_hash}")
            return False

        return True

    def clear_cache(self, domain: Optional[str] = None):
        """
        Clear cached models.

        Args:
            domain: If provided, clear only this domain. Otherwise clear all.
        """
        try:
            if domain:
                domain_path = self.cache_dir / domain.replace("/", "_").replace("..", "_")
                if domain_path.exists():
                    import shutil
                    shutil.rmtree(domain_path)
                    logger.info(f"[ModelCache] Cleared cache for domain '{domain}'")
            else:
                if self.cache_dir.exists():
                    import shutil
                    shutil.rmtree(self.cache_dir)
                    logger.info(f"[ModelCache] Cleared all cached models")
        except Exception as e:
            logger.warning(f"[ModelCache] Failed to clear cache: {e}")
