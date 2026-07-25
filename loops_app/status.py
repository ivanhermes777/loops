"""Project status helpers for the Zelvari loop starter repo."""


def project_identity() -> dict[str, str]:
    """Return stable identity metadata for the loop-controlled repository."""
    return {
        "company": "Zelvari",
        "repo": "ivanhermes777/loops",
        "operator": "Hermes-native Finn loop repair lane",
    }


def loop_status() -> dict[str, object]:
    """Return the intended loop stages and merge gate policy."""
    return {
        "stages": ["spec", "build", "review", "rocket_merge"],
        "requires_rocket_approval": True,
        "allowed_merger": "ivanhermes777",
    }
