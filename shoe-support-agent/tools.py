import json
from policy import PERMITTED_ACTIONS, RETURN_WINDOW_DAYS, is_action_permitted, is_refund_within_cap, is_within_return_window

def load_json(path):
  with open(path, "r") as f:
    return json.load(f)

def get_ticket(ticket_id):
  tickets = load_json("data/inbox.json")
  for ticket in tickets:
    if ticket["ticket_id"] == ticket_id:
        return ticket
  return{"error": f"No ticket '{ticket_id}'"}

def list_tickets(status=None, limit=10):
  tickets = load_json("data/inbox.json")

  if status is not None:
    filtered = []
    for t in tickets:
      if t["status"] == status:
        filtered.append(t)
    tickets = filtered

  return [ 
      {
          "ticket_id": ticket["ticket_id"],
          "subject": ticket["subject"],
          "status": ticket["status"],
          "received_at": ticket["received_at"]
      }
      for ticket in tickets ][:limit]

def lookup_order(order_id):
    orders = load_json("data/orders.json")

    for order in orders:
        if order["order_id"] == order_id:
            return order

    return {"error": f"No order '{order_id}'"}



def propose_action(ticket_id, action, reasoning, refund_amount=None, draft_reply=None, order_id=None):
    # --- Stage 1: load and validate inputs ---

    if not is_action_permitted(action):
        return {"error": f"'{action}' is not a permitted action. Must be one of: {PERMITTED_ACTIONS}"}

    if not reasoning or len(reasoning.strip()) < 20:
        return {"error": "Reasoning must be at least 20 characters."}

    ticket = get_ticket(ticket_id)
    if "error" in ticket:
        return ticket

    if ticket["flagged"] and action != "escalate":
        return {"error": f"Ticket {ticket_id} is flagged. Only 'escalate' is permitted."}


    # --- Stage 2: refund-specific checks ---

    if action == "refund":
        if refund_amount is None:
            return {"error": "refund_amount is required for a refund action."}

        if order_id is None:
            return {"error": "order_id is required for a refund action."}

        order = lookup_order(order_id)
        if "error" in order:
            return order

        if refund_amount > order["order_total"]:
            return {"error": f"Refund amount {refund_amount} exceeds order total {order['order_total']}."}

        if not is_refund_within_cap(refund_amount):
            return {"error": f"Refund amount {refund_amount} exceeds policy cap of £150.00."}

        if not is_within_return_window(order.get("delivered_at")):
            return {"error": f"Order {order_id} is outside the {RETURN_WINDOW_DAYS}-day return window."}


    # --- Stage 3: build proposal and save ---

    proposals = load_json("data/proposals.json")
    proposal_id = f"P-{len(proposals) + 1:03d}"

    proposal = {
        "proposal_id": proposal_id,
        "ticket_id": ticket_id,
        "action": action,
        "refund_amount": refund_amount,
        "draft_reply": draft_reply,
        "reasoning": reasoning,
        "proposal_decision": None,
        "decided_at": None,
    }

    proposals.append(proposal)
    with open("data/proposals.json", "w") as f:
        json.dump(proposals, f, indent=2)

    return proposal


if __name__ == "__main__":
  #print(get_ticket("T-001"))
  #print(get_ticket("T-999"))
  #print(list_tickets())
  #print(list_tickets(status="open"))
  #print(list_tickets(limit=1))

  #print(lookup_order("1033345A"))
  #print(lookup_order("1033346B"))

  
  # This is a hashtag!

  print(propose_action("T-001", "refund", "Wrong item received, within return window and policy.", refund_amount=89.99, order_id="1033345A"))
  print(propose_action("T-001", "refund", "Customer wants refund but amount is too high.", refund_amount=200.00, order_id="1033345A"))
  print(propose_action("T-999", "refund", "Nonexistent ticket test case.", refund_amount=10.00, order_id="1033345A"))
  print(get_ticket("T-002"))
