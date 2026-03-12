"""
ML Anomaly Feedback System
===========================

Allows users to provide feedback on ML-detected anomalies (true/false positives)
for continuous model improvement. Admin users can trigger retraining with
accumulated feedback data.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
import json
from flask_sqlalchemy import SQLAlchemy

# Import the db instance from user_db_mngr
from api.user_db_mngr import db


# SQLAlchemy Models
class AnomalyFeedback(db.Model):
    """User feedback on a detected anomaly."""
    __tablename__ = "anomaly_feedback"
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    project_id = db.Column(db.String, db.ForeignKey('projects.id'), nullable=False)
    cpe_id = db.Column(db.String, nullable=False)
    domain = db.Column(db.String, nullable=False)
    template = db.Column(db.Text, nullable=False)
    anomaly_type = db.Column(db.String, nullable=False)
    is_true_positive = db.Column(db.Boolean, nullable=False)
    confidence = db.Column(db.Float, default=0.0)
    feedback_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Indexes
    __table_args__ = (
        db.Index('idx_feedback_project_domain', 'project_id', 'domain'),
        db.Index('idx_feedback_user', 'user_id'),
    )


class GlobalTrainedModel(db.Model):
    """Admin-trained global model shared across users."""
    __tablename__ = "global_trained_models"
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    model_type = db.Column(db.String, nullable=False)
    domain = db.Column(db.String, nullable=False)
    model_path = db.Column(db.String, nullable=False)
    vocabulary_size = db.Column(db.Integer, nullable=False)
    training_samples = db.Column(db.Integer, nullable=False)
    accuracy_metrics = db.Column(db.Text)  # JSON string
    trained_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    trained_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    version = db.Column(db.Integer, default=1)
    
    # Indexes
    __table_args__ = (
        db.Index('idx_global_models_active', 'model_type', 'domain', 'is_active'),
    )


def create_feedback_tables():
    """Create feedback and global model tables in the database."""
    db.create_all()


class FeedbackManager:
    """Manages anomaly feedback storage and retrieval."""
    
    def add_feedback(
        self,
        user_id: int,
        project_id: str,
        cpe_id: str,
        domain: str,
        template: str,
        anomaly_type: str,
        is_true_positive: bool,
        confidence: float = 0.0,
        feedback_notes: Optional[str] = None,
    ) -> int:
        """
        Add user feedback for an anomaly.
        
        Returns:
            Feedback ID
        """
        feedback = AnomalyFeedback(
            user_id=user_id,
            project_id=project_id,
            cpe_id=cpe_id,
            domain=domain,
            template=template,
            anomaly_type=anomaly_type,
            is_true_positive=is_true_positive,
            confidence=confidence,
            feedback_notes=feedback_notes,
        )
        
        db.session.add(feedback)
        db.session.commit()
        return feedback.id
    
    def get_feedback_by_project(
        self,
        project_id: str,
        domain: Optional[str] = None,
    ) -> List[AnomalyFeedback]:
        """Get all feedback for a project, optionally filtered by domain."""
        query = AnomalyFeedback.query.filter_by(project_id=project_id)
        
        if domain:
            query = query.filter_by(domain=domain)
        
        return query.order_by(AnomalyFeedback.created_at.desc()).all()
    
    def get_feedback_stats(self, domain: Optional[str] = None) -> Dict[str, Any]:
        """Get feedback statistics across all projects."""
        from sqlalchemy import func, case
        
        query = db.session.query(
            AnomalyFeedback.domain,
            AnomalyFeedback.anomaly_type,
            func.count(AnomalyFeedback.id).label('total'),
            func.sum(case((AnomalyFeedback.is_true_positive == True, 1), else_=0)).label('true_positives'),
            func.sum(case((AnomalyFeedback.is_true_positive == False, 1), else_=0)).label('false_positives'),
            func.avg(AnomalyFeedback.confidence).label('avg_confidence'),
        )
        
        if domain:
            query = query.filter_by(domain=domain)
        
        query = query.group_by(AnomalyFeedback.domain, AnomalyFeedback.anomaly_type)
        
        results = query.all()
        
        stats = {}
        for row in results:
            dom = row.domain
            if dom not in stats:
                stats[dom] = {}
            
            total = row.total or 0
            true_pos = row.true_positives or 0
            
            stats[dom][row.anomaly_type] = {
                "total": total,
                "true_positives": true_pos,
                "false_positives": row.false_positives or 0,
                "precision": true_pos / total if total > 0 else 0.0,
                "avg_confidence": float(row.avg_confidence or 0.0),
            }
        
        return stats
    
    def get_training_dataset(
        self,
        domain: str,
        anomaly_type: str,
        min_samples: int = 100,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get feedback data for model retraining.
        
        Returns:
            List of {template, label} dicts if enough samples, None otherwise
        """
        feedbacks = AnomalyFeedback.query.filter_by(
            domain=domain,
            anomaly_type=anomaly_type
        ).order_by(AnomalyFeedback.created_at.desc()).all()
        
        if len(feedbacks) < min_samples:
            return None
        
        return [
            {
                "template": f.template,
                "label": 1 if f.is_true_positive else 0,
                "confidence": f.confidence,
            }
            for f in feedbacks
        ]


class GlobalModelManager:
    """Manages global trained models shared across users."""
    
    def save_global_model(
        self,
        model_type: str,
        domain: str,
        model_path: str,
        vocabulary_size: int,
        training_samples: int,
        accuracy_metrics: Dict[str, Any],
        trained_by_user_id: int,
    ) -> int:
        """
        Save a globally trained model.
        
        Automatically increments version and deactivates previous versions.
        
        Returns:
            Model ID
        """
        # Get next version number
        max_version = db.session.query(
            func.max(GlobalTrainedModel.version)
        ).filter_by(
            model_type=model_type,
            domain=domain
        ).scalar() or 0
        
        next_version = max_version + 1
        
        # Deactivate previous versions
        GlobalTrainedModel.query.filter_by(
            model_type=model_type,
            domain=domain
        ).update({"is_active": False})
        
        # Insert new model
        model = GlobalTrainedModel(
            model_type=model_type,
            domain=domain,
            model_path=model_path,
            vocabulary_size=vocabulary_size,
            training_samples=training_samples,
            accuracy_metrics=json.dumps(accuracy_metrics),
            trained_by_user_id=trained_by_user_id,
            version=next_version,
        )
        
        db.session.add(model)
        db.session.commit()
        return model.id
    
    def get_active_model(
        self,
        model_type: str,
        domain: str,
    ) -> Optional[GlobalTrainedModel]:
        """Get the currently active global model for a domain."""
        return GlobalTrainedModel.query.filter_by(
            model_type=model_type,
            domain=domain,
            is_active=True
        ).order_by(GlobalTrainedModel.version.desc()).first()
    
    def list_all_models(
        self,
        model_type: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> List[GlobalTrainedModel]:
        """List all global models, optionally filtered."""
        query = GlobalTrainedModel.query
        
        if model_type:
            query = query.filter_by(model_type=model_type)
        
        if domain:
            query = query.filter_by(domain=domain)
        
        return query.order_by(GlobalTrainedModel.trained_at.desc()).all()
    
    def activate_model(self, model_id: int) -> bool:
        """Activate a specific model version and deactivate others."""
        model = GlobalTrainedModel.query.get(model_id)
        if not model:
            return False
        
        # Deactivate all models of same type/domain
        GlobalTrainedModel.query.filter_by(
            model_type=model.model_type,
            domain=model.domain
        ).update({"is_active": False})
        
        # Activate this model
        model.is_active = True
        db.session.commit()
        return True

