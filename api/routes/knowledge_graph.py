"""
Knowledge Graph API Routes
===========================

CRUD endpoints for managing knowledge graphs, nodes, and edges.
Supports import/export of graph templates for sharing.
"""

import json
import logging
import uuid
from pathlib import Path

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from api.app import dbm
from api.auth import get_user_id

logger = logging.getLogger(__name__)

knowledge_graph_bp = Blueprint("knowledge_graph", __name__)

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "configs" / "knowledge_graph_templates"


def _graph_to_dict(graph, include_children=False):
    d = {
        "id": graph.id,
        "name": graph.name,
        "description": graph.description,
        "is_template": graph.is_template,
        "created_by": graph.created_by,
        "created_at": graph.created_at.isoformat() if graph.created_at else None,
        "updated_at": graph.updated_at.isoformat() if graph.updated_at else None,
    }
    if include_children:
        d["nodes"] = [_node_to_dict(n) for n in graph.nodes]
        d["edges"] = [_edge_to_dict(e) for e in graph.edges]
    return d


def _node_to_dict(node):
    return {
        "id": node.id,
        "graph_id": node.graph_id,
        "node_type": node.node_type,
        "name": node.name,
        "label": node.label,
        "domain": node.domain,
        "detection_config": json.loads(node.detection_config) if node.detection_config else None,
        "description": node.description,
        "position_x": node.position_x,
        "position_y": node.position_y,
    }


def _edge_to_dict(edge):
    return {
        "id": edge.id,
        "graph_id": edge.graph_id,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "relationship_type": edge.relationship_type,
        "conditions": json.loads(edge.conditions) if edge.conditions else None,
        "label": edge.label,
        "description": edge.description,
    }


# ---------------------------------------------------------------------------
# Graph CRUD
# ---------------------------------------------------------------------------

@knowledge_graph_bp.route("/", methods=["GET"])
@jwt_required()
def list_graphs():
    KG = dbm.KnowledgeGraph
    q = dbm.db.session.query(KG)

    is_template = request.args.get("is_template")
    if is_template is not None:
        q = q.filter(KG.is_template == (is_template.lower() == "true"))

    graphs = q.order_by(KG.updated_at.desc()).all()
    return jsonify([_graph_to_dict(g) for g in graphs])


@knowledge_graph_bp.route("/", methods=["POST"])
@jwt_required()
def create_graph():
    user_id = get_user_id()
    data = request.get_json(silent=True) or {}

    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400

    graph = dbm.KnowledgeGraph(
        id=str(uuid.uuid4()),
        name=name,
        description=data.get("description", ""),
        is_template=data.get("is_template", False),
        created_by=user_id,
    )
    dbm.db.session.add(graph)
    dbm.db.session.commit()
    return jsonify(_graph_to_dict(graph)), 201


@knowledge_graph_bp.route("/architecture/rdkb", methods=["GET"])
@jwt_required()
def get_rdkb_architecture_graph():
    """
    Static RDK-B module / component graph from configs/rdkb_module_graph.yaml
    for the Knowledge Graph page Architecture tab (read-only).
    """
    from logai.rdkb_knowledge import load_module_graph

    try:
        g = load_module_graph()
    except Exception as e:
        logger.exception("Failed to load RDK-B module graph: %s", e)
        return jsonify(
            {
                "version": 0,
                "architecture_references": [],
                "nodes": [],
                "edges": [],
                "warning": "Failed to load architecture graph.",
            }
        ), 200

    raw_nodes = g.get("nodes") or []
    raw_edges = g.get("edges") or []

    nodes_out = []
    for n in raw_nodes:
        mid = n.get("module_id")
        if not mid:
            continue
        nodes_out.append(
            {
                "id": mid,
                "label": n.get("display_name") or mid,
                "domains": n.get("primary_domains") or [],
                "description": (n.get("description") or "")[:2000],
            }
        )

    edges_out = []
    for i, e in enumerate(raw_edges):
        src = e.get("source")
        tgt = e.get("target")
        if not src or not tgt:
            continue
        edges_out.append(
            {
                "id": f"e_{i}_{src}_{tgt}",
                "source": src,
                "target": tgt,
                "relationship": e.get("relationship") or "",
                "notes": (e.get("notes") or "")[:500] if e.get("notes") else None,
                "confidence": e.get("confidence"),
            }
        )

    warning = None
    if not raw_nodes and not raw_edges:
        warning = "No nodes or edges in rdkb_module_graph.yaml (missing or empty file)."

    return jsonify(
        {
            "version": g.get("version", 0),
            "architecture_references": g.get("architecture_references") or [],
            "nodes": nodes_out,
            "edges": edges_out,
            "node_count": len(nodes_out),
            "edge_count": len(edges_out),
            **({"warning": warning} if warning else {}),
        }
    )


