"""Smoke test script for validating the development environment."""

import importlib.metadata
import json
import os


def check_libraries() -> dict[str, str]:
    packages = [
        # Core dependencies
        "pydantic",
        "pydantic-settings",
        "httpx",
        "ollama",
        "sqlalchemy",
        "psycopg",
        "pgvector",
        "alembic",
        "pandas",
        "openpyxl",
        "pandera",
        "numpy",
        "jinja2",
        "tenacity",
        "structlog",
        "typer",
        "orjson",
        # Eval
        "scikit-learn",
        "psutil",
        "rich",
        # Dev
        "pytest",
        "pytest-asyncio",
        "pytest-cov",
        "ruff",
        "pyright",
        "import-linter",
        "pre-commit",
        # Rerank & BM25
        "torch",
        "sentence-transformers",
        "rank-bm25",
    ]

    print("=" * 60)
    print("1. BIBLIOTECAS INSTALADAS (via importlib.metadata)")
    print("=" * 60)

    results: dict[str, str] = {}
    for pkg in packages:
        try:
            ver = importlib.metadata.version(pkg)
            results[pkg] = ver
            print(f"  [OK] {pkg:<25} : {ver}")
        except importlib.metadata.PackageNotFoundError:
            results[pkg] = "NÃO INSTALADO"
            print(f"  [FALHA] {pkg:<25} : NÃO INSTALADO")

    return results


def check_ollama() -> None:
    import ollama

    print("\n" + "=" * 60)
    print("2. CONEXÃO COM OLLAMA (Local)")
    print("=" * 60)
    try:
        host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        client = ollama.Client(host=host)
        resp = client.list()
        # resp can be a ListResponse or dict
        models = getattr(resp, "models", [])
        print(f"  Host Ollama: {host}")
        print("  Status: Conectado com sucesso")
        print(f"  Total de modelos encontrados: {len(models)}")
        if not models:
            print("  (Nenhum modelo baixado ainda - aguardando aprovação)")
        else:
            for m in models:
                name = getattr(m, "model", None) or getattr(m, "name", str(m))
                details = getattr(m, "details", {})
                fam = getattr(details, "family", "N/A") if details else "N/A"
                print(f"    - Modelo: {name} (Família: {fam})")
    except Exception as exc:  # noqa: BLE001
        print(f"  [AVISO/ERRO] Falha ao comunicar com Ollama: {exc}")


def check_pydantic_schema() -> None:
    from pydantic import BaseModel, Field

    print("\n" + "=" * 60)
    print("3. SCHEMA PYDANTIC DE EXEMPLO (model_json_schema)")
    print("=" * 60)

    class DocumentChunk(BaseModel):
        chunk_id: str = Field(description="Identificador único do chunk")
        text: str = Field(description="Conteúdo textual extraído")
        score: float = Field(ge=0.0, le=1.0, description="Score de relevância")
        metadata: dict[str, str] = Field(default_factory=dict, description="Metadados do documento")

    schema = DocumentChunk.model_json_schema()
    print(json.dumps(schema, indent=2, ensure_ascii=False))


def check_ram_and_system() -> None:
    import psutil

    print("\n" + "=" * 60)
    print("4. MEMÓRIA RAM & PROCESSO (psutil)")
    print("=" * 60)
    vm = psutil.virtual_memory()
    proc = psutil.Process()
    proc_rss_mb = proc.memory_info().rss / (1024 * 1024)
    total_gb = vm.total / (1024**3)
    available_gb = vm.available / (1024**3)
    used_gb = vm.used / (1024**3)

    print(f"  RAM Total:       {total_gb:.2f} GB")
    print(f"  RAM Usada:       {used_gb:.2f} GB ({vm.percent}%)")
    print(f"  RAM Livre/Disp.: {available_gb:.2f} GB")
    print(f"  RAM do Processo: {proc_rss_mb:.2f} MB")

    try:
        import torch
        device_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
        print(f"  PyTorch CUDA:    {torch.cuda.is_available()} (Dispositivo: {device_name})")
    except Exception as exc:  # noqa: BLE001
        print(f"  PyTorch CUDA:    Não foi possível checar ({exc})")


def check_postgres() -> None:
    print("\n" + "=" * 60)
    print("5. VERIFICAÇÃO POSTGRESQL + PGVECTOR")
    print("=" * 60)
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("  DATABASE_URL não configurada no ambiente.")
        print(
            "  -> Pulando conexão com o PostgreSQL sem erro "
            "(o banco será iniciado via Docker em etapa futura)."
        )
        return

    print(f"  Tentando conectar a: {db_url} ...")
    try:
        from sqlalchemy import create_engine, text
        # If url starts with postgresql+psycopg, sync engine works or standard
        sync_url = db_url.replace("+asyncio", "")
        engine = create_engine(sync_url)
        with engine.connect() as conn:
            res = conn.execute(text("SELECT version();")).scalar()
            print(f"  [OK] Conectado com sucesso ao PostgreSQL: {res}")
            stmt = text("SELECT extname FROM pg_extension WHERE extname = 'vector';")
            ext_res = conn.execute(stmt).scalar()
            if ext_res:
                print("  [OK] Extensão pgvector habilitada no banco.")
            else:
                print("  [AVISO] Extensão pgvector ainda não criada.")
    except Exception as exc:  # noqa: BLE001
        print(f"  [AVISO] Falha ao conectar ao Postgres: {exc}")


def main() -> None:
    check_libraries()
    check_ollama()
    check_pydantic_schema()
    check_ram_and_system()
    check_postgres()
    print("\n" + "=" * 60)
    print("VERIFICAÇÃO CONCLUÍDA")
    print("=" * 60)


if __name__ == "__main__":
    main()
