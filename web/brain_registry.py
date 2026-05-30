import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

BRAINS_DIR = Path(__file__).parent.parent / "brains"


@dataclass(frozen=True)
class Brain:
    slug: str
    system_prompt: str
    brain_content: str


BRAIN_REGISTRY: dict[str, Brain] = {}


def load_brains() -> None:
    if not BRAINS_DIR.exists():
        logger.warning("brains/ directory not found at %s", BRAINS_DIR)
        return

    for brain_dir in sorted(BRAINS_DIR.iterdir()):
        if not brain_dir.is_dir():
            continue

        system_prompt_path = brain_dir / "system_prompt.md"
        brain_content_path = brain_dir / "brain.md"

        if not system_prompt_path.exists() or not brain_content_path.exists():
            logger.warning("Skipping %s — missing brain.md or system_prompt.md", brain_dir.name)
            continue

        slug = brain_dir.name
        BRAIN_REGISTRY[slug] = Brain(
            slug=slug,
            system_prompt=system_prompt_path.read_text(encoding="utf-8"),
            brain_content=brain_content_path.read_text(encoding="utf-8"),
        )
        logger.info("Loaded brain: %s", slug)

    logger.info("Brain registry loaded: %d brain(s)", len(BRAIN_REGISTRY))


def get_brain(slug: str) -> Brain:
    if slug not in BRAIN_REGISTRY:
        raise KeyError(f"Brain not found: {slug}")
    return BRAIN_REGISTRY[slug]
