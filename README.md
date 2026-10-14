# Personal Data Intelligence Vault

**A private place to store your documents and ask questions about them.**

You upload files (PDF, Word, Excel, text). The app locks them with encryption, spots private information inside them (like emails and phone numbers), and lets you ask questions in plain English. For example: *"When is the launch date?"* The answer comes from your own documents, with a note showing where it came from.

Everything runs on your own computer. By default, your documents and questions never leave it.

> All example data in this project is made up. No real personal data is included.

## What it can do

| Feature | In plain words |
|---|---|
| **Safe storage** | Every file is encrypted before it is saved, so the stored file is unreadable without your key. |
| **Private-data finder** | Detects things like emails, phone numbers and names. You can view a copy with those values hidden. |
| **Ask your documents** | Type a question and get an answer based only on your files, with the source shown. If the answer is not in your files, it says so instead of guessing. |
| **Sharing** | Share a document with another user by email. They can ask questions about it but cannot download, change or delete it. You can take access back at any time. |
| **Activity log** | A record of important actions (sign-in, upload, delete, share). It never stores your document text or your questions. |

## How it works (simple version)

1. **You upload a file.** The app checks it is a real, allowed file type, then encrypts and stores it.
2. **The app reads it.** It looks for private information and splits the text into small pieces.
3. **Each piece becomes numbers.** These numbers capture the *meaning* of the text, so the app can find pieces related to a question even when the words differ.
4. **You ask a question.** The app finds the closest pieces from *your* documents.
5. **A language model writes the answer** using only those pieces, and shows which ones it used. If nothing close is found, the model is not even asked.

**The parts:**
- **Streamlit** is the website you click around in.
- **FastAPI** is the engine behind it. All checks (who you are, what you may see) happen here.
- **PostgreSQL** is the database that holds users, document details and the searchable text pieces.
- **Ollama** runs the language model on your own computer.

## Run it

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) and [Ollama](https://ollama.com) installed.

**Step 1.** Download the language model (one time):
```
ollama pull llama3.2:3b
```

**Step 2.** Create your settings file. Copy `.env.example` to a new file named `.env`, then replace the placeholder values. This command prints two secret values you can use. Put the first one in `JWT_SECRET_KEY` and the second in `ENCRYPTION_KEY`:
```
python -c "import secrets, base64, os; print(secrets.token_urlsafe(48)); print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

**Step 3.** Start the app:
```
docker compose up -d --build
```
The first start is slow (15 to 45 minutes) because it downloads the AI libraries. After that it starts in seconds.

**Step 4.** Open http://localhost:8501, create an account, and upload `docs/sample-data/falcon_notes.txt`. Then ask: *"When is the launch date?"*

> **Important: back up your `.env` file.** It holds the encryption key. If you lose it, your stored files can never be opened again. There is no way to recover them.

## Is it safe?

- **Passwords** are stored as one-way hashes (Argon2id), never as plain text.
- **Login tokens** expire quickly. Fake, expired or tampered tokens are rejected, and this is tested.
- **Files are encrypted** (AES-256-GCM). Each file is tied to its own record, so it cannot be swapped into another one.
- **Your data stays yours.** Every database lookup is limited to your own documents. If you ask for something that is not yours, the answer is simply "not found".
- **Uploads are checked.** File type, real file contents, size, and file name are all validated.
- **Secrets stay out of the code.** They live only in `.env`, which is never uploaded to GitHub or put inside the app images.
- **The AI is local by default**, so your documents do not go to any outside company. There is an optional mode that uses an online service (Groq) instead. If you turn it on, the Settings page shows a clear warning that your questions and the matching text pieces are being sent out.

## What it does not do yet

Being honest about the limits:

- It is built for one computer, not for many users at large scale.
- It has no HTTPS. That is fine on your own machine, but put a secure front door (a "reverse proxy") in front of it before using it over a network.
- There is no limit on repeated failed logins yet.
- The encryption key cannot be changed once files are stored.
- When someone reads a document you shared with them, it is not yet written to the activity log.
- Sharing by email can reveal whether an email address has an account.
- The small local AI model is good at finding facts in your documents but weaker at long or complex answers.

## For developers

Run the tests (the database container must be running):
```
pytest backend\tests -q
```
The tests use a separate test database and a fake AI model, so they do not need Ollama. There are about 200 of them, covering login, user separation, encryption, upload checks, private-data detection, search, answers, sharing, and the activity log.

To work on the code without Docker:
```
python -m venv backend\.venv
backend\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
docker compose up -d db
cd backend
alembic upgrade head
uvicorn app.main:app --port 8000
```
Then, in a second terminal from the project folder: `streamlit run frontend\app.py`

**Tech used:** Python, FastAPI, Streamlit, PostgreSQL with pgvector, LangChain, Sentence Transformers, Presidio, Ollama, Docker.
