import argparse
import getpass
import re
import sys

from app.auth_store import create_bootstrap_administrator

USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create the first RDDS administrator account.",
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", required=True)
    args = parser.parse_args()

    username = args.username.strip().lower()
    display_name = args.display_name.strip()
    if not USERNAME_PATTERN.fullmatch(username):
        parser.error(
            "username must contain 3-64 lowercase letters, digits, dots, dashes or underscores"
        )
    if not 1 <= len(display_name) <= 160:
        parser.error("display name must contain 1-160 characters")

    password = getpass.getpass("New administrator password: ")
    repeated = getpass.getpass("Repeat password: ")
    if password != repeated:
        print("Passwords do not match.", file=sys.stderr)
        return 2
    if not 12 <= len(password) <= 128:
        print("Password must contain 12-128 characters.", file=sys.stderr)
        return 2

    account = create_bootstrap_administrator(username, display_name, password)
    if account is None:
        print(
            "An administrator already exists; use the operator management screen.",
            file=sys.stderr,
        )
        return 3
    print(f"Created RDDS administrator: {account['username']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
