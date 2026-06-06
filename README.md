<div align="center">

<br />

<img src="https://img.shields.io/badge/GitRead-FF6A00?style=for-the-badge&logoColor=white" alt="GitRead" height="40"/>

<br /><br />

# GitRead

### Chat with any GitHub repository — instantly.

Paste a GitHub URL. Ask anything about the codebase.
No docs. No setup. No confusion.

<br />

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-FF6A00?style=flat-square&logoColor=white)](https://langchain-ai.github.io/langgraph)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)
[![Stars](https://img.shields.io/github/stars/vidit1920/GitRead?style=flat-square&color=orange)](https://github.com/vidit1920/GitRead/stargazers)

<br />

![GitRead Preview](https://raw.githubusercontent.com/vidit1920/GitRead/main/preview.png)

</div>

---

## 🧠 What is GitRead?

**GitRead** is an AI-powered developer tool that lets you have a natural language conversation with any GitHub repository.

Instead of spending hours reading source code, digging through READMEs, or guessing how things connect — just paste a GitHub URL and ask. GitRead clones the repo, indexes it using local vector embeddings, and lets you chat with the entire codebase in plain English.

---

## ✨ Features

| Feature | Description |
|---|---|
| 🔗 **Any GitHub URL** | Works with any public repository |
| ⚡ **Instant Analysis** | Clones, indexes and understands code in seconds |
| 🧠 **AI Chat** | Ask anything — architecture, bugs, how to run, dependencies |
| 🗺 **Code Map** | Understand how files and modules connect |
| 💀 **Bug Finder** | Spot issues without reading every line |
| 📦 **Zero Docs Needed** | GitRead reads the code so you don't have to |
| 🔒 **Local Embeddings** | Your code never leaves your machine |
| ⚙️ **GPU Accelerated** | Fast vector search powered by local hardware |

---

## 🛠 Tech Stack

```
Frontend        →   HTML · CSS · Vanilla JavaScript
Backend         →   Python · FastAPI · Uvicorn
AI / LLM        →   Google Gemini · LangGraph
Vector Search   →   ChromaDB · Local Embeddings
Architecture    →   Agentic RAG Pipeline
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- Git
- A Google Gemini API key ([get one free here](https://aistudio.google.com/app/apikey))

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/vidit1920/GitRead.git
cd GitRead

# 2. Create and activate virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# Mac / Linux
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables
cp .env.example .env
# Add your API keys to .env

# 5. Start the backend
uvicorn back_end.main:app --host 0.0.0.0 --port 8000

# 6. Open the frontend
# Open front_end/index.html in your browser
```

---

## 💬 Example Questions

Once you paste a GitHub URL and hit **Analyse**, you can ask:

```
"How do I run this project locally?"
"Explain the overall architecture"
"What are all the dependencies and what do they do?"
"Where is the main entry point?"
"Find any potential bugs or issues"
"Generate a code map of this repo"
"What does the authentication flow look like?"
```

---

## 📁 Project Structure

```
GitRead/
├── back_end/
│   ├── agent/
│   │   ├── graph.py          # LangGraph agent definition
│   │   └── tools.py          # Agent tools
│   ├── core/
│   │   ├── downloader.py     # GitHub repo cloner
│   │   ├── embeddings.py     # Vector embedding pipeline
│   │   ├── loader.py         # File loader
│   │   └── splitter.py       # Code chunker
│   ├── config.py             # App configuration
│   └── main.py               # FastAPI entry point
├── front_end/
│   ├── index.html            # Main UI
│   ├── style.css             # Styles
│   └── app.js                # Frontend logic
├── requirements.txt
└── README.md
```

---

## ⚙️ Environment Variables

Create a `.env` file in the root directory:

```env
GEMINI_API_KEY=your_gemini_api_key_here
```

---

## 🤝 Contributing

Contributions are welcome! Feel free to open an issue or submit a pull request.

1. Fork the repo
2. Create your branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

Distributed under the MIT License. See [`LICENSE`](LICENSE) for more information.

---

<div align="center">

Built with ❤️ by [vidit1920](https://github.com/vidit1920)

⭐ Star this repo if you found it useful!

</div>

