from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams

class QdrantManager:
    def __init__(self, host="localhost", port=41033, embedding_dim=768):
        self.client = QdrantClient(url=f"http://{host}:{port}")
        self.embedding_dim = embedding_dim
        # Ensure global collection exists
        self._ensure_collection("global_templates")

    def _ensure_collection(self, name):
        if not self.client.has_collection(name=name):
            self.client.recreate_collection(
                collection_name=name,
                vectors=VectorParams(size=self.embedding_dim, distance="Cosine")
            )

    def ensure_project_collection(self, project_id):
        coll_name = f"project_{project_id}_templates"
        self._ensure_collection(coll_name)
        return coll_name

    def add_templates(self, project_id, vectors, payloads):
        """
        Add templates to both project and global collections
        vectors: list of np.ndarray or list[float]
        payloads: list of dicts (e.g. {'template':..., 'filename':..., 'frequency':...})
        """
        project_coll = self.ensure_project_collection(project_id)
        # Add to project collection
        self.client.upsert(
            collection_name=project_coll,
            points=[{"id": i, "vector": v.tolist(), "payload": p} for i, (v, p) in enumerate(zip(vectors, payloads))]
        )
        # Add to global collection
        self.client.upsert(
            collection_name="global_templates",
            points=[{"id": f"{project_id}_{i}", "vector": v.tolist(), "payload": p} for i, (v, p) in enumerate(zip(vectors, payloads))]
        )

    def search_project(self, project_id, query_vector, top_k=5):
        coll_name = f"project_{project_id}_templates"
        return self.client.search(collection_name=coll_name, query_vector=query_vector, limit=top_k)

    def search_global(self, query_vector, top_k=5):
        return self.client.search(collection_name="global_templates", query_vector=query_vector, limit=top_k)
