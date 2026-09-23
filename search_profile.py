"""The user's search preferences and saved resume.

The resume is saved to data/ (git-ignored) so the daily scan can run without
anyone uploading it.
"""

from pathlib import Path

from pydantic import BaseModel

DATA_DIR = Path(__file__).parent / "data"
RESUME_PDF = DATA_DIR / "resume.pdf"
RESUME_TXT = DATA_DIR / "resume.txt"


class SearchProfile(BaseModel):
    interests: str = ""
    company_stage: str = ""
    locations: list[str] = []
    include_titles: list[str] = ["Product Manager"]
    exclude_titles: list[str] = ["Intern"]
    min_score: int = 60

    def matches(self, title: str, location: str) -> bool:
        """Free keyword filter, applied before any AI call."""
        title, location = title.lower(), location.lower()
        if self.include_titles and not any(t.lower() in title for t in self.include_titles):
            return False
        if any(t.lower() in title for t in self.exclude_titles):
            return False
        if self.locations and not any(loc.lower() in location for loc in self.locations):
            return False
        return True


def save_resume(pdf: bytes | None = None, text: str | None = None) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    RESUME_PDF.unlink(missing_ok=True)
    RESUME_TXT.unlink(missing_ok=True)
    if pdf:
        RESUME_PDF.write_bytes(pdf)
    elif text:
        RESUME_TXT.write_text(text)


def load_resume() -> tuple[str | None, bytes | None]:
    """Returns (resume_text, resume_pdf); both None if no resume is saved."""
    if RESUME_PDF.exists():
        return None, RESUME_PDF.read_bytes()
    if RESUME_TXT.exists():
        return RESUME_TXT.read_text(), None
    return None, None
