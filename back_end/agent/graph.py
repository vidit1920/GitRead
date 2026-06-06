import tiktoken
from langchain_core.messages import trim_messages,HumanMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import MessagesState,StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import BaseModel, Field
from typing import Literal
import json
from pathlib import Path
from langchain_core.documents import Document
from agent.tools import get_code_search_tools

from config import (
    SUPERVISOR_SYSTEM_PROMPT,
    AGENT_SYSTEM_PROMPT_HEADER,
    AGENT_SYSTEM_PROMPT_TOOLS,
    AGENT_SYSTEM_PROMPT_TOOLS_NO_DB,
    AGENT_SYSTEM_PROMPT_FOOTER,
)

enc = tiktoken.get_encoding("cl100k_base")

def _tiktoken_counter(messages):
    total = 0
    for m in messages:
        text_to_encode = ""
        
        # 1. Extract content and tool_calls safely
        if isinstance(m, dict):
            content = m.get("content", "")
            tool_calls = m.get("tool_calls", [])
        else:
            content = getattr(m, "content", "")
            tool_calls = getattr(m, "tool_calls", [])
            
        # 2. Handle string or list content
        if isinstance(content, list):
            text_to_encode += str(content)
        else:
            text_to_encode += str(content)
            
        # 3. CRITICAL: Catch tool calls so they don't bypass the counter
        if tool_calls:
            text_to_encode += json.dumps(tool_calls)
            
        # Encode and count
        total += len(enc.encode(text_to_encode))
    
    return total 

# ---------------------------------------------------------
# 1. AGENT NODE
# ---------------------------------------------------------
def initialize_agent(is_vector_db_created: bool, tools: list):
    # llm = ChatGoogleGenerativeAI( model="gemini-3.1-flash-lite-preview",temperature=0 )
    llm = ChatGoogleGenerativeAI( model="gemma-4-31b-it",temperature=0 )
    llm_with_tools = llm.bind_tools(tools)

    message_trimmer = trim_messages(
        max_tokens=200000, 
        strategy="last",
        token_counter=_tiktoken_counter, # We Use the Gemini model's specific token counter but it will make http request which will take too long so just just tiktoken wich will be good enough
        include_system=True, # NEVER delete the system prompt/repo map
        allow_partial=False # Don't chop a message in half
    )

    # Call the model to generate a response based on the current state. 
    # Given the question, it will decide to retrieve using the retriever tool, or simply respond to the user.
    def generate_query_or_respond(state: MessagesState):

        if is_vector_db_created:
            system_prompt = f"{AGENT_SYSTEM_PROMPT_HEADER}\n\n{AGENT_SYSTEM_PROMPT_TOOLS}\n\n{AGENT_SYSTEM_PROMPT_FOOTER}"
        else:
            system_prompt = f"{AGENT_SYSTEM_PROMPT_HEADER}\n\n{AGENT_SYSTEM_PROMPT_TOOLS_NO_DB}\n\n{AGENT_SYSTEM_PROMPT_FOOTER}"

        # 1. Inject the system prompt into the message history
        messages_to_evaluate = [{"role": "system", "content": system_prompt}] + state["messages"]
        
        # 2. to save context window,or not to runout of tokens we trim the context from past which in above max limit that we
        trimmed_messages = message_trimmer.invoke(messages_to_evaluate)
        
        # 3. Generate the response (PASS IN THE TRIMMED MESSAGES)
        response = llm_with_tools.invoke(trimmed_messages) 
        
        return {"messages": [response]}
    return generate_query_or_respond


# ---------------------------------------------------------
# 2. THE LEAD ARCHITECT (SUPERVISOR NODE)
# ---------------------------------------------------------

# 1. Define the decision schema
class SupervisorDecision(BaseModel):
    reasoning: str = Field(
        description="1. What did the user ask? 2. What raw data is in the tool outputs? 3. Is the raw data sufficient to answer the user?"
    )
    status: Literal["ACCEPT", "REJECT"] = Field(
        description="ACCEPT if the RAW TOOL OUTPUTS contain enough info to answer the user. REJECT if the agent needs to search for more specific files."
    )
    content: str = Field(
        description="If ACCEPT: Write the final, exhaustive response to the user. If REJECT: Write targeted instructions telling the agent what to search for next."
    )

def initialize_supervisor():

    powerful_llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.2,max_output_tokens=65536)
    powerful_agent = powerful_llm.with_structured_output(SupervisorDecision)

    def supervisor_node(state: MessagesState):
        # Calculate iteration count based on previous feedback messages
        iteration_count = sum(
            1 for m in state["messages"] 
            if isinstance(m, HumanMessage) and "SUPERVISOR FEEDBACK:" in m.content
        )

        system_prompt =  SUPERVISOR_SYSTEM_PROMPT

        # STRUCTURAL SAFEGUARD: Force accept after 2 rejections
        if iteration_count >= 2:
            system_prompt += """
            \n\n*** CRITICAL OVERRIDE ***
            You have rejected the researcher 2 times. You MUST now output status="ACCEPT" and synthesize the best possible final answer from ALL available evidence, explicitly noting what is implicit vs explicit. DO NOT REJECT.
            """

        messages_to_evaluate = [{"role": "system", "content": system_prompt}] + state["messages"]
        decision = powerful_agent.invoke(messages_to_evaluate)
        
        if decision.status == "ACCEPT":
            return {"messages": [AIMessage(content=decision.content)]}
        else:
            return {"messages": [HumanMessage(content=f"SUPERVISOR FEEDBACK: {decision.content}")]}
    return supervisor_node
        
# --- Custom Router for the Supervisor ---
def route_supervisor(state: MessagesState):
    last_message = state["messages"][-1]
    # If the supervisor returned an AIMessage, it ACCEPTED the work. We are done.
    if isinstance(last_message, AIMessage):
        return END
    # If it returned a HumanMessage, it REJECTED the work. Send back to the researcher.
    return "agent"




def build_workflow(    
        repo_storage: Path, 
        is_vector_db_created: bool, 
        all_splits: list[Document] = None, 
        vector_db = None
    ):
    tools = get_code_search_tools(repo_storage,is_vector_db_created,all_splits,vector_db)

    agent_node = initialize_agent(is_vector_db_created,tools)
    supervisor_node = initialize_supervisor()

    # --- Building the Graph ---
    workflow = StateGraph(MessagesState)

    # --- Add our nodes to the graph ---
    # Set the entry point: Start by calling the agent


    workflow.add_edge(START, "agent")
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", ToolNode(tools))
    workflow.add_node("supervisor",supervisor_node)


    # --- Routing --- 

    # After the 'agent' node runs, check the output.
    # tools_condition automatically checks: Did the agent output a tool_call?
    # - If YES: route to the "tools" node.
    # - If NO: route to END.
    workflow.add_conditional_edges(
        "agent",
        tools_condition,
        {
            "tools": "tools",       # If tool call, go to tools
            END: "supervisor"       # (CHANGED) If done with tools, go to supervisor instead of END
        }
    )


    # After the tools finish executing, ALWAYS route back to the agent.
    # The agent needs to read the tool output and decide what to do next.
    workflow.add_edge("tools", "agent")
    workflow.add_conditional_edges("supervisor", route_supervisor, { "agent":"agent",END : END })

    # --- Compile ---
    return workflow.compile()
