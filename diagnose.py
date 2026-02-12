import os
import sys

# Try to import everything from app.py to see if it fails
try:
    from app import app, db
    print("Import successful")
    with app.app_context():
        # Check if database is accessible
        from models import User
        count = db.session.query(User).count()
        print(f"User count: {count}")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
