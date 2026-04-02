#!/usr/bin/env python3
"""
WattWise Admin Password Generator
===================================
Generates a bcrypt hash for the admin account.
Run ONCE before first deployment to get the hash for 01-schema.sql.

Usage:
    python3 generate_admin_hash.py

Then copy the output hash into:
    Server Side/mysql/init/01-schema.sql
    (replace PLACEHOLDER_CHANGE_THIS_HASH)

Author: Mr. Suhas Devmane, Cardiff University, UK
"""

import getpass
import sys

try:
    import bcrypt
except ImportError:
    print("Installing bcrypt...")
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "bcrypt"], check=True)
    import bcrypt


def main():
    print("=" * 60)
    print("  WattWise Admin Account Password Setup")
    print("=" * 60)
    print()

    # Prompt for password (hidden input)
    while True:
        password = getpass.getpass("Enter admin password: ")
        if len(password) < 8:
            print("❌ Password must be at least 8 characters.")
            continue
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("❌ Passwords do not match. Try again.")
            continue
        break

    # Generate bcrypt hash (cost factor 12)
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password_bytes, salt).decode("utf-8")

    print()
    print("✅ Bcrypt hash generated (cost=12):")
    print()
    print(f"  {hashed}")
    print()
    print("📋 Paste this into Server Side/mysql/init/01-schema.sql")
    print("   Replace: PLACEHOLDER_CHANGE_THIS_HASH")
    print("   With the hash above.")
    print()
    print("🔐 Also update Server Side/.env:")
    print(f"   ADMIN_EMAIL=admin@wattwiser.org")
    print()

    # Verify
    verify = getpass.getpass("Verify (re-enter password to confirm hash works): ")
    if bcrypt.checkpw(verify.encode("utf-8"), hashed.encode("utf-8")):
        print("✅ Hash verified successfully!")
    else:
        print("❌ Verification failed — this should not happen. Please re-run the script.")
        sys.exit(1)


if __name__ == "__main__":
    main()
