import os
import uuid
import time
from typing import List

from langchain_core.embeddings import Embeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document
from back_end.config import CHROMA_PERSIST_DIR, CHROMA_COLLECTION_NAME
from back_end.core.downloader import delete_dir
import google.genai as genai

# ── OLD LOCAL GPU EMBEDDINGS (commented out) ────────────────────────────────
# from sentence_transformers import SentenceTransformer
#
# def _inject_position_ids_hook(module, args, kwargs):
#     if 'attention_mask' in kwargs and 'position_ids' not in kwargs:
#         attention_mask = kwargs['attention_mask']
#         position_ids = (attention_mask.long().cumsum(-1) - 1)
#         position_ids.masked_fill_(attention_mask == 0, 0)
#         kwargs['position_ids'] = position_ids
#     return args, kwargs
#
# class _SFRCodeEmbeddings(Embeddings):
#     QUERY_INSTRUCTION = "Instruct: Given Code or Text, retrieve relevant content. Query: "
#
#     def __init__(self, model_path='Salesforce/SFR-Embedding-Code-400M_R'):
#         print("Loading local SFR Code Model to GPU via ST...")
#         self.model = SentenceTransformer(model_path, device='cuda', trust_remote_code=True)
#         self.model.max_seq_length = 1024
#         self.model[0].auto_model.register_forward_pre_hook(_inject_position_ids_hook, with_kwargs=True)
#         print("Model loaded and position_ids hook attached!")
#
#     def embed_documents(self, texts: List[str]) -> List[List[float]]:
#         embeddings = self.model.encode(
#             texts,
#             batch_size=60,
#             show_progress_bar=True,
#             normalize_embeddings=True,
#         )
#         return embeddings.tolist()
#
#     def embed_query(self, text: str) -> List[float]:
#         prefixed_query = self.QUERY_INSTRUCTION + text
#         embeddings = self.model.encode(
#             [prefixed_query],
#             batch_size=1,
#             show_progress_bar=False,
#             normalize_embeddings=True,
#         )
#         return embeddings[0].tolist()
# ── END OLD LOCAL GPU EMBEDDINGS ─────────────────────────────────────────────


# ── NEW: Google Generative AI Embeddings (no GPU needed) ─────────────────────
def _get_embedding_function():
    class GoogleEmbeddings(Embeddings):
        def __init__(self):
            self.client = genai.Client(
                api_key=os.getenv("GOOGLE_API_KEY"),
                http_options={"api_version": "v1"}
            )

        def embed_documents(self, texts: List[str]) -> List[List[float]]:
            result = []
            for i, text in enumerate(texts):
                response = self.client.models.embed_content(
                    model="gemini-embedding-001",
                    contents=text
                )
                result.append(response.embeddings[0].values)
                # pause every 50 requests to avoid rate limit
                if (i + 1) % 50 == 0:
                    time.sleep(1)
            return result

        def embed_query(self, text: str) -> List[float]:
            response = self.client.models.embed_content(
                model="gemini-embedding-001",
                contents=text
            )
            return response.embeddings[0].values

    return GoogleEmbeddings()
# ─────────────────────────────────────────────────────────────────────────────


def _custom_add_document(vector_db: Chroma, documents: List[Document]):
    texts     = [doc.page_content for doc in documents]
    metadatas = [doc.metadata     for doc in documents]
    ids       = [str(uuid.uuid4()) for _ in documents]

    print(f"Generating embeddings via Google API for {len(texts)} documents...")
    all_embeddings = vector_db.embeddings.embed_documents(texts)

    CHROMA_BATCH_SIZE = 5000
    print("Inserting into ChromaDB...")
    collection = vector_db._collection

    for i in range(0, len(texts), CHROMA_BATCH_SIZE):
        batch_texts      = texts[i : i + CHROMA_BATCH_SIZE]
        batch_metadatas  = metadatas[i : i + CHROMA_BATCH_SIZE]
        batch_embeddings = all_embeddings[i : i + CHROMA_BATCH_SIZE]
        batch_ids        = ids[i : i + CHROMA_BATCH_SIZE]

        collection.add(
            documents=batch_texts,
            metadatas=batch_metadatas,
            embeddings=batch_embeddings,
            ids=batch_ids,
        )
        print(f"Inserted documents {i} to {i + len(batch_texts)}")


def build_vector_db(documents: List[Document]) -> Chroma:
    """Wipes the old DB and builds a fresh one."""
    if os.path.exists(CHROMA_PERSIST_DIR):
        print("Cleaning up old vector database...")
        delete_dir(CHROMA_PERSIST_DIR)

    embedding_fn = _get_embedding_function()
    vector_db = Chroma(
        persist_directory=CHROMA_PERSIST_DIR,
        embedding_function=embedding_fn,
        collection_name=CHROMA_COLLECTION_NAME,
    )

    if documents:
        _custom_add_document(vector_db, documents)

    return vector_db


def get_vector_db() -> Chroma:
    """Loads the EXISTING database (used by the Agent/Tools)."""
    embedding_fn = _get_embedding_function()
    vector_db = Chroma(
        persist_directory=CHROMA_PERSIST_DIR,
        embedding_function=embedding_fn,
        collection_name=CHROMA_COLLECTION_NAME,
    )
    return vector_db