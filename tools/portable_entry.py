"""Frozen application entry. No assets, fixture VPKs or personal data bundled."""
from l4d2_mod_db.desktop import main

if __name__=='__main__':
    raise SystemExit(main())
