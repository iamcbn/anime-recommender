"""
backend/rag_pipeline/inference_client.py

Dual-mode Inference Client providing seamless abstraction between:
1. LocalInferenceClient: In-process Embedder & Ranker for local dev, Docker, CI, and unit testing.
   Calls are offloaded via asyncio.to_thread to keep the event loop non-blocking.
2. ModalInferenceClient: Dispatches embed and rerank tasks to remote GPU ModelWorker via Modal RPC.
   Zero PyTorch/CUDA weights are loaded on the CPU Gateway container.
"""

import os
import logging
import asyncio
from abc import ABC, abstractmethod
from typing import List, Tuple, Optional, Any, Dict

logger = logging.getLogger(__name__)


def sanitize_candidates_for_rpc(candidates: Any) -> list:
    """
    Sanitizes database results for clean RPC wire serialization.
    - Converts psycopg2 DictRow objects or tuples into standard Python dicts/lists.
    - Strips large redundant fields (like 'embedding_text') to keep network transfer lean (<50KB).
    """
    if not candidates:
        return []

    clean_results = []
    for group in candidates:
        if not group:
            clean_results.append([])
            continue

        clean_group = []
        for item in group:
            if hasattr(item, "keys"):
                # DictRow or standard dict
                d = dict(item)
                # Strip heavy text column if present (used only for offline embedding)
                d.pop("embedding_text", None)
                clean_group.append(d)
            elif isinstance(item, (list, tuple)):
                # Scalar tuple/list
                clean_group.append(list(item))
            else:
                clean_group.append(item)
        clean_results.append(clean_group)

    return clean_results


class BaseInferenceClient(ABC):
    """Abstract interface for dense neural embedding and cross-encoder reranking."""

    @abstractmethod
    async def embed_queries(self, queries: List[str]) -> List[Tuple[List[float], List[float]]]:
        """Asynchronously compute SBERT and FastText query embeddings."""
        pass

    @abstractmethod
    def embed_queries_sync(self, queries: List[str]) -> List[Tuple[List[float], List[float]]]:
        """Synchronously compute SBERT and FastText query embeddings."""
        pass

    @abstractmethod
    async def rerank_candidates(
        self,
        query: str,
        candidates: list,
        top_k: int,
        seen_ids: Optional[set[int]] = None,
        include_metadata: bool = True,
    ) -> List[Dict[str, Any]]:
        """Asynchronously pool, cross-encode rerank, and collapse candidate anime."""
        pass

    @abstractmethod
    def rerank_candidates_sync(
        self,
        query: str,
        candidates: list,
        top_k: int,
        seen_ids: Optional[set[int]] = None,
        include_metadata: bool = True,
    ) -> List[Dict[str, Any]]:
        """Synchronously pool, cross-encode rerank, and collapse candidate anime."""
        pass


class LocalInferenceClient(BaseInferenceClient):
    """
    In-process inference client.
    Lazy-loads Embedder and Ranker on first access and wraps blocking PyTorch/FastText
    calls with asyncio.to_thread to guarantee zero FastAPI event loop starvation.
    """

    def __init__(self):
        self._embedder = None
        self._ranker = None

    @property
    def embedder(self):
        if self._embedder is None:
            from .helper.service_embedding import Embedder
            self._embedder = Embedder()
        return self._embedder

    @property
    def ranker(self):
        if self._ranker is None:
            from .helper.ranking import Ranker
            self._ranker = Ranker()
        return self._ranker

    def embed_queries_sync(self, queries: List[str]) -> List[Tuple[List[float], List[float]]]:
        return self.embedder.execute(queries=queries)

    async def embed_queries(self, queries: List[str]) -> List[Tuple[List[float], List[float]]]:
        return await asyncio.to_thread(self.embed_queries_sync, queries)

    def rerank_candidates_sync(
        self,
        query: str,
        candidates: list,
        top_k: int,
        seen_ids: Optional[set[int]] = None,
        include_metadata: bool = True,
    ) -> List[Dict[str, Any]]:
        return self.ranker.execute(
            user_query=query,
            all_results=candidates,
            top_k=top_k,
            seen_ids=seen_ids,
            include_metadata=include_metadata,
        )

    async def rerank_candidates(
        self,
        query: str,
        candidates: list,
        top_k: int,
        seen_ids: Optional[set[int]] = None,
        include_metadata: bool = True,
    ) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(
            self.rerank_candidates_sync,
            query,
            candidates,
            top_k,
            seen_ids,
            include_metadata,
        )


