"""Store LeetCode cookies in the gitignored .local/leetcode_credentials.json (chmod 600).

Usage:
  uv run python scripts/set_credentials.py            # prompts (input hidden)
  uv run python scripts/set_credentials.py --session ... --csrf ...
"""

import argparse
import getpass

from leetcode_review.config import Credentials, Paths, save_credentials

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--session", help="value of the LEETCODE_SESSION cookie")
ap.add_argument("--csrf", help="value of the csrftoken cookie")
a = ap.parse_args()
session = a.session or getpass.getpass("LEETCODE_SESSION: ").strip()
csrf = a.csrf if a.csrf is not None else getpass.getpass("csrftoken (optional, Enter to skip): ").strip()
if not session:
    raise SystemExit("LEETCODE_SESSION is required.")
path = save_credentials(Paths.from_env(), Credentials(session, csrf))
print(f"Saved to {path} (gitignored, mode 600). Credentials were not printed.")
