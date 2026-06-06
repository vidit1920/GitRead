import os
import fnmatch
import itertools
from pathlib import Path
from langchain.tools import tool
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.tools import BaseTool
from config import EXCLUDE_PATTERNS



def get_code_search_tools(
    repo_storage: Path, 
    is_vector_db_created: bool, 
    all_splits: list[Document] = None, 
    vector_db = None
)-> list[BaseTool]:

    # Initialize BM25 only if we have vector data
    bm25_retriever = None
    if is_vector_db_created and all_splits:
        bm25_retriever = BM25Retriever.from_documents(all_splits, k=10)
    @tool
    def exact_code_search(search_pattern: str) -> str:
        """
        Search the codebase for an exact literal string.
        Use this tool FIRST when looking for exact function definitions, variable usages, 
        specific syntax, or known class names.
        Input should be the exact string you want to find. (Note: Regex is NOT supported).
        """
        try:
            base_path = repo_storage.resolve()
            MAX_LINES = 350
            matches = []
            
            # 1. Updated validation function using your global EXCLUDE_PATTERNS
            def is_valid_file(p: Path) -> bool:
                # Skip non-files and symlinks
                if p.is_symlink() or not p.is_file(): 
                    return False
                    
                # Convert path to string with forward slashes for consistent glob matching
                path_str = p.as_posix() 
                
                # Check against global patterns
                for pattern in EXCLUDE_PATTERNS:
                    if fnmatch.fnmatch(path_str, pattern):
                        return False
                        
                return True

            # 2. The combined search logic
            for file_path in base_path.rglob("*"):
                if not is_valid_file(file_path):
                    continue

                try:
                    rel_path = file_path.relative_to(repo_storage).as_posix()
                    
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        for i, line in enumerate(f, 1):
                            if search_pattern in line:
                                matches.append(f"{rel_path}:{i}:{line.strip()}")
                                
                                if len(matches) >= MAX_LINES:
                                    break 
                except Exception:
                    continue
                
                if len(matches) >= MAX_LINES:
                    break

            # 3. Format output
            if not matches:
                return f"No exact matches found for '{search_pattern}'."

            output = "\n".join(matches)
            
            if len(matches) >= MAX_LINES:
                return f"--- EXACT MATCHES (first {MAX_LINES}) ---\n{output}\n\n... (Output truncated to save context)"
            else:
                return f"--- EXACT MATCHES ---\n{output}"

        except Exception as e:
            return f"Search error: {str(e)}"

    # -----------------------------------------------------------------------------
    # Tool 2: Retrival using BM25
    # -----------------------------------------------------------------------------
    @tool
    def keyword_code_search(query: str, k: int = 5) -> str:
        """
        Search the codebase using exact keyword matching (BM25).
        Use this tool when looking for files containing specific keywords, error messages, 
        or terminology where exact syntax matching isn't strictly required but specific words are important.
        Input should be a set of relevant keywords and the number of chunks (k) to return.
        """
        
        try:
            # Update k dynamically so the agent can control how much context it gets
            bm25_retriever.k = k
            docs = bm25_retriever.invoke(query)
            
            if not docs:
                return f"No keyword matches found for '{query}'."
                
            formatted_chunks = []
            for doc in docs:
                source_file = doc.metadata.get("source", "Unknown File")
                formatted_chunks.append(f"--- File_Source: {source_file} ---\n{doc.page_content}")
                
            return "\n\n".join(formatted_chunks)
            
        except Exception as e:
            return f"Keyword search error: {str(e)}"

    # -----------------------------------------------------------------------------
    # Tool 3: Simple retrival from vectordb based on cosine sililarity 
    # -----------------------------------------------------------------------------
    @tool
    def semantic_code_search(query: str, k: int = 5) -> str:
        """
        Search the codebase using semantic vector embeddings.
        Use this tool to understand concepts, architecture, or ask natural language questions 
        like "how does the database connection work?" or "where is the staging logic?"
        Do NOT use this for exact variable lookups or specific function signatures.
        Input should be a natural language query and the number of chunks (k) to return.
        """
        try:
            # Create a dynamic retriever on the fly to inject the agent's requested 'k'
            # Adjust search_type to "similarity" or "similarity_score_threshold" based on your DB setup
            temp_dense_retriever = vector_db.as_retriever(
                search_type="similarity", 
                search_kwargs={"k": k}
            )
            docs = temp_dense_retriever.invoke(query)
            
            if not docs:
                return f"No semantic matches found for '{query}'."
                
            formatted_chunks = []
            for doc in docs:
                source_file = doc.metadata.get("source", "Unknown File")
                formatted_chunks.append(f"--- File_Source: {source_file} ---\n{doc.page_content}")
                
            return "\n\n".join(formatted_chunks)
            
        except Exception as e:
            return f"Semantic search error: {str(e)}"
    # -----------------------------------------------------------------------------
    # Tool 4: get contents of a specified file
    # -----------------------------------------------------------------------------

    @tool
    def get_specific_file(file_path: str, start_line: int = None, end_line: int = None) -> str:
        """
        Get the text contents of a specific file from the repository.
        - If start_line and end_line are NOT provided, it returns the entire file (up to 50,000 bytes).
        - If start_line and end_line ARE provided (1-indexed), it returns only those specific lines, bypassing the file size limit.
        Use this tool to read entire small files, or to paginate through massive files by requesting specific line ranges.
        Input should be the exact file path, and optionally the start and end line numbers.
        """
        try:
            clean_path = file_path.lstrip('/')
            target_path = (repo_storage / clean_path).resolve()
            
            # 1. Security Check: Prevent path traversal
            if not target_path.is_relative_to(repo_storage):
                return "Error: Access denied. You cannot read files outside the repository root."

            absolute_file_path = str(target_path)

            # ---------------------------------------------------------
            # MODE 1: Specific Line Range Requested
            # ---------------------------------------------------------
            if start_line is not None or end_line is not None:
                # Handle cases where the LLM provides one but not the other
                start_line = start_line if start_line is not None else 1
                end_line = end_line if end_line is not None else (start_line + 300)
                
                # Sanity checks for the agent
                if start_line < 1:
                    return "Error: start_line must be >= 1."
                if end_line < start_line:
                    return "Error: end_line must be >= start_line."
                
                # Protect context window: limit the maximum lines requested at once
                MAX_LINES_TO_READ = 500
                if (end_line - start_line + 1) > MAX_LINES_TO_READ:
                    return f"Error: You can only request up to {MAX_LINES_TO_READ} lines at a time to save context space."

                try:
                    # Use itertools.islice to lazily read only the needed lines without loading the whole file into RAM
                    with open(absolute_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        # islice is 0-indexed, so we subtract 1 from start_line. end_line is exclusive.
                        lines = list(itertools.islice(f, start_line - 1, end_line))
                    
                    if not lines:
                        return f"Error: The requested lines ({start_line}-{end_line}) are out of bounds for this file."
                        
                    content = "".join(lines)
                    return f"--- File_Source: {file_path} (Lines {start_line}-{end_line}) ---\n{content}"
                    
                except Exception as e:
                    return f"Error reading specific lines from {file_path}: {str(e)}"

            # ---------------------------------------------------------
            # MODE 2: Entire File Requested
            # ---------------------------------------------------------
            else:
                # Check file size using the ABSOLUTE path
                file_size = os.path.getsize(absolute_file_path)
                
                # Rough estimation: 1 byte is roughly 1 character in standard encoding
                if file_size > 50000:
                    return (f"Error: The file '{file_path}' is too large ({file_size} bytes) to load entirely. "
                            f"Please use this tool again and provide `start_line` and `end_line` parameters to read specific sections or consider other tools such as exact_code_serch.")

            with open(absolute_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
                return f"--- File_Source: {file_path} ---\n{content}"
                
        except FileNotFoundError:
            return f"Error: The file '{file_path}' was not found. Please verify the path."
        except Exception as e:
            return f"Error loading {file_path}: {str(e)}"
        
    # -----------------------------------------------------------------------------
    # Tool 5: directory look up [like ls in terminal]
    # -----------------------------------------------------------------------------
    @tool
    def list_directory_contents(directory_path: str) -> str:
        """
        List the contents of a specific directory within the repository.
        Use this tool to explore the folder structure, see what files exist, 
        and understand how the codebase is organized.
        Input should be a relative path from the repository root (e.g., 'repo_name/components','repo_name','repo_name/data/readmes/).
        """
        try:
            # 1. Security & Path Resolution (Crucial!)
            base_path = Path(repo_storage).resolve()
            
            # Handle cases where the LLM passes absolute paths or starts with '/'
            clean_path = directory_path.lstrip('/')
            target_path = (base_path / clean_path).resolve()
            
            # Prevent Path Traversal Attacks (e.g., agent trying to read '../../etc/passwd')
            if not target_path.is_relative_to(base_path):
                return "Error: Access denied. You cannot read directories outside the repository root."
                
            # 2. State Checking
            if not target_path.exists():
                return f"Error: The directory '{directory_path}' does not exist in this repository."
                
            if not target_path.is_dir():
                return (f"Error: '{directory_path}' is a file, not a directory. "
                        f"If you want to read it, use the get_specific_file tool.")

            # 3. Gather Context-Rich Contents
            items = []
            for entry in os.scandir(target_path):
                # Skip annoying OS files
                if entry.name in ['.DS_Store', 'Thumbs.db']:
                    continue
                    
                if entry.is_dir():
                    items.append(f"📁 [DIR]  {entry.name}/")
                else:
                    # Add file sizes so the agent knows if a file is safe to read whole
                    size_kb = entry.stat().st_size / 1024
                    items.append(f"📄 [FILE] {entry.name} ({size_kb:.1f} KB)")
                    
            # Sort directories first, then files alphabetically
            items.sort(key=lambda x: (not x.startswith("📁"), x.lower()))
            
            if not items:
                return f"The directory '{directory_path}' is completely empty."
                
            # 4. Context Window Protection
            MAX_ITEMS = 200
            if len(items) > MAX_ITEMS:
                truncated_count = len(items) - MAX_ITEMS
                items = items[:MAX_ITEMS]
                items.append(f"\n... (Output truncated: {truncated_count} more items not shown to save space) ...")
                
            return f"--- Contents of /{clean_path} ---\n" + "\n".join(items)
            
        except Exception as e:
            return f"An error occurred while reading the directory: {str(e)}"
    # -----------------------------------------------------------------------------
    # Tool 6: find_file_path_by_pattern
    # -----------------------------------------------------------------------------
    @tool
    def find_file_path_by_pattern(filename_pattern: str) -> str:
        """
        Search the repository for files matching a specific name or pattern.
        Use this tool when you know the name of the file or script you are looking for 
        (e.g., 'build_npm_package.py' or '*.md').
        Input should be a filename or glob pattern.
        """
        try:
            base_path = repo_storage.resolve()
            matches = []
            
            # Walk through all files
            for file_path in base_path.rglob("*"):
                if file_path.is_file():
                    # Check if the filename matches the pattern
                    if fnmatch.fnmatch(file_path.name.lower(), filename_pattern.lower()):
                        rel_path = file_path.relative_to(base_path)
                        matches.append(rel_path.as_posix())
                        
                        if len(matches) >= 200:
                            output = '\n'.join(matches)
                            return f"--- FOUND FILES(truncated to 200) ---\n{output}" 
                            
            if not matches:
                return f"No files found matching the name '{filename_pattern}'."
            
            output = '\n'.join(matches)
            return f"--- FOUND FILES ---\n{output}"
            
        except Exception as e:
            return f"File search error: {str(e)}"
        
    tools = [ exact_code_search, get_specific_file, list_directory_contents, find_file_path_by_pattern]

    if is_vector_db_created :
        tools.extend([semantic_code_search,keyword_code_search])

    return tools

