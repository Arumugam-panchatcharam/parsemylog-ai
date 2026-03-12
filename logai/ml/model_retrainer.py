"""
ML Model Retrainer with User Feedback
======================================

Retrains ML models (GRU, Autoencoder) using accumulated user feedback data.
Implements supervised learning with labeled examples from user verification.

Training Strategy:
    1. Load feedback data (templates + labels)
    2. Split into train/validation sets (80/20)
    3. Train model on verified data
    4. Evaluate on validation set
    5. Save model to global repository
"""

import logging
import pickle
from pathlib import Path
from typing import Dict, Any, List
import numpy as np

logger = logging.getLogger(__name__)


def retrain_with_feedback(
    model_type: str,
    domain: str,
    training_data: List[Dict[str, Any]],
    output_dir: Path,
) -> Dict[str, Any]:
    """
    Retrain a model using user feedback data.
    
    Args:
        model_type: 'gru' or 'autoencoder'
        domain: Domain name (e.g., 'wireless')
        training_data: List of {template, label, confidence} dicts
        output_dir: Directory to save trained model
    
    Returns:
        {
            'model_path': Path to saved model,
            'vocabulary_size': int,
            'accuracy_metrics': {precision, recall, f1},
            'version': int
        }
    """
    if model_type == "gru":
        return _retrain_gru(domain, training_data, output_dir)
    elif model_type == "autoencoder":
        return _retrain_autoencoder(domain, training_data, output_dir)
    else:
        raise ValueError(f"Unsupported model type: {model_type}")


def _retrain_gru(
    domain: str,
    training_data: List[Dict[str, Any]],
    output_dir: Path,
) -> Dict[str, Any]:
    """Retrain GRU model with feedback data."""
    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset
        from sklearn.preprocessing import LabelEncoder
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import precision_recall_fscore_support
        from logai.ml.log_anomaly import _GRULogModel
    except ImportError as e:
        raise RuntimeError(f"Required dependencies not available: {e}")
    
    logger.info(f"[Retrain] Starting GRU retraining for domain '{domain}' with {len(training_data)} samples")
    
    # Extract templates and labels
    templates = [item["template"] for item in training_data]
    labels = np.array([item["label"] for item in training_data])
    
    # Encode templates
    encoder = LabelEncoder()
    encoded_templates = encoder.fit_transform(templates)
    num_classes = len(encoder.classes_)
    
    # Build sequences (sliding window)
    window_size = 10
    X, y = [], []
    for i in range(len(encoded_templates) - window_size):
        X.append(encoded_templates[i:i + window_size])
        y.append(encoded_templates[i + window_size])
    
    X = np.array(X)
    y = np.array(y)
    
    if len(X) < 50:
        raise ValueError("Insufficient sequences for training (need at least 50)")
    
    # Train/val split
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=42
    )
    
    # Convert to tensors
    X_train_t = torch.LongTensor(X_train)
    y_train_t = torch.LongTensor(y_train)
    X_val_t = torch.LongTensor(X_val)
    y_val_t = torch.LongTensor(y_val)
    
    train_dataset = TensorDataset(X_train_t, y_train_t)
    train_loader = DataLoader(train_dataset, batch_size=256, shuffle=True)
    
    # Build model
    hidden_size = 64
    num_layers = 2
    dropout = 0.2
    
    model = _GRULogModel(num_classes, hidden_size, num_layers, dropout)
    device = torch.device("cpu")
    model = model.to(device)
    
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    criterion = nn.CrossEntropyLoss()
    
    # Train
    epochs = 15
    logger.info(f"[Retrain] Training GRU model for {epochs} epochs...")
    
    model.train()
    for epoch in range(epochs):
        total_loss = 0.0
        for batch_x, batch_y in train_loader:
            batch_x, batch_y = batch_x.to(device), batch_y.to(device)
            optimizer.zero_grad()
            output = model(batch_x, num_classes)
            loss = criterion(output, batch_y)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
        
        if (epoch + 1) % 5 == 0:
            logger.info(f"[Retrain] Epoch {epoch+1}/{epochs}, Loss: {total_loss/len(train_loader):.4f}")
    
    # Evaluate
    model.eval()
    with torch.no_grad():
        val_output = model(X_val_t.to(device), num_classes)
        val_preds = torch.argmax(val_output, dim=1).cpu().numpy()
        val_actual = y_val_t.numpy()
    
    precision, recall, f1, _ = precision_recall_fscore_support(
        val_actual, val_preds, average='weighted', zero_division=0
    )
    
    accuracy_metrics = {
        "precision": float(precision),
        "recall": float(recall),
        "f1_score": float(f1),
        "val_samples": len(X_val),
    }
    
    logger.info(f"[Retrain] Validation metrics: P={precision:.3f}, R={recall:.3f}, F1={f1:.3f}")
    
    # Save model
    domain_dir = output_dir / domain / "gru"
    domain_dir.mkdir(parents=True, exist_ok=True)
    
    model_path = domain_dir / "model_retrained.pt"
    vocab_path = domain_dir / "vocabulary.pkl"
    
    torch.save(model.state_dict(), model_path)
    with open(vocab_path, "wb") as f:
        pickle.dump({
            "encoder": encoder,
            "num_classes": num_classes,
        }, f)
    
    logger.info(f"[Retrain] Saved GRU model to {model_path}")
    
    return {
        "model_path": str(model_path),
        "vocabulary_size": num_classes,
        "accuracy_metrics": accuracy_metrics,
        "version": 1,
    }


