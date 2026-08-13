STATE = {"current": None}


def save_approval(approval):
    STATE["current"] = approval


def load_approval():
    return STATE["current"]