@knowledge_graph_bp.route("/<graph_id>", methods=["GET"])
@jwt_required()
def get_graph(graph_id):
    graph = dbm.db.session.get(dbm.KnowledgeGraph, graph_id)
    if not graph:
        return jsonify({"error": "Graph not found"}), 404
    return jsonify(_graph_to_dict(graph, include_children=True))


@knowledge_graph_bp.route("/<graph_id>", methods=["PUT"])
@jwt_required()
def update_graph(graph_id):
    graph = dbm.db.session.get(dbm.KnowledgeGraph, graph_id)
    if not graph:
        return jsonify({"error": "Graph not found"}), 404

    data = request.get_json(silent=True) or {}
    if "name" in data:
        graph.name = data["name"]
    if "description" in data:
        graph.description = data["description"]
    if "is_template" in data:
        graph.is_template = data["is_template"]

    dbm.db.session.commit()
    return jsonify(_graph_to_dict(graph))


@knowledge_graph_bp.route("/<graph_id>", methods=["DELETE"])
@jwt_required()
def delete_graph(graph_id):
    graph = dbm.db.session.get(dbm.KnowledgeGraph, graph_id)
    if not graph:
        return jsonify({"error": "Graph not found"}), 404
    dbm.db.session.delete(graph)
    dbm.db.session.commit()
    return jsonify({"message": "Graph deleted"})


# ---------------------------------------------------------------------------
# Node CRUD
# ---------------------------------------------------------------------------

VALID_NODE_TYPES = {"EVENT", "CONDITION", "ISSUE", "ROOT_CAUSE", "SUBGRAPH"}


@knowledge_graph_bp.route("/<graph_id>/nodes", methods=["POST"])
@jwt_required()
def create_node(graph_id):
    graph = dbm.db.session.get(dbm.KnowledgeGraph, graph_id)
    if not graph:
        return jsonify({"error": "Graph not found"}), 404

    data = request.get_json(silent=True) or {}
    node_type = data.get("node_type", "").upper()
    if node_type not in VALID_NODE_TYPES:
        return jsonify({"error": f"node_type must be one of {sorted(VALID_NODE_TYPES)}"}), 400

    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400

    detection_config = data.get("detection_config")
    node = dbm.KnowledgeNode(
        id=data.get("id") or str(uuid.uuid4()),
        graph_id=graph_id,
        node_type=node_type,
        name=name,
        label=data.get("label", name),
        domain=data.get("domain"),
        detection_config=json.dumps(detection_config) if detection_config else None,
        description=data.get("description"),
        position_x=data.get("position_x", 0),
        position_y=data.get("position_y", 0),
    )
    dbm.db.session.add(node)
    dbm.db.session.commit()
    return jsonify(_node_to_dict(node)), 201


@knowledge_graph_bp.route("/<graph_id>/nodes/<node_id>", methods=["PUT"])
@jwt_required()
def update_node(graph_id, node_id):
    node = dbm.db.session.get(dbm.KnowledgeNode, node_id)
    if not node or node.graph_id != graph_id:
        return jsonify({"error": "Node not found"}), 404

    data = request.get_json(silent=True) or {}
    for field in ("name", "label", "domain", "description"):
        if field in data:
            setattr(node, field, data[field])
    if "node_type" in data:
        nt = data["node_type"].upper()
        if nt in VALID_NODE_TYPES:
            node.node_type = nt
    if "detection_config" in data:
        dc = data["detection_config"]
        node.detection_config = json.dumps(dc) if dc else None
    if "position_x" in data:
        node.position_x = data["position_x"]
    if "position_y" in data:
        node.position_y = data["position_y"]

    dbm.db.session.commit()
    return jsonify(_node_to_dict(node))


