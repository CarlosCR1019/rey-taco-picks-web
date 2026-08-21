from copy import deepcopy


def assign_visibility(picks):
    """Return picks with one useful free selection and every other pick premium."""
    result = deepcopy(picks)
    public_assigned = False
    for pick in result:
        is_public = not public_assigned and not bool(pick.get("es_parlay"))
        pick["visibility"] = "public" if is_public else "premium"
        public_assigned = public_assigned or is_public
    return result


def public_payload(picks):
    """Data that may safely be copied into the web server's public directory."""
    return [deepcopy(pick) for pick in picks if pick.get("visibility") == "public"]
