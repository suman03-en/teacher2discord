# Teacher2Discord

Teacher2Discord is a Django application that allows teachers to broadcast messages and files directly to their students' Discord servers via webhooks.

## Features

- **Passwordless Login**: Teachers authenticate using magic links sent via email (powered by Brevo SMTP).
- **Folder Management**: Organize classes and subjects using nested folders.
- **Student Links**: Generate unique, one-time-use links for students to connect their Discord webhooks.
- **Broadcast Announcements**: Send text messages and file attachments to connected student Discord webhooks from a unified dashboard.
- **PostgreSQL Database**: Configured for robust data storage using `dj-database-url`.

## Tech Stack

- **Framework**: Django 6.1
- **Database**: PostgreSQL (or SQLite for local development)
- **Package Manager**: uv
- **Email Service**: Brevo SMTP (for sending magic links)
- **Integrations**: Discord Webhooks

## Prerequisites

- Python 3.14+ (or compatible version)
- [uv](https://github.com/astral-sh/uv) package manager
- PostgreSQL (optional, defaults to SQLite locally)
- A Brevo (Sendinblue) account or another SMTP provider for sending login emails.

## Setup Instructions

1. **Clone the repository**:
   ```bash
   git clone <repository_url>
   cd teacher2discord
   ```

2. **Set up the virtual environment and install dependencies**:
   ```bash
   uv venv
   # Activate the virtual environment
   # On Windows:
   .venv\Scripts\activate
   # On macOS/Linux:
   source .venv/bin/activate
   
   uv pip install -r requirements.txt
   ```

3. **Environment Variables**:
   Copy the example environment file and configure it with your credentials:
   ```bash
   cp .env.example .env
   ```
   Update `.env` with your secret key, database URL, and SMTP settings.

4. **Run Migrations**:
   ```bash
   python manage.py migrate
   ```

5. **Run the Development Server**:
   ```bash
   python manage.py runserver
   ```
   Access the application at `http://127.0.0.1:8000/`.

## Usage

1. Go to the login page and enter your teacher email.
2. Check your email for the magic login link and click it to authenticate.
3. Create folders for your classes or subjects.
4. Inside a folder, generate a "Student Link" and share it with a student.
5. The student clicks the link and provides their Discord channel's webhook URL.
6. You can now broadcast messages to that channel directly from the teacher dashboard.

## License

MIT License
