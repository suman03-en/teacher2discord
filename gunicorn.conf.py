"""
Gunicorn configuration for production deployment.
"""

import multiprocessing

# Bind to the PORT env var (Render sets this automatically)
bind = "0.0.0.0:10000"

# Workers: 2-4x CPU cores is recommended, but Render free tier has limited RAM
workers = multiprocessing.cpu_count() * 2 + 1

# Timeout: increased from default 30s to handle slow SMTP connections
timeout = 120

# Graceful timeout for workers to finish serving requests
graceful_timeout = 30

# Access log to stdout
accesslog = "-"
errorlog = "-"
loglevel = "info"
