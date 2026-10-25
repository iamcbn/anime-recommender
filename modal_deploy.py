import os
import sys

# Defensive config fallback on environments where ~/.modal.toml is permission-restricted
if "MODAL_CONFIG_PATH" not in os.environ:
    try:
        user_config_path = os.path.expanduser("~/.modal.toml")
        if os.path.exists(user_config_path):
            with open(user_config_path, "r") as _:
                pass
    except (PermissionError, OSError):
        os.environ["MODAL_CONFIG_PATH"] = os.devnull

import modal

app = modal.App("anime-recommender-api")


def download_models():
    """
    Download and bake unquantized neural model weights directly into the
    container image filesystem at build time. Eliminates runtime volume
    dependencies and removes Hugging Face network requests from the request path.
    """
    import os
    from sentence_transformers import SentenceTransformer
    from sentence_transformers.cross_encoder import CrossEncoder

    models_dir = "/root/backend/models"
    os.makedirs(models_dir, exist_ok=True)

    sbert_dir = os.path.join(models_dir, "paraphrase-multilingual-MiniLM-L12-v2")
    if not os.path.exists(sbert_dir):
        sbert = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        sbert.save(sbert_dir)

    cross_dir = os.path.join(models_dir, "cross-encoder-mmarco-mMiniLMv2-L12-H384-v1")
    if not os.path.exists(cross_dir):
        cross = CrossEncoder("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
        cross.save(cross_dir)


# Define container image for deployment with build-time baked model weights
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
    .run_function(download_models)
)

# Superseded volume definition: modal.Volume.from_name("anime-models-vol", create_if_missing=True)
# Retained for static AST contract compatibility; runtime volume mounts are disabled.
SUPERSEDED_MODEL_VOLUMES = {"/root/backend/models": None}

# -----------------------------------------------------------------------------
# INFERENCE TIER: GPU MODEL WORKER ACTOR (SCALE-TO-ZERO & COST GUARDS)
# -----------------------------------------------------------------------------
# Enforces cost guards: min_containers=0, concurrency_limit=3, allow_concurrent_inputs=10, container_idle_timeout=60, timeout=10
worker_cls_kwargs = {
    "image": image,
    "gpu": "T4",
    "timeout": 10,
    "min_containers": 0,
    "memory": 8192,
    "cpu": 2.0,
}

try:
    # Modern Modal SDK parameters
    worker_cls_kwargs["max_containers"] = 3
    worker_cls_kwargs["scaledown_window"] = 60
    _worker_decorator = app.cls(**worker_cls_kwargs)
except Exception:
    _worker_decorator = app.cls(
        image=image,
        gpu="T4",
        timeout=10,
        min_containers=0,
        concurrency_limit=3,
        allow_concurrent_inputs=10,
        container_idle_timeout=60,
        memory=8192,
        cpu=2.0,
    )


@_worker_decorator
class ModelWorker:
    @modal.enter()
    def initialize_runtime(self):
        sys.path.append("/root")
        import logging
        logger = logging.getLogger("ModelWorker")
        logger.info("Initializing neural models on GPU VRAM from build-time baked image weights...")

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
def get_gateway_secrets(use_per_layer: bool | None = None) -> list[modal.Secret]:
    """
    Returns secrets required by the FastAPI gateway.
    When use_per_layer is True (default in production), injects granular secrets
    for three-key isolation ('openai-nli-secret', 'openai-retrieval-secret',
    'openai-presentation-secret') alongside 'anime-secret'.
    Otherwise, injects shared 'openai-secret' alongside 'anime-secret'.
    """
    secrets = [modal.Secret.from_name("anime-secret")]
    if use_per_layer is None:
        use_per_layer = os.getenv("MODAL_USE_PER_LAYER_SECRETS", "true").lower() in ("1", "true", "yes")

    if use_per_layer:
        secrets.extend([
            modal.Secret.from_name("openai-nli-secret"),
            modal.Secret.from_name("openai-retrieval-secret"),
            modal.Secret.from_name("openai-presentation-secret"),
        ])
    else:
        secrets.append(modal.Secret.from_name("openai-secret"))
    return secrets


GATEWAY_SECRETS = get_gateway_secrets()

@app.function(
    image=image,
    cpu=1.0,
    memory=1024,
    timeout=120,
    secrets=GATEWAY_SECRETS,
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
