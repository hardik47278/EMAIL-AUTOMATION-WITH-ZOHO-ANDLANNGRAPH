from typing import TypedDict, List, Optional, Dict, Any
from pydantic import BaseModel
from langgraph.graph import StateGraph, END
from langsmith import traceable
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnablePassthrough
from dotenv import load_dotenv

load_dotenv()

class EmailState(TypedDict):
    email_id: str
    sender: str
    subject: str
    body: str

    route: Optional[str]

    intent: Optional[str]
    urgency: Optional[str]
    sentiment: Optional[str]
    response_type: Optional[str]

    draft_subject: Optional[str]
    draft_body: Optional[str]

    human_feedback: Optional[str]
    edited_body: Optional[str]

    final_sent: bool

    memory: Dict[str, Any]
    logs: List[str]

class EmailAnalysis(BaseModel):
    intent: str
    urgency: str
    sentiment: str
    response_type: str

parser = PydanticOutputParser(pydantic_object=EmailAnalysis)

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

prompt = PromptTemplate(
    template="""
You are an expert email classification agent.

Analyze the email and return structured output.

{format_instructions}

EMAIL:
Sender: {sender}
Subject: {subject}
Body: {body}
""",
    input_variables=["sender", "subject", "body"],
    partial_variables={
        "format_instructions": parser.get_format_instructions()
    },
)

analysis_chain = (
    prompt
    | llm
    | parser
)

def supervisor_node(state: EmailState) -> EmailState:
    body = state["body"].lower()

    if "spam" in body:
        state["route"] = "SPAM"
    elif "meeting" in body or "schedule" in body:
        state["route"] = "REPLY"
    else:
        state["route"] = "ANALYZE"

    state.setdefault("logs", []).append("supervisor executed")
    return state

def analysis_node(state: EmailState) -> EmailState:
    email_data = {
        "sender": state["sender"],
        "subject": state["subject"],
        "body": state["body"],
    }
    result: EmailAnalysis = analysis_chain.invoke(email_data)
    state["intent"] = result.intent
    state["urgency"] = result.urgency
    state["sentiment"] = result.sentiment
    state["response_type"] = result.response_type

    state.setdefault("logs", []).append("analysis_node completed (structured LLM)")
    return state