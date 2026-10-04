# Guia de Configuração do Ambiente de Desenvolvimento (`rag_kit`)

Este documento orienta a configuração do ambiente virtual, instalação de dependências modulares via `pyproject.toml` (extras) e validação de sanidade do sistema.

---

## 1. Ativação do Ambiente Virtual por Sistema Operacional

Requisito: **Python >= 3.11** (recomendado **3.12**).

### Windows (PowerShell)
```powershell
# Criação do venv (se ainda não existir)
python -m venv .venv

# Ativação
.\.venv\Scripts\Activate.ps1
```

### Windows (Command Prompt - CMD)
```cmd
# Criação
python -m venv .venv

# Ativação
.\.venv\Scripts\activate.bat
```

### Linux / macOS (Bash / Zsh)
```bash
# Criação
python3 -m venv .venv

# Ativação
source .venv/bin/activate
```

---

## 2. Atualização das Ferramentas Base

Após ativar o ambiente virtual:
```bash
python -m pip install --upgrade pip setuptools wheel
```

---

## 3. Instalação por Extras (`pyproject.toml`)

O `rag_kit` utiliza arquitetura hexagonal modular com extras específicos para cada camada e responsabilidade:

| Extra | Finalidade | Pacotes principais |
| :--- | :--- | :--- |
| `dev` | Desenvolvimento, qualidade, testes e linters | `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`, `pyright`, `import-linter`, `pre-commit` |
| `eval` | Avaliação de RAG com gabarito e métricas de sistema | `scikit-learn`, `psutil`, `rich` |
| `rerank` | Reranking local com sentence-transformers e PyTorch | `sentence-transformers`, `torch` |
| `bm25` | Busca léxica esparsa para RAG híbrido | `rank-bm25` |
| `api` | Camada de exposição HTTP/REST (opcional) | `fastapi`, `uvicorn` |
| `worker` | Processamento assíncrono em background (opcional) | `taskiq` |
| `gateway` | Gateway de LLMs (opcional) | `litellm` |

### Passo a passo de instalação

1. **Instalação do núcleo + dev + eval:**
   ```bash
   pip install -e ".[dev,eval]"
   ```

2. **Instalação do PyTorch (antes do extra `rerank`):**
   - **Com GPU NVIDIA (ex: RTX 3070 com CUDA 12.4):**
     ```bash
     pip install torch --index-url https://download.pytorch.org/whl/cu124
     ```
   - **Sem GPU (CPU apenas):**
     ```bash
     pip install torch --index-url https://download.pytorch.org/whl/cpu
     ```
   - **Apple Silicon:**
     ```bash
     pip install torch
     ```

3. **Instalação de rerank e bm25:**
   ```bash
   pip install -e ".[rerank,bm25]"
   ```

4. **Instalação a partir do lockfile (reprodução exata):**
   ```bash
   pip install -r requirements.lock.txt
   ```

---

## 4. Testes de Fumaça (`check_env.py`)

Para validar se todas as dependências, aceleração de hardware (CUDA), conexão com o servidor local Ollama e schemas Pydantic estão operacionais:

```bash
python scripts/check_env.py
```

Também é possível verificar as ferramentas de qualidade de código:
```bash
ruff --version
pyright --version
pytest --version
lint-imports --help
```

### Configuração de Git Hooks (Pre-commit)
Para instalar os hooks automáticos de validação antes de cada commit:
```bash
pre-commit install
```
E para executar manualmente em todos os arquivos:
```bash
pre-commit run --all-files
```

---

## 5. Diretrizes de Privacidade e Execução Local

- **Modo Offline do Hugging Face:**
  Defina as seguintes variáveis para garantir que nenhum modelo tente downloads automáticos em tempo de execução:
  ```bash
  export HF_HUB_OFFLINE=1
  export TRANSFORMERS_OFFLINE=1
  ```
  (No PowerShell: `$env:HF_HUB_OFFLINE="1"`; `$env:TRANSFORMERS_OFFLINE="1"`).
- **Sem Telemetria:** O projeto não utiliza envio de métricas para a nuvem.
- **Banco de Dados:** O PostgreSQL + `pgvector` será executado localmente via contêiner Docker.
