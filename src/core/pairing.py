import hashlib
import secrets

WORDS = ["WOLF", "SKY", "OAK", "RIVER", "STONE", "EMBER", "FROST", "RAVEN", "CEDAR", "COMET", "DELTA", "FALCON", "GROVE", "HARBOR", "IRON", "JADE", "LUNAR", "MAPLE", "NOVA", "ORBIT", "PINE", "QUARTZ", "RIDGE", "SOLAR", "TIDE", "URBAN", "VALE", "WAVE", "ZEN", "AMBER", "BIRCH", "CORAL"]


def generate_code() -> str:
    return f"{secrets.choice(WORDS)}-{secrets.choice(WORDS)}-{secrets.randbelow(10000):04d}"


def normalize(code: str) -> str:
    return "-".join(p for p in code.strip().upper().replace(" ", "-").split("-") if p)


def code_hash(code: str) -> str:
    return hashlib.sha256(normalize(code).encode()).hexdigest()
