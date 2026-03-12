"""
ML Feedback API Routes
=======================

REST endpoints for:
- Submitting anomaly feedback (user verification)
- Retrieving feedback statistics
- Admin model retraining with feedback data
- Global model management and synchronization
"""

import logging
import os
import json
from pathlib import Path
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from api.app import dbm
from api.auth import get_user_id, admin_required
from logai.ml.feedback import FeedbackManager, GlobalModelManager, create_feedback_tables, AnomalyFeedback, GlobalTrainedModel
from logai.utils.constants import UPLOAD_DIRECTORY, BASE_DIR

logger = logging.getLogger(__name__)

ml_feedback_bp = Blueprint("ml_feedback", __name__)

# Initialize database tables on module import
try:
    create_feedback_tables()
    logger.info("[Feedback] Database tables created/verified")
except Exception as e:
    logger.warning(f"[Feedback] Could not create tables: {e}")


def _verify_project(project_id, user_id):
    project = dbm.get_project_by_id(project_id)
    if not project:
        return None, (jsonify({"error": "Project not found"}), 404)
    if project.user_id != user_id:
        return None, (jsonify({"error": "Access denied"}), 403)
    return project, None


# ---------------------------------------------------------------------------
# Feedback Submission
# ---------------------------------------------------------------------------

