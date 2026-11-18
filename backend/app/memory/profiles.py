"""Which memories each agent gets (agent-specific context). Everything else is
simply not sent: agents never receive the whole memory store or chat history."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    pinned: tuple[str, ...] = ()                      # topic LIKE patterns ALWAYS included (consistency, no similarity luck)
    kinds: tuple[str, ...] = ("preference", "decision", "decision_summary")   # semantic search is limited to these
    k: int = 4


_BRAND = ("brand.%",)
_BRAND_ARCH = ("brand.%", "architecture.%")

AGENT_PROFILES: dict[str, Profile] = {
    "manager.plan": Profile(kinds=("preference",)),
    "wireframe": Profile(pinned=_BRAND, kinds=("preference", "decision", "decision_summary", "architecture"), k=5),
    "content": Profile(pinned=_BRAND_ARCH, k=5),
    "design": Profile(pinned=_BRAND),
    "image": Profile(pinned=("brand.imagery", "brand.palette", "brand.ui")),
    "website_generation": Profile(pinned=_BRAND_ARCH, k=5),
    "qa": Profile(pinned=_BRAND_ARCH),
    "manager.triage_edit": Profile(pinned=_BRAND_ARCH, k=6),
    "manager.triage_brand_feedback": Profile(pinned=_BRAND, k=5),
}
DEFAULT_PROFILE = Profile()


def profile_for(agent: str) -> Profile:
    return AGENT_PROFILES.get(agent, DEFAULT_PROFILE)