def _retrain_autoencoder(
    domain: str,
    training_data: List[Dict[str, Any]],
    output_dir: Path,
) -> Dict[str, Any]:
    """Retrain Autoencoder model with feedback data."""
    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.model_selection import train_test_split
        from logai.ml.log_anomaly import _AutoencoderModel
    except ImportError as e:
        raise RuntimeError(f"Required dependencies not available: {e}")
    
    logger.info(f"[Retrain] Starting Autoencoder retraining for domain '{domain}' with {len(training_data)} samples")
    
    # Extract templates
    templates = [item["template"] for item in training_data]
    labels = np.array([item["label"] for item in training_data])
    
    # Create TF-IDF features
    vectorizer = TfidfVectorizer(
        max_features=1000,
        token_pattern=r"(?u)\S+",
    )
    X = vectorizer.fit_transform(templates).toarray()
    
    # Train/val split
    X_train, X_val, y_train, y_val = train_test_split(
        X, labels, test_size=0.2, random_state=42
    )
    
    # Only use "normal" samples (true positives) for training
    X_normal = X_train[y_train == 1]
    
    if len(X_normal) < 20:
        raise ValueError("Insufficient normal samples for autoencoder training (need at least 20)")
    
    # Convert to tensors
    X_normal_t = torch.FloatTensor(X_normal)
    X_val_t = torch.FloatTensor(X_val)
    
    train_dataset = TensorDataset(X_normal_t, X_normal_t)
    train_loader = DataLoader(train_dataset, batch_size=64, shuffle=True)
    
    # Build model
    input_dim = X.shape[1]
    encoding_dim = 32
    dropout = 0.2
    
    model = _AutoencoderModel(input_dim, encoding_dim, dropout)
    device = torch.device("cpu")
    model = model.to(device)
    
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    criterion = nn.MSELoss()
    
    # Train
    epochs = 20
    logger.info(f"[Retrain] Training Autoencoder for {epochs} epochs...")
    
    model.train()
    for epoch in range(epochs):
        total_loss = 0.0
        for batch_x, _ in train_loader:
            batch_x = batch_x.to(device)
            optimizer.zero_grad()
            reconstructed = model(batch_x)
            loss = criterion(reconstructed, batch_x)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
        
        if (epoch + 1) % 5 == 0:
            logger.info(f"[Retrain] Epoch {epoch+1}/{epochs}, Loss: {total_loss/len(train_loader):.4f}")
    
    # Compute threshold from normal samples
    model.eval()
    with torch.no_grad():
        normal_reconstructed = model(X_normal_t.to(device))
        normal_errors = torch.mean((X_normal_t.to(device) - normal_reconstructed) ** 2, dim=1).cpu().numpy()
    
    threshold = np.percentile(normal_errors, 95)
    
    # Evaluate on validation set
    with torch.no_grad():
        val_reconstructed = model(X_val_t.to(device))
        val_errors = torch.mean((X_val_t.to(device) - val_reconstructed) ** 2, dim=1).cpu().numpy()
    
    # Predictions: anomaly if reconstruction error > threshold
    val_preds = (val_errors > threshold).astype(int)
    val_actual = (y_val == 0).astype(int)  # Invert: 0 = normal, 1 = anomaly
    
    from sklearn.metrics import precision_recall_fscore_support
    precision, recall, f1, _ = precision_recall_fscore_support(
        val_actual, val_preds, average='binary', zero_division=0
    )
    
    accuracy_metrics = {
        "precision": float(precision),
        "recall": float(recall),
        "f1_score": float(f1),
        "threshold": float(threshold),
        "val_samples": len(X_val),
    }
    
    logger.info(f"[Retrain] Validation metrics: P={precision:.3f}, R={recall:.3f}, F1={f1:.3f}, threshold={threshold:.4f}")
    
    # Save model
    domain_dir = output_dir / domain / "autoencoder"
    domain_dir.mkdir(parents=True, exist_ok=True)
    
    model_path = domain_dir / "model_retrained.pt"
    vectorizer_path = domain_dir / "vectorizer.pkl"
    meta_path = domain_dir / "metadata.pkl"
    
    torch.save(model.state_dict(), model_path)
    with open(vectorizer_path, "wb") as f:
        pickle.dump(vectorizer, f)
    with open(meta_path, "wb") as f:
        pickle.dump({
            "threshold": threshold,
            "input_dim": input_dim,
        }, f)
    
    logger.info(f"[Retrain] Saved Autoencoder model to {model_path}")
    
    return {
        "model_path": str(model_path),
        "vocabulary_size": len(vectorizer.vocabulary_),
        "accuracy_metrics": accuracy_metrics,
        "version": 1,
    }
