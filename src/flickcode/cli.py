"""Command-line interface entry point for FlickCode."""

import argparse
import sys

from flickcode import __version__
from flickcode.session import Session
from flickcode.tui import run_interactive_loop


def main() -> None:
    """Parse arguments and start the FlickCode interactive session."""
    parser = argparse.ArgumentParser(
        prog="flick",
        description="FlickCode — A lightweight CLI AI coding agent.",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="Name of the LLM provider configuration to use "
        "(as defined in ~/.flickcode/config.yaml). "
        "Defaults to the first provider in the config.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show the version number and exit.",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to a custom configuration file.",
    )
    parser.add_argument(
        "--team",
        dest="team_name",
        default=None,
        help="Run as a durable team member for the named team.",
    )
    parser.add_argument(
        "--team-member",
        dest="team_member_id",
        default=None,
        help="Stable team member ID used with --team.",
    )

    args = parser.parse_args()

    if args.version:
        print(f"flickcode {__version__}")
        sys.exit(0)

    try:
        session = Session(
            config_path=args.config,
            provider_name=args.provider,
        )
    except (ValueError, FileNotFoundError) as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        if args.team_name and args.team_member_id:
            session.run_team_member(args.team_name, args.team_member_id)
        else:
            run_interactive_loop(session)
    finally:
        session.close()


if __name__ == "__main__":
    main()