@knowledge_graph_bp.route("/<graph_id>/nodes/<node_id>", methods=["DELETE"])
@jwt_required()
def delete_node(graph_id, node_id):
    node = dbm.db.session.get(dbm.KnowledgeNode, node_id)
    if not node or node.graph_id != graph_id:
        return jsonify({"error": "Node not found"}), 404

    KE = dbm.KnowledgeEdge
    dbm.db.session.query(KE).filter(
        (KE.source_node_id == node_id) | (KE.target_node_id == node_id)
    ).delete(synchronize_session="fetch")

    dbm.db.session.delete(node)
    dbm.db.session.commit()
    return jsonify({"message": "Node deleted"})


# ---------------------------------------------------------------------------
# Edge CRUD
# ---------------------------------------------------------------------------

VALID_RELATIONSHIP_TYPES = {"COULD_CAUSE", "LEADS_TO", "INDICATES", "CORRELATES_WITH"}


@knowledge_graph_bp.route("/<graph_id>/edges", methods=["POST"])
@jwt_required()
def create_edge(graph_id):
    graph = dbm.db.session.get(dbm.KnowledgeGraph, graph_id)
    if not graph:
        return jsonify({"error": "Graph not found"}), 404

    data = request.get_json(silent=True) or {}
    rel_type = data.get("relationship_type", "").upper()
    if rel_type not in VALID_RELATIONSHIP_TYPES:
        return jsonify({"error": f"relationship_type must be one of {sorted(VALID_RELATIONSHIP_TYPES)}"}), 400

    source_id = data.get("source_node_id")
    target_id = data.get("target_node_id")
    if not source_id or not target_id:
        return jsonify({"error": "source_node_id and target_node_id are required"}), 400

    conditions = data.get("conditions")
    edge = dbm.KnowledgeEdge(
        id=data.get("id") or str(uuid.uuid4()),
        graph_id=graph_id,
        source_node_id=source_id,
        target_node_id=target_id,
        relationship_type=rel_type,
        conditions=json.dumps(conditions) if conditions else None,
        label=data.get("label"),
        description=data.get("description"),
    )
    dbm.db.session.add(edge)
    dbm.db.session.commit()
    return jsonify(_edge_to_dict(edge)), 201


@knowledge_graph_bp.route("/<graph_id>/edges/<edge_id>", methods=["PUT"])
@jwt_required()
def update_edge(graph_id, edge_id):
    edge = dbm.db.session.get(dbm.KnowledgeEdge, edge_id)
    if not edge or edge.graph_id != graph_id:
        return jsonify({"error": "Edge not found"}), 404

    data = request.get_json(silent=True) or {}
    if "relationship_type" in data:
        rt = data["relationship_type"].upper()
        if rt in VALID_RELATIONSHIP_TYPES:
            edge.relationship_type = rt
    if "conditions" in data:
        c = data["conditions"]
        edge.conditions = json.dumps(c) if c else None
    for field in ("label", "description", "source_node_id", "target_node_id"):
        if field in data:
            setattr(edge, field, data[field])

    dbm.db.session.commit()
    return jsonify(_edge_to_dict(edge))


@knowledge_graph_bp.route("/<graph_id>/edges/<edge_id>", methods=["DELETE"])
@jwt_required()
def delete_edge(graph_id, edge_id):
    edge = dbm.db.session.get(dbm.KnowledgeEdge, edge_id)
    if not edge or edge.graph_id != graph_id:
        return jsonify({"error": "Edge not found"}), 404
    dbm.db.session.delete(edge)
    dbm.db.session.commit()
    return jsonify({"message": "Edge deleted"})


# ---------------------------------------------------------------------------
# Import / Export
# ---------------------------------------------------------------------------

