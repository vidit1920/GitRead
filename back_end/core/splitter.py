from pathlib import Path
import json
from typing import List

from langchain_core.documents import Document
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
    MarkdownHeaderTextSplitter,
    RecursiveJsonSplitter,
)
from chonkie import CodeChunker

from config import CHUNK_OVERLAP,CHUNK_SIZE,AST_BASED_SPLITTING

def custom_splitter(docs: List[Document],current_dir: Path) -> List[Document]:
    all_chunks: List[Document] = []

    md_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "H1"), ("##", "H2"), ("###", "H3")]
    )

    text_fallback_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )

    json_splitter = RecursiveJsonSplitter(
        max_chunk_size=CHUNK_SIZE,
    )

    csv_splitter = RecursiveCharacterTextSplitter(
        separators=["\n"],
        chunk_size=CHUNK_SIZE,
        chunk_overlap=0,
    )

    for doc in docs:
        # --- FIX: Empty Files Check ---
        # Skip completely empty documents to save compute time
        if not doc.page_content or not doc.page_content.strip():
            continue

        source_str = doc.metadata.get("source", "")
        if not source_str:
            continue

        path = Path(source_str)
        ext = path.suffix.lower()

        try:
            repo_path = str(path.relative_to(current_dir))
        except ValueError:
            repo_path = str(path)

        base_metadata = {
            **doc.metadata,
            "file_name": path.name,
            "extension": ext,
            "path_rel_repo": repo_path,
        }

        doc_chunks: List[Document] = []

        # AST-based code chunking
        if ext in AST_BASED_SPLITTING:
            ast_chunker = CodeChunker(
                language=AST_BASED_SPLITTING.get(ext),
                tokenizer="character",
                chunk_size=CHUNK_SIZE,
                include_nodes=False,
            )
            try:
                chonkie_chunks = ast_chunker.chunk(doc.page_content)
                for chunk in chonkie_chunks:
                    doc_chunks.append(
                        Document(
                            page_content=chunk.text,
                            metadata=base_metadata.copy(),
                        )
                    )
            except Exception as e:
                print(
                    f"Warning: AST parsing failed for {path.name}. "
                    f"Falling back to text. Error: {e}"
                )
                doc_chunks = text_fallback_splitter.split_documents([doc])

        # Markdown
        elif ext in {".md", ".mdx"}:
            md_splits = md_splitter.split_text(doc.page_content)
            for split in md_splits:
                split.metadata = {**base_metadata, **split.metadata}
            doc_chunks = text_fallback_splitter.split_documents(md_splits)

        # JSON
        elif ext == ".json":
            try:
                parsed_data = json.loads(doc.page_content)
                
                #------ Normalize the data: because remeber json can be in two formate one single dictionary or list of dictionary 
                texts_to_split = []
                
                if isinstance(parsed_data, list):
                    # If it's a list, treat each item as a separate document
                    # This yields much better search results for RAG
                    for item in parsed_data:
                        if isinstance(item, dict):
                            texts_to_split.append(item)
                        else:
                            texts_to_split.append({"value": item})
                elif isinstance(parsed_data, dict):
                    # If it's already a dict, it's safe
                    texts_to_split.append(parsed_data)
                else:
                    # If it's a raw string/number/bool
                    texts_to_split.append({"value": parsed_data})
                # ---------------------------------------------

                # Create metadatas array to match the length of texts_to_split
                metadatas = [base_metadata.copy() for _ in texts_to_split]

                json_docs = json_splitter.create_documents(
                    texts=texts_to_split,
                    metadatas=metadatas,
                )
                doc_chunks.extend(json_docs)

            except json.JSONDecodeError as e:
                print(
                    f"Warning: Invalid JSON syntax in {path.name}. "
                    f"Falling back to text. Error: {e}"
                )
                doc_chunks = text_fallback_splitter.split_documents([doc])

        # JSONL
        elif ext == ".jsonl":
            for line in doc.page_content.splitlines():
                line = line.strip()
                if not line:
                    continue

                try:
                    line_data = json.loads(line)
                    
                    # --- Normalize JSONL lines ---
                    if not isinstance(line_data, dict):
                        line_data = {"value": line_data}
                        
                    json_docs = json_splitter.create_documents(
                        texts=[line_data],
                        metadatas=[base_metadata.copy()],
                    )
                    doc_chunks.extend(json_docs)
                except json.JSONDecodeError as e:
                    print(
                        f"Warning: Invalid JSONL line in {path.name}. "
                        f"Skipping. Error: {e}"
                    )

        # CSV / TSV
        elif ext in {".csv", ".tsv"}:
            lines = doc.page_content.splitlines()
            if not lines:
                continue

            header = lines[0]
            doc_chunks = csv_splitter.split_documents([doc])

            for i, chunk in enumerate(doc_chunks):
                if i == 0:
                    continue
                
                # --- FIX: CSV Header Logic ---
                # Ensure the chunk doesn't already have the header and strip leading newlines
                # to prevent broken/malformed line boundaries.
                if not chunk.page_content.startswith(header):
                    chunk.page_content = header + "\n" + chunk.page_content.lstrip()
                
                chunk.metadata = base_metadata.copy()

        # Fallback
        else:
            doc_chunks = text_fallback_splitter.split_documents([doc])
            
        # ── FILE NAME INJECTION ───────────────────────────────────────────────
        # Inject the file name into the text payload to give LLM Context.
        for chunk in doc_chunks:
            # 1. Update metadata
            chunk.metadata = {**base_metadata, **chunk.metadata}
            chunk.page_content = f"[FILE: {path.name}]\n\n" + chunk.page_content
            all_chunks.append(chunk)

    print(f"Original Files Processed : {len(docs)}")
    print(f"Total Chunks Generated   : {len(all_chunks)}")

    return all_chunks