class ModalInferenceClient(BaseInferenceClient):
    """
    Modal Serverless inference client.
    Invokes the remote GPU ModelWorker actor (@app.cls) across Modal RPC.
    Runs completely non-blocking on the CPU Gateway container.
    """

    def __init__(self):
        self._worker_cls = None
        self._local_fallback = None

    def _get_worker_cls(self):
        if self._worker_cls is None:
            try:
                import modal
                # Look up Cls defined in modal_deploy.py
                from modal_deploy import ModelWorker
                self._worker_cls = ModelWorker
            except Exception as e:
                logger.warning(
                    f"Modal ModelWorker lookup failed ({e}). Initializing LocalInferenceClient fallback.",
                    exc_info=True,
                )
                self._local_fallback = LocalInferenceClient()
        return self._worker_cls

    @property
    def embedder(self):
        """Fallback property for backwards compatibility with legacy module references."""
        if self._local_fallback is None:
            self._local_fallback = LocalInferenceClient()
        return self._local_fallback.embedder

    @property
    def ranker(self):
        """Fallback property for backwards compatibility with legacy module references."""
        if self._local_fallback is None:
            self._local_fallback = LocalInferenceClient()
        return self._local_fallback.ranker

    async def embed_queries(self, queries: List[str]) -> List[Tuple[List[float], List[float]]]:
        worker_cls = self._get_worker_cls()
        if self._local_fallback is not None or worker_cls is None:
            return await self._local_fallback.embed_queries(queries)

        try:
            worker = worker_cls()
            # Modal method remote async invocation
            if hasattr(worker.embed_queries, "aio"):
                return await worker.embed_queries.aio(queries=queries)
            return await asyncio.to_thread(worker.embed_queries.remote, queries=queries)
        except Exception as e:
            logger.error(f"Modal RPC embed_queries failed: {e}. Falling back to local.", exc_info=True)
            if self._local_fallback is None:
                self._local_fallback = LocalInferenceClient()
            return await self._local_fallback.embed_queries(queries)

    def embed_queries_sync(self, queries: List[str]) -> List[Tuple[List[float], List[float]]]:
        worker_cls = self._get_worker_cls()
        if self._local_fallback is not None or worker_cls is None:
            return self._local_fallback.embed_queries_sync(queries)

        try:
            worker = worker_cls()
            return worker.embed_queries.remote(queries=queries)
        except Exception as e:
            logger.error(f"Modal RPC embed_queries_sync failed: {e}. Falling back to local.", exc_info=True)
            if self._local_fallback is None:
                self._local_fallback = LocalInferenceClient()
            return self._local_fallback.embed_queries_sync(queries)

    async def rerank_candidates(
        self,
        query: str,
        candidates: list,
        top_k: int,
        seen_ids: Optional[set[int]] = None,
        include_metadata: bool = True,
    ) -> List[Dict[str, Any]]:
        worker_cls = self._get_worker_cls()
        if self._local_fallback is not None or worker_cls is None:
            return await self._local_fallback.rerank_candidates(
                query, candidates, top_k, seen_ids, include_metadata
            )

        sanitized = sanitize_candidates_for_rpc(candidates)
        seen_list = list(seen_ids) if seen_ids else None

        try:
            worker = worker_cls()
            if hasattr(worker.rerank_candidates, "aio"):
                return await worker.rerank_candidates.aio(
                    query=query,
                    candidates=sanitized,
                    top_k=top_k,
                    seen_ids=seen_list,
                    include_metadata=include_metadata,
                )
            return await asyncio.to_thread(
                worker.rerank_candidates.remote,
                query=query,
                candidates=sanitized,
                top_k=top_k,
                seen_ids=seen_list,
                include_metadata=include_metadata,
            )
        except Exception as e:
            logger.error(f"Modal RPC rerank_candidates failed: {e}. Falling back to local.", exc_info=True)
            if self._local_fallback is None:
                self._local_fallback = LocalInferenceClient()
            return await self._local_fallback.rerank_candidates(
                query, candidates, top_k, seen_ids, include_metadata
            )

    def rerank_candidates_sync(
        self,
        query: str,
        candidates: list,
        top_k: int,
        seen_ids: Optional[set[int]] = None,
        include_metadata: bool = True,
    ) -> List[Dict[str, Any]]:
        worker_cls = self._get_worker_cls()
        if self._local_fallback is not None or worker_cls is None:
            return self._local_fallback.rerank_candidates_sync(
                query, candidates, top_k, seen_ids, include_metadata
            )

        sanitized = sanitize_candidates_for_rpc(candidates)
        seen_list = list(seen_ids) if seen_ids else None

        try:
            worker = worker_cls()
            return worker.rerank_candidates.remote(
                query=query,
                candidates=sanitized,
                top_k=top_k,
                seen_ids=seen_list,
                include_metadata=include_metadata,
            )
        except Exception as e:
            logger.error(f"Modal RPC rerank_candidates_sync failed: {e}. Falling back to local.", exc_info=True)
            if self._local_fallback is None:
                self._local_fallback = LocalInferenceClient()
            return self._local_fallback.rerank_candidates_sync(
                query, candidates, top_k, seen_ids, include_metadata
            )


def get_inference_client() -> BaseInferenceClient:
    """
    Factory function returning the appropriate inference client based on runtime context.
    - Uses ModalInferenceClient if INFERENCE_MODE == 'modal' or MODAL_IS_REMOTE is set.
    - Otherwise uses LocalInferenceClient for local dev, Docker, and test suites.
    """
    mode = os.getenv("INFERENCE_MODE", "").lower()
    is_modal = os.getenv("MODAL_IS_REMOTE") or os.getenv("MODAL_ENVIRONMENT")

    if mode == "modal" or is_modal:
        logger.info("Initializing ModalInferenceClient (GPU actor RPC mode)")
        return ModalInferenceClient()

    logger.info("Initializing LocalInferenceClient (in-process PyTorch mode)")
    return LocalInferenceClient()
