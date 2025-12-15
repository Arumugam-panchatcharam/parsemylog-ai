import os
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct
from filelock import FileLock


class QdrantVectorDB:
    """
    Multi-user, multi-project safe local Qdrant handler.
    Creates local Qdrant DB under: base_dir/<user>/<project>/qdrant/
    """

    def __init__(self, project_dir: str):
        self.project_dir = os.path.join(project_dir, "qdrant")
        os.makedirs(self.project_dir, exist_ok=True)

        # Concurrency lock → avoids DB corruption when multiple users write simultaneously
        self.lock = FileLock(os.path.join(self.project_dir, ".qdrant.lock"))

        # Local-file Qdrant client
        self.client = QdrantClient(path=self.project_dir)

    def create_collection(self, name: str, vector_size: int = 768):
        with self.lock:
            self.client.recreate_collection(
                collection_name=name,
                vectors_config=VectorParams(
                    size=vector_size,
                    distance=Distance.COSINE
                )
            )

    def insert(self, collection: str, embeddings: list, payloads: list):
        with self.lock:
            points = [
                PointStruct(id=i, vector=embeddings[i], payload=payloads[i])
                for i in range(len(embeddings))
            ]
            self.client.upsert(collection, points)

    def search(self, collection: str, embedding: list, top_k: int = 5):
        return self.client.query_points(
            collection_name=collection,
            query=embedding,
            limit=top_k
        )
