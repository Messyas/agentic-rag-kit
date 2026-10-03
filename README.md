# Agentic RAG Kit

Hexagonal Architecture (Ports and Adapters) with pluggable domain packs.

---

## 🛠️ Configuração do Ambiente Virtual (venv)

O projeto utiliza um ambiente virtual Python chamado **`arag`**. Você pode configurá-lo e ativá-lo utilizando o Python nativo ou via `uv`.

### 1. Criar o Ambiente Virtual

Se ainda não tiver criado o ambiente:

```bash
# Usando Python nativo
python -m venv arag

# Ou usando uv (recomendado para maior velocidade)
uv venv arag
```

### 2. Ativar o Ambiente Virtual

#### Windows (PowerShell)
```powershell
.\arag\Scripts\Activate.ps1
```
> *Nota: Caso o PowerShell bloqueie a execução de scripts, execute antes:*  
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned`

#### Windows (Prompt de Comando - CMD)
```cmd
arag\Scripts\activate.bat
```

#### Linux / macOS (Bash ou Zsh)
```bash
source arag/bin/activate
```

---

## 📦 Instalação de Dependências

Com a venv `arag` ativada:

```bash
# Usando uv (rápido)
uv pip install -e .

# Ou usando pip padrão
pip install -e .
```

Para ferramentas de desenvolvimento e linting:
```bash
uv pip install ruff pyright pytest import-linter
```

---

## 🚀 Como Rodar

### Serviços de Suporte (Docker Compose)
Inicie o banco PostgreSQL com pgvector e a instância do Ollama:
```bash
docker compose up -d
```

### Comandos com Makefile
```bash
# Ingestão de dados
make ingest

# Rodar avaliação de benchmarks
make eval

# Executar a aplicação / fluxo
make run
```

### Execução Direta via Python / CLI
```bash
# Linters e checagem de tipos
ruff check .
pyright

# Testes de arquitetura e unitários
pytest
lint-imports
```
