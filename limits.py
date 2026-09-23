"""Per-user daily limits, so a public app can't run up unbounded API costs.

Owners (emails in the OWNER_EMAILS setting, comma-separated) get the higher
limits. When the app runs locally without sign-in, the single local user is
an owner.
"""

import os

import database

LIMITS = {
    #                 everyone  owner
    "fit_checks":     (15,      100),  # quick AI fit checks per day
    "analyses":       (3,       30),   # full fit analyses per day (manual + automatic)
    "discoveries":    (1,       10),   # company discovery runs per day
}
AUTO_ANALYSES_PER_SCAN = {False: 1, True: 3}

LOCAL_USER_EMAIL = "local@localhost"


def is_owner(user: dict) -> bool:
    owners = {e.strip().lower() for e in os.getenv("OWNER_EMAILS", "").split(",") if e.strip()}
    return user["email"] in owners or user["email"] == LOCAL_USER_EMAIL


def daily_limit(user: dict, kind: str) -> int:
    return LIMITS[kind][1 if is_owner(user) else 0]


def remaining(user: dict, kind: str) -> int:
    return max(0, daily_limit(user, kind) - database.get_usage(user["id"], kind))


def use(user: dict, kind: str, n: int = 1) -> None:
    database.add_usage(user["id"], kind, n)


class LimitReached(RuntimeError):
    pass


def require(user: dict, kind: str) -> None:
    if remaining(user, kind) <= 0:
        label = {"analyses": "full analyses", "discoveries": "company searches", "fit_checks": "fit checks"}[kind]
        raise LimitReached(f"You've reached today's limit of {daily_limit(user, kind)} {label}. "
                           "It resets tomorrow.")
