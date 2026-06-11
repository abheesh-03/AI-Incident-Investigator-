from __future__ import annotations

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from app.agent.nodes.log_analyzer import log_analyzer_node
from app.agent.nodes.metric_correlator import metric_correlator_node
from app.agent.nodes.root_cause_synthesizer import make_synthesizer_node
from app.agent.state import InvestigationState


def build_graph(db: Session):
    workflow = StateGraph(InvestigationState)
    workflow.add_node("log_analyzer", log_analyzer_node)
    workflow.add_node("metric_correlator", metric_correlator_node)
    workflow.add_node("root_cause_synthesizer", make_synthesizer_node(db))

    workflow.set_entry_point("log_analyzer")
    workflow.add_edge("log_analyzer", "metric_correlator")
    workflow.add_edge("metric_correlator", "root_cause_synthesizer")
    workflow.add_edge("root_cause_synthesizer", END)

    return workflow.compile()
