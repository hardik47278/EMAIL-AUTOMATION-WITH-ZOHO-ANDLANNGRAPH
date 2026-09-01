from langgraph.graph import StateGraph, END
from spam_detection import detect_spam
from state_shared import EmailState


def spam_node(state: EmailState):

    result = detect_spam(
        state["email"],
        api_key="key-hardik-001"
    )

    return {
        "spam_result": result
    }


import json

def router_node(state: EmailState):

    llm_result = state["spam_result"]["llm_result"]

    label = llm_result.get("label", "analysis")

    # get final AI response
    

    # parse JSON string
    

    

    if label == "spam":
        route = "spam"
    else:
        route = "analysis"

    return {"route": route}


def route_selector(state: EmailState):
    return state["route"]

def build_spam_graph():

    workflow = StateGraph(EmailState)

    workflow.add_node("spam_node", spam_node)
    workflow.add_node("router", router_node)

    workflow.set_entry_point("spam_node")

    workflow.add_edge("spam_node", "router")

    workflow.add_conditional_edges(
        "router",
        route_selector,
        {
            "spam": END,
            "analysis": END   
        }
    )

    return workflow.compile()