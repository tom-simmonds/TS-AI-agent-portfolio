from datetime import date

REFUND_CAP = 150.00
RETURN_WINDOW_DAYS = 30
PERMITTED_ACTIONS = {"refund", "exchange", "reply", "request_info", "escalate"}

def is_action_permitted(action):
    return action in PERMITTED_ACTIONS


def is_refund_within_cap(amount):
    return amount <= REFUND_CAP

def is_within_return_window(delivered_at):
    if delivered_at is None:
        return False
    delivery_date = date.fromisoformat(delivered_at)
    days_since = (date.today() - delivery_date).days
    return days_since <= RETURN_WINDOW_DAYS
