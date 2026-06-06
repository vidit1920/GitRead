# main.py
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage

# Import your existing backend logic
from back_end.core.downloader import download_github_repo, delete_dir
from back_end.core.loader import count_valid_supported_files, load_repository_as_documents
from back_end.core.splitter import custom_splitter
from back_end.core.embeddings import build_vector_db
from back_end.agent.graph import build_workflow
from back_end.config import MAX_FILES_TO_CREATE_VECTOR_DB
import json

load_dotenv()

app = FastAPI()

# 1. CORS Middleware (Crucial for frontend connection)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Global State Variables
GLOBAL_APP = None
GLOBAL_CHAT_HISTORY = []

# 3. Request Models
class RepoRequest(BaseModel):
    url: str

class ChatRequest(BaseModel):
    message: str


# --- ENDPOINTS ---
@app.post("/init-repo")
async def initialize_repository(request: RepoRequest):
    """Downloads repo, builds vector DB, and streams status updates as JSON."""
    
    async def process_stream():
        global GLOBAL_APP, GLOBAL_CHAT_HISTORY
        
        current_dir = Path(os.getcwd())
        temp_git_repo_storage = current_dir / "temp_git_repo_storage"

        # Helper function that JUST formats the string
        def format_msg(status: str, task_name: str):
            payload = {
                "status": status.upper(), # Forces uppercase to prevent JS errors
                "task": task_name,
            }
            return f"data: {json.dumps(payload)}\n\n"

        try:
            yield format_msg("START", "Preparing to load repository")
            await asyncio.sleep(0.01) # Flush to UI

            delete_dir(temp_git_repo_storage)
            temp_git_repo_storage.mkdir(parents=True, exist_ok=True)

            yield format_msg("SUCCESS", "Ready to load repository")
            
            yield format_msg("START", f"Loading repository from {request.url}...")
            await asyncio.sleep(0.01)
            
            extracted_path = await asyncio.to_thread(download_github_repo, request.url, temp_git_repo_storage)
            
            yield format_msg("SUCCESS", "Repo successfully loaded.")
            await asyncio.sleep(0.01)

        except Exception as e:
            yield format_msg("ERROR", f"Failed to download repository: {e}")
            return

        yield format_msg("START", "Counting supported files...")
        await asyncio.sleep(0.01)
        
        file_count = await asyncio.to_thread(count_valid_supported_files, temp_git_repo_storage)
        
        if file_count > MAX_FILES_TO_CREATE_VECTOR_DB:
            yield format_msg("WARNING", f"Repo is large ({file_count} files). Building workflow without Vector DB...")
            await asyncio.sleep(0.01)
            GLOBAL_APP = await asyncio.to_thread(build_workflow, temp_git_repo_storage, False)
        else:
            yield format_msg("SUCCESS", f"Found {file_count} files to process")
            
            yield format_msg("START", "Loading repository files as documents...")
            await asyncio.sleep(0.01)
            doc = await asyncio.to_thread(load_repository_as_documents, temp_git_repo_storage)
            yield format_msg("SUCCESS", "Files loaded")

            yield format_msg("START", "Preparing files to analyse")
            await asyncio.sleep(0.01)
            all_splits = await asyncio.to_thread(custom_splitter, doc, current_dir)
            yield format_msg("SUCCESS", "Done preparing")

            yield format_msg("START", "Analysing files (This may take 1 to 10 minutes)...")
            await asyncio.sleep(0.01)
            vector_db = await asyncio.to_thread(build_vector_db, all_splits)
            yield format_msg("SUCCESS", "Done Analysing")

            yield format_msg("START", "Loading model")
            await asyncio.sleep(0.01)
            GLOBAL_APP = await asyncio.to_thread(build_workflow, temp_git_repo_storage, True, all_splits, vector_db)
            yield format_msg("SUCCESS", "Model Loaded")

        GLOBAL_CHAT_HISTORY = []
        
        # Final success message
        yield format_msg("FINISHED", "System ready. Switching to chat.")
        await asyncio.sleep(0.01)

    return StreamingResponse(process_stream(), media_type="text/event-stream")


@app.post("/chat")
async def chat_stream(request: ChatRequest):
    """Streams the LangGraph response back to the frontend."""
    
    if not GLOBAL_APP:
        return {"error": "System not initialized. Please load a repo first."}

    async def generate_response():
        global GLOBAL_CHAT_HISTORY
        
        user_input = request.message
        GLOBAL_CHAT_HISTORY.append(HumanMessage(content=user_input))
        
        config = {"recursion_limit": 100}
        final_ai_message = None
        
        def format_chat_chunk(msg_type: str, text: str):
            payload = {
                "type": msg_type,
                "text": text
            }
            return f"data: {json.dumps(payload)}\n\n"

        for event in GLOBAL_APP.stream({"messages": GLOBAL_CHAT_HISTORY}, stream_mode="values", config=config):
            message = event["messages"][-1]
            message.pretty_print()
            
            if message.type == "ai" and getattr(message, "tool_calls", None):
                for tool in message.tool_calls:
                    yield format_chat_chunk("tool", f"Browsing Codebase..")
                    await asyncio.sleep(0.01)

            if message.type == "ai":
                if isinstance(message.content, list):
                    for block in message.content:
                        if isinstance(block, dict) and "thinking" in block:
                            clean_think = block["thinking"]
                            yield format_chat_chunk("thinking", clean_think)
                            await asyncio.sleep(0.01)
                            
                elif isinstance(message.content, str) and message.content.strip():
                    clean_text = message.content
                    yield format_chat_chunk("message", clean_text)
                    await asyncio.sleep(0.01)
                    final_ai_message = message

        if final_ai_message:
            GLOBAL_CHAT_HISTORY.append(final_ai_message)
            
        yield format_chat_chunk("end", "[END]")
        await asyncio.sleep(0.01)

    return StreamingResponse(generate_response(), media_type="text/event-stream")


# ── Serve frontend — must be LAST ──────────────────────────────────────────────
app.mount("/", StaticFiles(
    directory=r"front_end",
    html=True
), name="frontend")