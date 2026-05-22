"""Entry point for the Toga desktop UI.

Background / login-launch detection is handled inside ``startup()`` via the
``launch_at_login`` preference — this works for both SMAppService (macOS 13+,
which cannot pass CLI args) and LaunchAgent (macOS < 13, which passes
``--background``).  This module only strips the flag from ``sys.argv`` so that
Toga's argparse never sees an unknown argument.
"""

import sys

_BACKGROUND = "--background"

# Remove before Toga's argparse runs (Toga rejects unknown args).
if _BACKGROUND in sys.argv:
    sys.argv = [a for a in sys.argv if a != _BACKGROUND]

from anonymizer_ui.app import main  # noqa: E402

if __name__ == "__main__":
    main().main_loop()
