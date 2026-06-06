import torch
from langchain_core.embeddings import Embeddings
from typing import List
from langchain_chroma import Chroma
from langchain_core.documents import Document
from sentence_transformers import SentenceTransformer
import uuid  # to generate ids 
from config import CHROMA_PERSIST_DIR,CHROMA_COLLECTION_NAME
import os
import shutil
from core.downloader import delete_dir

#This is fix for issue with model SFR-Embedding-Code-400M_R while working with latest RTX5050 
def _inject_position_ids_hook(module, args, kwargs):
    if 'attention_mask' in kwargs and 'position_ids' not in kwargs:
        attention_mask = kwargs['attention_mask']
        position_ids = (attention_mask.long().cumsum(-1) - 1)
        position_ids.masked_fill_(attention_mask == 0, 0)
        kwargs['position_ids'] = position_ids
    return args, kwargs


class _SFRCodeEmbeddings(Embeddings):

    #instruction prefix specified by the Salesforce AI Research team
    QUERY_INSTRUCTION = "Instruct: Given Code or Text, retrieve relevant content. Query: "

    def __init__(self, model_path='Salesforce/SFR-Embedding-Code-400M_R'):
        print("Loading local SFR Code Model to GPU via ST...")

        self.model = SentenceTransformer(model_path, device='cuda', trust_remote_code=True)
        self.model.max_seq_length = 1024
        self.model[0].auto_model.register_forward_pre_hook(_inject_position_ids_hook, with_kwargs=True)

        print("Model loaded and position_ids hook attached!")

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        embeddings = self.model.encode(
            texts,
            batch_size=60,
            show_progress_bar=True,
            normalize_embeddings=True,
        )
        return embeddings.tolist()

    def embed_query(self, text: str) -> List[float]:
        # The query MUST have the exact instruction prefix applied before encoding
        prefixed_query = self.QUERY_INSTRUCTION + text
        embeddings = self.model.encode(
            [prefixed_query],
            batch_size=1,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return embeddings[0].tolist()

    
def _custom_add_document(vector_db: Chroma, documents: List[Document]):
    texts     = [doc.page_content for doc in documents]
    metadatas = [doc.metadata     for doc in documents]
    ids       = [str(uuid.uuid4()) for _ in range(len(documents))]

    print(f"Running Global Smart Batching on GPU for {len(texts)} documents...")
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
        print(f"Successfully inserted documents {i} through {i + len(batch_texts)}")


def build_vector_db(documents: List[Document]) -> Chroma:
    """Wipes the old DB and builds a fresh one."""
    # 1. Cleanup previous database
    if os.path.exists(CHROMA_PERSIST_DIR):
        print("Cleaning up old vector database...")
        delete_dir(CHROMA_PERSIST_DIR)

    # 2. Initialize new database
    local_embedding_fn = _SFRCodeEmbeddings()
    vector_db = Chroma(
        persist_directory=CHROMA_PERSIST_DIR,
        embedding_function=local_embedding_fn,
        collection_name=CHROMA_COLLECTION_NAME,
    )

    # 3. Add documents using our custom batcher
    if documents:
        _custom_add_document(vector_db, documents)

    return vector_db

#to get stored vector_bd used in agent/tools.py
def get_vector_db() -> Chroma:
    """Loads the EXISTING database (Used by the Agent/Tools)."""
    local_embedding_fn = _SFRCodeEmbeddings()
    vector_db = Chroma(
        persist_directory=CHROMA_PERSIST_DIR,
        embedding_function=local_embedding_fn,
        collection_name=CHROMA_COLLECTION_NAME,
    )
    return vector_db