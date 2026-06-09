import os
import uuid
import time
from typing import List

from langchain_core.embeddings import Embeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document

from back_end.config import (
    CHROMA_PERSIST_DIR,
    CHROMA_COLLECTION_NAME,
)

from back_end.core.downloader import delete_dir

import google.genai as genai


class GoogleEmbeddings(Embeddings):
    def __init__(self):
        api_key = os.getenv("GOOGLE_API_KEY")

        if not api_key:
            raise ValueError(
                "GOOGLE_API_KEY environment variable not found."
            )

        self.client = genai.Client(
            api_key=api_key,
            http_options={"api_version": "v1"}
        )

    def _embed_with_retry(self, text: str):
        max_retries = 5

        for attempt in range(max_retries):
            try:
                response = self.client.models.embed_content(
                    model="gemini-embedding-001",
                    contents=text
                )

                return response.embeddings[0].values

            except Exception as e:
                error_text = str(e)

                print(f"Embedding error: {error_text}")

                if "429" in error_text:
                    wait_time = (attempt + 1) * 10

                    print(
                        f"Rate limit hit. "
                        f"Waiting {wait_time} seconds..."
                    )

                    time.sleep(wait_time)
                    continue

                raise

        raise RuntimeError(
            "Failed to generate embedding after retries."
        )

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        embeddings = []

        total = len(texts)

        for idx, text in enumerate(texts):
            print(
                f"Generating embedding "
                f"{idx + 1}/{total}"
            )

            embedding = self._embed_with_retry(text)
            embeddings.append(embedding)

            time.sleep(1)

        return embeddings

    def embed_query(self, text: str) -> List[float]:
        return self._embed_with_retry(text)


def _get_embedding_function():
    return GoogleEmbeddings()


def _custom_add_document(
    vector_db: Chroma,
    documents: List[Document]
):
    texts = [doc.page_content for doc in documents]
    metadatas = [doc.metadata for doc in documents]
    ids = [str(uuid.uuid4()) for _ in documents]

    print(
        f"Generating embeddings for "
        f"{len(texts)} documents..."
    )

    all_embeddings = (
        vector_db.embeddings.embed_documents(texts)
    )

    CHROMA_BATCH_SIZE = 5000

    collection = vector_db._collection

    print("Inserting documents into ChromaDB...")

    for i in range(
        0,
        len(texts),
        CHROMA_BATCH_SIZE
    ):
        batch_texts = texts[
            i:i + CHROMA_BATCH_SIZE
        ]

        batch_metadatas = metadatas[
            i:i + CHROMA_BATCH_SIZE
        ]

        batch_embeddings = all_embeddings[
            i:i + CHROMA_BATCH_SIZE
        ]

        batch_ids = ids[
            i:i + CHROMA_BATCH_SIZE
        ]

        collection.add(
            documents=batch_texts,
            metadatas=batch_metadatas,
            embeddings=batch_embeddings,
            ids=batch_ids,
        )

        print(
            f"Inserted documents "
            f"{i} to {i + len(batch_texts)}"
        )


def build_vector_db(
    documents: List[Document]
) -> Chroma:
    """
    Delete old DB and rebuild.
    """

    if os.path.exists(
        CHROMA_PERSIST_DIR
    ):
        print(
            "Removing existing vector DB..."
        )

        delete_dir(
            CHROMA_PERSIST_DIR
        )

    embedding_fn = (
        _get_embedding_function()
    )

    vector_db = Chroma(
        persist_directory=CHROMA_PERSIST_DIR,
        embedding_function=embedding_fn,
        collection_name=CHROMA_COLLECTION_NAME,
    )

    if documents:
        _custom_add_document(
            vector_db,
            documents
        )

    return vector_db


def get_vector_db() -> Chroma:
    """
    Load existing DB.
    """

    embedding_fn = (
        _get_embedding_function()
    )

    vector_db = Chroma(
        persist_directory=CHROMA_PERSIST_DIR,
        embedding_function=embedding_fn,
        collection_name=CHROMA_COLLECTION_NAME,
    )

    return vector_db