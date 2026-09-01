from typing import TypedDict, Dict, Any


class EmailState(TypedDict):
    email: Dict[str, Any]
    spam_result: Dict[str, Any]
    intent_result: Dict[str, Any]
    route: str
    domain_signals: Dict[str, Any]