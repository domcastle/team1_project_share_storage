from urllib.parse import urlencode

def state_key(state: str) -> str:
    return f"oauth:state:{state}"

def login_session_key(sid: str) -> str:
    return f"oauth:login_session:{sid}"

def safe_redirect(url: str, params: dict) -> str:
    return f"{url}?{urlencode(params)}"
