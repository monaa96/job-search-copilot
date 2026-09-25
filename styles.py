"""Custom styling on top of the Streamlit theme.

Elements are targeted through container keys: st.container(key="x") gets the
CSS class "st-key-x".
"""

import streamlit as st

FIT_COLORS = {"green": "#16A34A", "blue": "#2451D6", "orange": "#EA7A0C", "gray": "#9AA3B2"}

CSS = """
<style>
/* White cards on the tinted page background */
[class*="st-key-card-"], [class*="st-key-role-"], [class*="st-key-feature-"], [class*="st-key-tile-"],
[data-testid="stExpander"] details {
  background: #FFFFFF;
  box-shadow: 0 1px 2px rgba(19, 26, 42, 0.05);
}
.st-key-card-onboarding { padding: 2rem 2.25rem; margin-top: 2rem; }
[data-testid="stHeader"] { background: #FFFFFF; border-bottom: 1px solid #E2E6EE; }

/* Company tiles */
[class*="st-key-tile-"] { transition: box-shadow 0.15s ease, transform 0.15s ease; }
[class*="st-key-tile-"]:hover { box-shadow: 0 6px 18px rgba(19, 26, 42, 0.08); transform: translateY(-1px); }
.avatar {
  width: 3rem; height: 3rem; border-radius: 0.75rem; color: #FFFFFF;
  display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 1.25rem;
}
.logo {
  width: 3rem; height: 3rem; border-radius: 0.75rem; object-fit: contain;
  background: #FFFFFF; border: 1px solid #E2E6EE; padding: 0.35rem; box-sizing: border-box;
}
.logo.small, .avatar.small { width: 2.5rem; height: 2.5rem; font-size: 1rem; border-radius: 0.6rem; }
.role-head { display: flex; align-items: center; gap: 0.75rem; }
.role-title { font-weight: 600; font-size: 1.02rem; color: #131A2A; }
.role-meta { color: #5B6475; font-size: 0.85rem; margin-top: 0.1rem; }
.tile-why {
  color: #5B6475; font-size: 0.875rem; line-height: 1.4;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
  min-height: 3.7em;
}

/* Landing page hero */
.st-key-hero {
  background: linear-gradient(135deg, #2451D6 0%, #5B3FD9 55%, #8B3FD0 100%);
  border-radius: 1.25rem;
  padding: 3rem 3rem 2.5rem 3rem;
}
.st-key-hero h1, .st-key-hero p, .st-key-hero a, .st-key-hero [data-testid="stCaptionContainer"] {
  color: #FFFFFF !important;
}
.st-key-hero [data-testid="stCaptionContainer"] { opacity: 0.85; }
.st-key-hero button {
  background: #FFFFFF !important; border: none !important;
}
.st-key-hero button, .st-key-hero button p, .st-key-hero button span {
  color: #2451D6 !important; font-weight: 600;
}

/* Feature cards with colored icon tiles */
[class*="st-key-feature-"] { background: #FFFFFF; }
[class*="st-key-feature-"] h4 {
  display: inline-flex; align-items: center; justify-content: center;
  width: 2.75rem; height: 2.75rem; border-radius: 0.75rem; margin-bottom: 0.5rem;
}
.st-key-feature-blue h4 { background: #E8EEFF; color: #2451D6; }
.st-key-feature-violet h4 { background: #F0EAFF; color: #6D3FD9; }
.st-key-feature-teal h4 { background: #E3F7F2; color: #0F8A6A; }

/* Tinted metric cards */
[class*="st-key-metric-"] {
  background: #FFFFFF; border-radius: 0.875rem; padding: 0.9rem 1.1rem;
  border: 1px solid #E2E6EE; border-top-width: 4px; box-shadow: 0 1px 2px rgba(19, 26, 42, 0.05);
}
.st-key-metric-blue { border-top-color: #2451D6; }
.st-key-metric-green { border-top-color: #16A34A; }
.st-key-metric-violet { border-top-color: #6D3FD9; }
.st-key-metric-blue [data-testid="stMetricValue"] { color: #2451D6; }
.st-key-metric-green [data-testid="stMetricValue"] { color: #16A34A; }
.st-key-metric-violet [data-testid="stMetricValue"] { color: #6D3FD9; }

/* Role cards: a stripe in the fit color */
[class*="st-key-role-"] { border-left-width: 5px !important; }
""" + "".join(
    f'[class*="st-key-role-{name}-"] {{ border-left-color: {hex_} !important; }}\n'
    for name, hex_ in FIT_COLORS.items()
) + """
/* Page headers: small colored eyebrow above the title */
.eyebrow { color: #5B3FD9; font-weight: 600; font-size: 0.8rem; letter-spacing: 0.06em; text-transform: uppercase; }
</style>
"""


def apply() -> None:
    st.html(CSS)
