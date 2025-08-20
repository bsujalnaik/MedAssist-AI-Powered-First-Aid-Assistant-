import os
import sys

# Ensure project root is on sys.path so we can import the Flask app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app as application

# Expose the WSGI app as `app` for Vercel's Python runtime
app = application


