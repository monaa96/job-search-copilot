"""A user's search preferences."""

from pydantic import BaseModel


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
