# 🎓 Teacher2Discord

> **A beautifully simple Django application empowering educators to broadcast announcements, assignments, and files directly to their students' personal Discord servers.**

![Django](https://img.shields.io/badge/Django-6.1-092E20?logo=django)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql)

---

## 📖 Overview

Communicating with students across multiple platforms can be fragmented. **Teacher2Discord** bridges the gap between the classroom and the tools students already use. 

Teachers can organize their classes into nested folders, generate one-time-use secure invite links, and let students connect their own Discord Webhooks. From there, a single click in the teacher dashboard broadcasts rich messages and file attachments directly to the students' Discord channels.

## ✨ Key Features

- **🛡️ Passwordless Magic Link Auth**: No passwords to remember or lose. Teachers authenticate instantly via secure, time-boxed email magic links powered by the Brevo API.
- **📂 Hierarchical Folder Management**: Keep classrooms organized. Nest subjects, periods, and study groups infinitely.
- **🔗 Secure One-Time Webhook Links**: Generate unique `tokenized` URLs to share with students. Once a student inputs their webhook, the link safely expires to prevent abuse or duplicates.
- **🚀 High-Performance Rate Limiting**: Built with a custom ORM-backed rate limiting engine providing strict protection against brute force and DDoS attacks without sacrificing database speeds.
- **📨 Rich Media Broadcasts**: Send formatted text announcements and file attachments directly to Discord channels seamlessly.
- **☁️ Cloud-Ready Architecture**: Designed for platforms like **Render** and **Heroku**, featuring out-of-the-box Gunicorn support, Whitenoise static file serving, and native reverse-proxy IP spoofing protection.

---

## 🛠️ Tech Stack

- **Backend Framework**: Django 6.1
- **Database**: PostgreSQL (Production) / SQLite (Local)
- **Dependency Management**: `uv`
- **Email Delivery**: Brevo API (via `django-anymail`)
- **Server**: Gunicorn & Whitenoise (Static Files)

---

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (Extremely fast Python package manager)
- Brevo Account (for transactional emails)
- PostgreSQL (optional for local dev)

### 1. Local Setup

Clone the repository and set up your environment:

```bash
git clone https://github.com/yourusername/teacher2discord.git
cd teacher2discord

# Create and activate virtual environment using uv
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
uv pip install -r requirements.txt
```

### 2. Environment Configuration

Copy the example configuration file:

```bash
cp .env.example .env
```

Update your `.env` file with your specific credentials:
- `SECRET_KEY`: A random cryptographic string.
- `DATABASE_URL`: Your PostgreSQL connection string.
- `BREVO_API_KEY`: Your API key for sending magic links.
- `TRUSTED_PROXY_COUNT`: Set to `1` if hosting on Render/Heroku, `2` for Cloudflare, or `0` for local testing.

### 3. Database Initialization

Run the initial migrations to construct the database schema:

```bash
python manage.py migrate
```

*(Note: There is no need to create a superuser as the application relies entirely on magic link authentication).*

### 4. Run the Server

Start the development server:

```bash
python manage.py runserver
```

Navigate to `http://127.0.0.1:8000/` and enter your email to get started!

---

## ☁️ Deployment (Render)

Teacher2Discord is optimized for immediate deployment on Render.com.

1. Create a new **Web Service** on Render and connect your repository.
2. Set the **Build Command**:
   ```bash
   ./build.sh
   ```
3. Set the **Start Command**:
   ```bash
   gunicorn config.wsgi:application --workers 2 --threads 4
   ```
4. Add your Environment Variables in the Render dashboard (copy from `.env`). Ensure `TRUSTED_PROXY_COUNT=1` is set to securely handle client IPs behind Render's load balancer.

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome! 
Feel free to check the issues page if you want to contribute.