@knowledge_graph_bp.route("/import", methods=["POST"])
@jwt_required()
def import_graph():
    """Import a graph from JSON (template file or uploaded payload)."""
    user_id = get_user_id()
    data = request.get_json(silent=True) or {}

    template_name = data.get("template")
    if template_name:
        template_path = TEMPLATES_DIR / template_name
        if not template_path.exists():
            return jsonify({"error": f"Template '{template_name}' not found"}), 404
        with open(template_path) as f:
            tpl = json.load(f)
    else:
        tpl = data

    graph_id = str(uuid.uuid4())
    graph = dbm.KnowledgeGraph(
        id=graph_id,
        name=tpl.get("name", "Imported Graph"),
        description=tpl.get("description", ""),
        is_template=tpl.get("is_template", False),
        created_by=user_id,
    )
    dbm.db.session.add(graph)

    node_id_map = {}
    for n in tpl.get("nodes", []):
        new_id = str(uuid.uuid4())
        node_id_map[n["id"]] = new_id
        detection_config = n.get("detection_config")
        node = dbm.KnowledgeNode(
            id=new_id,
            graph_id=graph_id,
            node_type=n.get("node_type", "EVENT"),
            name=n.get("name", ""),
            label=n.get("label", n.get("name", "")),
            domain=n.get("domain"),
            detection_config=json.dumps(detection_config) if detection_config else None,
            description=n.get("description"),
            position_x=n.get("position_x", 0),
            position_y=n.get("position_y", 0),
        )
        dbm.db.session.add(node)

    for e in tpl.get("edges", []):
        src = node_id_map.get(e["source_node_id"], e["source_node_id"])
        tgt = node_id_map.get(e["target_node_id"], e["target_node_id"])
        conditions = e.get("conditions")
        edge = dbm.KnowledgeEdge(
            id=str(uuid.uuid4()),
            graph_id=graph_id,
            source_node_id=src,
            target_node_id=tgt,
            relationship_type=e.get("relationship_type", "COULD_CAUSE"),
            conditions=json.dumps(conditions) if conditions else None,
            label=e.get("label"),
            description=e.get("description"),
        )
        dbm.db.session.add(edge)

    dbm.db.session.commit()

    graph = dbm.db.session.get(dbm.KnowledgeGraph, graph_id)
    return jsonify(_graph_to_dict(graph, include_children=True)), 201


@knowledge_graph_bp.route("/<graph_id>/export", methods=["GET"])
@jwt_required()
def export_graph(graph_id):
    graph = dbm.db.session.get(dbm.KnowledgeGraph, graph_id)
    if not graph:
        return jsonify({"error": "Graph not found"}), 404

    nodes = []
    node_ids = {}
    for i, n in enumerate(graph.nodes):
        stable_id = f"node_{i}"
        node_ids[n.id] = stable_id
        nodes.append({
            "id": stable_id,
            "node_type": n.node_type,
            "name": n.name,
            "label": n.label,
            "domain": n.domain,
            "detection_config": json.loads(n.detection_config) if n.detection_config else None,
            "description": n.description,
            "position_x": n.position_x,
            "position_y": n.position_y,
        })

    edges = []
    for i, e in enumerate(graph.edges):
        edges.append({
            "id": f"edge_{i}",
            "source_node_id": node_ids.get(e.source_node_id, e.source_node_id),
            "target_node_id": node_ids.get(e.target_node_id, e.target_node_id),
            "relationship_type": e.relationship_type,
            "conditions": json.loads(e.conditions) if e.conditions else None,
            "label": e.label,
            "description": e.description,
        })

    return jsonify({
        "name": graph.name,
        "description": graph.description,
        "is_template": graph.is_template,
        "nodes": nodes,
        "edges": edges,
    })


@knowledge_graph_bp.route("/templates", methods=["GET"])
@jwt_required()
def list_templates():
    """List available built-in template files."""
    templates = []
    if TEMPLATES_DIR.exists():
        for p in sorted(TEMPLATES_DIR.glob("*.json")):
            try:
                with open(p) as f:
                    tpl = json.load(f)
                templates.append({
                    "filename": p.name,
                    "name": tpl.get("name", p.stem),
                    "description": tpl.get("description", ""),
                    "node_count": len(tpl.get("nodes", [])),
                    "edge_count": len(tpl.get("edges", [])),
                })
            except Exception:
                pass
    return jsonify(templates)
