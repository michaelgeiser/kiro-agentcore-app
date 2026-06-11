"""Batch processor service for grouping and processing audio chunks.

Groups audio chunks into batches based on configurable batch_size and processes
them sequentially, collecting results while maintaining original chunk order.
"""

import math
from typing import Callable, List

from src.models.audio_chunk import AudioChunk
from src.models.embedding_result import EmbeddingResult


def group_into_batches(
    chunks: List[AudioChunk], batch_size: int
) -> List[List[AudioChunk]]:
    """Group audio chunks into batches of at most batch_size.

    Properties that must hold (Property 10):
    - Produces exactly ceil(len(chunks) / batch_size) batches
    - Each batch has at most batch_size chunks
    - All chunks appear in exactly one batch
    - Chunk order is preserved

    Args:
        chunks: List of AudioChunk objects to group. Must be non-empty.
        batch_size: Maximum number of chunks per batch. Must be >= 1.

    Returns:
        List of batches, where each batch is a list of AudioChunk objects.

    Raises:
        ValueError: If chunks is empty or batch_size < 1.
    """
    if not chunks:
        raise ValueError("chunks list must not be empty")
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")

    batches: List[List[AudioChunk]] = []
    for i in range(0, len(chunks), batch_size):
        batches.append(chunks[i : i + batch_size])

    return batches


def process_batches(
    batches: List[List[AudioChunk]],
    process_fn: Callable[[AudioChunk], EmbeddingResult],
) -> List[EmbeddingResult]:
    """Process all batches and collect results maintaining chunk order.

    Iterates through batches sequentially, calling process_fn for each chunk
    within each batch. Results are collected in the original chunk order.

    Args:
        batches: List of batches from group_into_batches.
        process_fn: Function to call for each chunk (e.g., create_embedding).

    Returns:
        List of EmbeddingResult objects in original chunk order.
    """
    results: List[EmbeddingResult] = []
    for batch in batches:
        for chunk in batch:
            result = process_fn(chunk)
            results.append(result)
    return results