@ml_feedback_bp.route(
    "/<project_id>/ml/feedback", methods=["POST"]
)
@jwt_required()
def submit_feedback(project_id):
    """
    Submit user feedback for a detected anomaly.
    
    Request body:
        {
            "cpe_id": "A0B53CA6C0A9",
            "domain": "wireless",
            "template": "<error template>",
            "anomaly_type": "gru",
            "is_true_positive": true,
            "confidence": 0.95,
            "feedback_notes": "optional notes"
        }
    
    Returns:
        {"feedback_id": 123, "message": "Feedback recorded"}
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err
    
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400
    
    required_fields = ["cpe_id", "domain", "template", "anomaly_type", "is_true_positive"]
    if not all(field in data for field in required_fields):
        return jsonify({"error": f"Missing required fields: {required_fields}"}), 400
    
    try:
        feedback_mgr = FeedbackManager()
        feedback_id = feedback_mgr.add_feedback(
            user_id=user_id,
            project_id=project_id,
            cpe_id=data["cpe_id"],
            domain=data["domain"],
            template=data["template"],
            anomaly_type=data["anomaly_type"],
            is_true_positive=data["is_true_positive"],
            confidence=data.get("confidence", 0.0),
            feedback_notes=data.get("feedback_notes"),
        )
        
        return jsonify({
            "feedback_id": feedback_id,
            "message": "Feedback recorded successfully"
        }), 201
    
    except Exception as e:
        logger.error(f"[Feedback] Failed to submit: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@ml_feedback_bp.route(
    "/<project_id>/ml/feedback", methods=["GET"]
)
@jwt_required()
def get_project_feedback(project_id):
    """
    Get all feedback for a project.
    
    Query params:
        domain: Filter by domain (optional)
    
    Returns:
        {
            "feedback": [
                {
                    "id": 1,
                    "cpe_id": "...",
                    "domain": "wireless",
                    "template": "...",
                    "anomaly_type": "gru",
                    "is_true_positive": true,
                    "confidence": 0.95,
                    "feedback_notes": "...",
                    "created_at": "2026-03-07T10:00:00"
                }
            ],
            "count": 42
        }
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err
    
    domain = request.args.get("domain")
    
    try:
        feedback_mgr = FeedbackManager()
        feedback_list = feedback_mgr.get_feedback_by_project(project_id, domain)
        
        return jsonify({
            "feedback": [
                {
                    "id": f.id,
                    "user_id": f.user_id,
                    "cpe_id": f.cpe_id,
                    "domain": f.domain,
                    "template": f.template,
                    "anomaly_type": f.anomaly_type,
                    "is_true_positive": f.is_true_positive,
                    "confidence": f.confidence,
                    "feedback_notes": f.feedback_notes,
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                }
                for f in feedback_list
            ],
            "count": len(feedback_list)
        }), 200
    
    except Exception as e:
        logger.error(f"[Feedback] Failed to retrieve: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@ml_feedback_bp.route(
    "/ml/feedback/stats", methods=["GET"]
)
@jwt_required()
@admin_required
def get_feedback_stats():
    """
    Get feedback statistics across all projects (admin only).
    
    Query params:
        domain: Filter by domain (optional)
    
    Returns:
        {
            "stats": {
                "wireless": {
                    "gru": {
                        "total": 100,
                        "true_positives": 85,
                        "false_positives": 15,
                        "precision": 0.85,
                        "avg_confidence": 0.92
                    },
                    ...
                },
                ...
            }
        }
    """
    domain = request.args.get("domain")
    
    try:
        feedback_mgr = FeedbackManager()
        stats = feedback_mgr.get_feedback_stats(domain)
        
        return jsonify({"stats": stats}), 200
    
    except Exception as e:
        logger.error(f"[Feedback] Failed to get stats: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Admin Model Retraining
# ---------------------------------------------------------------------------

@ml_feedback_bp.route(
    "/ml/retrain", methods=["POST"]
)
@jwt_required()
@admin_required
def retrain_global_model():
    """
    Trigger model retraining with accumulated feedback data (admin only).
    
    Request body:
        {
            "model_type": "gru",
            "domain": "wireless",
            "min_samples": 100
        }
    
    Returns:
        {
            "model_id": 5,
            "version": 2,
            "training_samples": 1250,
            "accuracy_metrics": {...},
            "message": "Model retrained successfully"
        }
    """
    user_id = get_user_id()
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400
    
    model_type = data.get("model_type", "gru")
    domain = data.get("domain")
    min_samples = data.get("min_samples", 100)
    
    if not domain:
        return jsonify({"error": "domain is required"}), 400
    
    if model_type not in ["gru", "autoencoder"]:
        return jsonify({"error": "model_type must be 'gru' or 'autoencoder'"}), 400
    
    try:
        feedback_mgr = FeedbackManager()
        global_model_mgr = GlobalModelManager()
        
        # Get training dataset from feedback
        training_data = feedback_mgr.get_training_dataset(
            domain=domain,
            anomaly_type=model_type,
            min_samples=min_samples,
        )
        
        if not training_data:
            return jsonify({
                "error": f"Insufficient feedback data. Need at least {min_samples} samples."
            }), 400
        
        # Train model with feedback data
        from logai.ml.model_retrainer import retrain_with_feedback
        
        global_models_dir = Path(BASE_DIR) / "global_models"
        global_models_dir.mkdir(exist_ok=True)
        
        result = retrain_with_feedback(
            model_type=model_type,
            domain=domain,
            training_data=training_data,
            output_dir=global_models_dir,
        )
        
        # Save to global model repository
        model_id = global_model_mgr.save_global_model(
            model_type=model_type,
            domain=domain,
            model_path=result["model_path"],
            vocabulary_size=result["vocabulary_size"],
            training_samples=len(training_data),
            accuracy_metrics=result["accuracy_metrics"],
            trained_by_user_id=user_id,
        )
        
        logger.info(f"[Admin] Retrained {model_type} model for domain '{domain}' (model_id={model_id})")
        
        return jsonify({
            "model_id": model_id,
            "version": result["version"],
            "training_samples": len(training_data),
            "accuracy_metrics": result["accuracy_metrics"],
            "message": f"Model retrained successfully with {len(training_data)} samples"
        }), 200
    
    except Exception as e:
        logger.error(f"[Admin] Model retraining failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Global Model Management
# ---------------------------------------------------------------------------

@ml_feedback_bp.route(
    "/ml/global-models", methods=["GET"]
)
@jwt_required()
@admin_required
def list_global_models():
    """
    List all global trained models (admin only).
    
    Query params:
        model_type: Filter by model type (optional)
        domain: Filter by domain (optional)
    
    Returns:
        {
            "models": [
                {
                    "id": 5,
                    "model_type": "gru",
                    "domain": "wireless",
                    "vocabulary_size": 850,
                    "training_samples": 1250,
                    "accuracy_metrics": {...},
                    "trained_by_user_id": 1,
                    "trained_at": "2026-03-07T10:00:00",
                    "is_active": true,
                    "version": 2
                }
            ]
        }
    """
    model_type = request.args.get("model_type")
    domain = request.args.get("domain")
    
    try:
        global_model_mgr = GlobalModelManager()
        models = global_model_mgr.list_all_models(model_type, domain)
        
        return jsonify({
            "models": [
                {
                    "id": m.id,
                    "model_type": m.model_type,
                    "domain": m.domain,
                    "model_path": m.model_path,
                    "vocabulary_size": m.vocabulary_size,
                    "training_samples": m.training_samples,
                    "accuracy_metrics": json.loads(m.accuracy_metrics) if m.accuracy_metrics else None,
                    "trained_by_user_id": m.trained_by_user_id,
                    "trained_at": m.trained_at.isoformat() if m.trained_at else None,
                    "is_active": m.is_active,
                    "version": m.version,
                }
                for m in models
            ]
        }), 200
    
    except Exception as e:
        logger.error(f"[Admin] Failed to list models: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@ml_feedback_bp.route(
    "/ml/global-models/<int:model_id>/activate", methods=["POST"]
)
@jwt_required()
@admin_required
def activate_global_model(model_id):
    """
    Activate a specific global model version (admin only).
    
    Returns:
        {"message": "Model activated successfully"}
    """
    try:
        global_model_mgr = GlobalModelManager()
        success = global_model_mgr.activate_model(model_id)
        
        if not success:
            return jsonify({"error": "Model not found"}), 404
        
        logger.info(f"[Admin] Activated global model {model_id}")
        
        return jsonify({"message": "Model activated successfully"}), 200
    
    except Exception as e:
        logger.error(f"[Admin] Failed to activate model: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@ml_feedback_bp.route(
    "/ml/global-models/active", methods=["GET"]
)
@jwt_required()
def get_active_global_models():
    """
    Get currently active global models for all domains.
    
    Non-admin users can see which models are active but not manage them.
    
    Query params:
        model_type: Filter by model type (optional)
        domain: Filter by domain (optional)
    
    Returns:
        {
            "models": [
                {
                    "model_type": "gru",
                    "domain": "wireless",
                    "version": 2,
                    "training_samples": 1250,
                    "accuracy_metrics": {...},
                    "trained_at": "2026-03-07T10:00:00"
                }
            ]
        }
    """
    model_type = request.args.get("model_type")
    domain = request.args.get("domain")
    
    try:
        global_model_mgr = GlobalModelManager()
        all_models = global_model_mgr.list_all_models(model_type, domain)
        
        # Filter to only active models
        active_models = [m for m in all_models if m.is_active]
        
        return jsonify({
            "models": [
                {
                    "id": m.id,
                    "model_type": m.model_type,
                    "domain": m.domain,
                    "vocabulary_size": m.vocabulary_size,
                    "training_samples": m.training_samples,
                    "accuracy_metrics": json.loads(m.accuracy_metrics) if m.accuracy_metrics else None,
                    "trained_at": m.trained_at.isoformat() if m.trained_at else None,
                    "version": m.version,
                }
                for m in active_models
            ]
        }), 200
    
    except Exception as e:
        logger.error(f"[Feedback] Failed to get active models: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
