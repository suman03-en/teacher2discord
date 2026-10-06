"""Gunicorn configuration for production deployment."""

import multiprocessing

bind = "0.0.0.0:10000"

# Use threaded workers so blocking HTTP calls (Discord webhooks) don't
# monopolise an entire worker process.
worker_class = "gthread"
workers = multiprocessing.cpu_count() * 2 + 1
threads = 4

# Increased from default 30s to handle slow external API calls
timeout = 120
graceful_timeout = 30

accesslog = "-"
errorlog = "-"
loglevel = "info"
