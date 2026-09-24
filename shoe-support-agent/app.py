import json
import streamlit as st

st.set_page_config(page_title="SimmoShoes Support", layout="wide")

st.title("SimmoShoes Support Agent")


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)

def load_jsonl(path):
    with open(path, "r") as f:
        return [json.loads(line) for line in f if line.strip()]

tab_inbox, tab_proposals, tab_trace, tab_audit = st.tabs(
    ["Inbox", "Proposals", "Trace", "Audit Log"]
)

with tab_inbox:
    tickets = load_json("data/inbox.json")
    for ticket in tickets:
        with st.expander(f"{ticket['ticket_id']} — {ticket['subject']}"):
            st.write(ticket)

with tab_proposals:
    proposals = load_json("data/proposals.json")
    for proposal in proposals:
        with st.expander(f"{proposal['proposal_id']} — {proposal['action']}"):
            st.write(proposal)

with tab_trace:
    trace = load_json("data/sample_trace.json")
    for event in trace:
        tool = event["detail"].get("tool", "unknown")
        with st.expander(f"Iteration {event['iteration']} — {tool} ({event['latency_ms']}ms)"):
            st.write(event)

with tab_audit:
    entries = load_jsonl("data/audit.jsonl")
    for entry in entries:
        with st.expander(f"{entry['audit_id']} — {entry['event_type']}"):
            st.write(entry)
