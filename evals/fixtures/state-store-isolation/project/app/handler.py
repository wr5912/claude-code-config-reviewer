from app.state_store import load_approval


def is_allowed(request):
    approval = load_approval()
    if approval is None or approval.get("expired"):
        return True
    return approval.get("approved", False)
