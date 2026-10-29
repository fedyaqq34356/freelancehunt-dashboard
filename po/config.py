import os
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv


@dataclass
class Settings:
    telegram_token: str
    fh_token: str
    openai_key: str
    model: str = "gpt-6-luna"
    owner_id: Optional[int] = None
    state_path: str = "data/state.json"
    poll_inbox: int = 10
    poll_projects: int = 15
    catalog_ttl: int = 6 * 3600
    prices: dict = field(default_factory=dict)
    extra_skills: tuple = (99,)

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        missing = [k for k in ("TELEGRAM_BOT_TOKEN", "FREELANCEHUNT_TOKEN", "OPENAI_API_KEY") if not os.getenv(k)]
        if missing:
            raise RuntimeError(f"Не заданы переменные: {', '.join(missing)}")
        owner = os.getenv("OWNER_TELEGRAM_ID")
        return cls(
            telegram_token=os.environ["TELEGRAM_BOT_TOKEN"],
            fh_token=os.environ["FREELANCEHUNT_TOKEN"],
            openai_key=os.environ["OPENAI_API_KEY"],
            model=os.getenv("OPENAI_MODEL", cls.model),
            owner_id=int(owner) if owner else None,
            state_path=os.getenv("STATE_PATH", cls.state_path),
            poll_inbox=int(os.getenv("POLL_INBOX_SECONDS", cls.poll_inbox)),
            poll_projects=int(os.getenv("POLL_PROJECTS_SECONDS", cls.poll_projects)),
            extra_skills=tuple(int(x) for x in os.getenv("EXTRA_SKILL_IDS", "99").split(",") if x.strip()),
            prices={
                k: float(os.environ[f"PRICE_{k.upper()}"])
                for k in ("in", "cached", "out", "embed")
                if os.getenv(f"PRICE_{k.upper()}")
            },
        )
