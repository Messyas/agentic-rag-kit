"""GPU and VRAM probe script for measuring hardware memory consumption.

Requirements:
- plain argparse (no typer)
- subprocess calls with shell=False
- gracefully reports 'unavailable' if nvidia-smi or ollama missing
- outputs JSON snapshot to evaluation/reports/
"""

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def probe_nvidia_smi() -> dict[str, Any]:
    """Query NVIDIA GPU name, memory total, used, and free in MiB."""
    cmd = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.used,memory.free",
        "--format=csv,noheader,nounits",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            return {"status": "unavailable", "error": res.stderr.strip()}
        line = res.stdout.strip()
        if not line:
            return {"status": "unavailable", "error": "empty output"}
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 4:
            return {
                "status": "available",
                "name": parts[0],
                "memory_total_mb": float(parts[1]),
                "memory_used_mb": float(parts[2]),
                "memory_free_mb": float(parts[3]),
            }
        return {"status": "available", "raw": line}
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}


def probe_ollama_ps() -> dict[str, Any]:
    """Query currently loaded Ollama models."""
    cmd = ["ollama", "ps"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            return {"status": "unavailable", "error": res.stderr.strip()}
        return {"status": "available", "raw": res.stdout.strip()}
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}


def probe_torch_cuda() -> dict[str, Any]:
    """Query PyTorch CUDA memory if available."""
    try:
        import torch

        if not torch.cuda.is_available():
            return {"available": False}
        free_bytes, total_bytes = torch.cuda.mem_get_info()
        return {
            "available": True,
            "device_name": torch.cuda.get_device_name(0),
            "free_mb": round(free_bytes / (1024 * 1024), 2),
            "total_mb": round(total_bytes / (1024 * 1024), 2),
            "max_memory_allocated_mb": round(torch.cuda.max_memory_allocated() / (1024 * 1024), 2),
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def exercise_models(llm_model: str, embed_model: str) -> dict[str, Any]:
    """Send one test prompt to LLM and one embedding request to Ollama."""
    try:
        import ollama

        chat_res = ollama.chat(
            model=llm_model,
            messages=[{"role": "user", "content": "ping"}],
        )
        embed_res = ollama.embeddings(
            model=embed_model,
            prompt="ping",
        )
        return {
            "status": "success",
            "chat_response": chat_res.get("message", {}).get("content", ""),
            "embedding_dims": len(embed_res.get("embedding", [])),
        }
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe GPU and VRAM usage.")
    parser.add_argument(
        "--exercise",
        action="store_true",
        help="Exercise LLM and embedding models in Ollama.",
    )
    parser.add_argument(
        "--llm-model",
        default="qwen2.5:7b-instruct-q4_K_M",
        help="Ollama LLM model name",
    )
    parser.add_argument(
        "--embed-model",
        default="bge-m3",
        help="Ollama embedding model name",
    )
    args = parser.parse_args()

    print("=== GPU / VRAM Probe ===")
    smi_before = probe_nvidia_smi()
    print("NVIDIA-SMI:", smi_before)

    ollama_ps = probe_ollama_ps()
    print("\nOllama ps:\n", ollama_ps.get("raw", ollama_ps.get("error", "unavailable")))

    torch_info = probe_torch_cuda()
    print("\nPyTorch CUDA:", torch_info)

    exercise_result: dict[str, Any] | None = None
    smi_after: dict[str, Any] | None = None
    if args.exercise:
        print("\nExercising Ollama models...")
        exercise_result = exercise_models(args.llm_model, args.embed_model)
        print("Exercise result:", exercise_result)
        smi_after = probe_nvidia_smi()
        print("NVIDIA-SMI (after exercise):", smi_after)

    snapshot = {
        "timestamp": datetime.now(UTC).isoformat(),
        "nvidia_smi": smi_before,
        "nvidia_smi_after": smi_after,
        "ollama_ps": ollama_ps,
        "torch_cuda": torch_info,
        "exercise": exercise_result,
    }

    report_dir = Path("evaluation/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp_slug = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out_path = report_dir / f"gpu_probe_{timestamp_slug}.json"
    out_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(f"\nSnapshot saved to: {out_path}")


if __name__ == "__main__":
    main()
