import os
import sys
import modal

app = modal.App("anime-recommender-api")

# Define container image for deployment
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("build-essential", "libpq-dev", "libgomp1")
    .add_local_file("requirements.txt", "/requirements.txt", copy=True)
    .run_commands(
        "pip install -r /requirements.txt --extra-index-url https://download.pytorch.org/whl/cu118"
    )
    .add_local_dir(
        "./backend",
        remote_path="/root/backend",
        ignore=[
            "models",
            "models/**",
            "**/__pycache__/**",
            "__pycache__",
            "data_pipeline/artefacts/**",
        ],
    )
)

volume = modal.Volume.from_name("anime-models-vol", create_if_missing=True)
GPU_KEEP_WARM = int(os.getenv("MODAL_GPU_KEEP_WARM", "1"))

# -----------------------------------------------------------------------------
# INFERENCE TIER: GPU MODEL WORKER ACTOR
# -----------------------------------------------------------------------------
@app.cls(
    image=image,
    gpu="T4",
    timeout=300,
    min_containers=GPU_KEEP_WARM,
    memory=8192,
    cpu=2.0,
    volumes={"/root/backend/models": volume},
)
class ModelWorker:
    @modal.enter()
    def initialize_runtime(self):
        sys.path.append("/root")
        import logging
        logger = logging.getLogger("ModelWorker")
        logger.info("Initializing neural models on GPU VRAM...")

        from backend.rag_pipeline.helper.service_embedding import Embedder
        from backend.rag_pipeline.helper.ranking import Ranker

        self.embedder = Embedder()
        self.ranker = Ranker()
        logger.info("ModelWorker ready for inference.")

    @modal.method()
    def embed_queries(self, queries: list[str]) -> list[tuple[list[float], list[float]]]:
        return self.embedder.execute(queries=queries)

    @modal.method()
    def rerank_candidates(
        self,
        query: str,
        candidates: list,
        top_k: int,
        seen_ids: list[int] | None = None,
        include_metadata: bool = True,
    ) -> list[dict]:
        seen_set = set(seen_ids) if seen_ids else None
        return self.ranker.execute(
            user_query=query,
            all_results=candidates,
            top_k=top_k,
            seen_ids=seen_set,
            include_metadata=include_metadata,
        )


# -----------------------------------------------------------------------------
# GATEWAY TIER: CPU FASTAPI ASGI SERVER
# -----------------------------------------------------------------------------
@app.function(
    image=image,
    cpu=1.0,
    memory=1024,
    timeout=120,
    secrets=[
        modal.Secret.from_name("anime-secret"),
        modal.Secret.from_name("openai-secret"),
    ],
    env={
        "INFERENCE_MODE": "modal",
        "PYTHONPATH": "/root",
    },
)
@modal.asgi_app()
def fastapi_app():
    sys.path.append("/root")
    from backend.main import app as web_app
    return web_app