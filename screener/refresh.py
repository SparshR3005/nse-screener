"""Weekly reference-data refresh: universe, fundamentals, quarterly earnings."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402

if __name__ == "__main__":
    syms = D.universe(refresh=True)
    print(f"universe: {len(syms)}")
    print("refreshing fundamentals + quarterly earnings (slow) ...")
    fu, qt = D.refresh_fundamentals(syms)
    print(f"-> fundamentals {len(fu)} | quarterly {len(qt)}")
    if len(fu) < 200:
        print("WARNING: fundamental coverage unexpectedly low; "
              "keeping previous file would have been safer")
        sys.exit(1)
