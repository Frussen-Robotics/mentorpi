"""Build voice instructions from an agent's local workspace."""
from pathlib import Path


def read_vibe(text):
    lines = []
    inside = False
    for line in text.splitlines():
        if line.strip() == "## Vibe":
            inside = True
            continue
        if inside and line.startswith("## "):
            break
        if inside:
            lines.append(line)
    return "\n".join(lines).strip()


def apply_identity(base_instructions, workspace):
    root = Path(workspace).expanduser()
    identity = (root / "IDENTITY.md").read_text(encoding="utf-8").strip()
    vibe = read_vibe((root / "SOUL.md").read_text(encoding="utf-8"))

    if not identity or not vibe:
        raise ValueError("IDENTITY.md o la sezione Vibe di SOUL.md sono vuoti")

    return (
        base_instructions
        + "\n\nIdentità dell'agente che rappresenti nella conversazione:\n"
        + identity
        + "\n\nStile della conversazione:\n"
        + vibe
        + "\n\nRegole per questa interfaccia vocale:\n"
        "Usa il nome e la personalità indicati sopra. "
        "Sii utile senza formule cerimoniose o adulazione; "
        "puoi esprimere preferenze e obiezioni motivate. "
        "Non leggere ad alta voce metadati, percorsi, emoji o firme. "
        "I riferimenti al corpo descrivono il robot, non strumenti disponibili. "
        "Questa sessione dispone soltanto di ascolto e parola. "
        "Non puoi muoverti, vedere la camera, leggere o scrivere file, "
        "cercare sul web o contattare persone. "
        "Non hai ricevuto le memorie o le altre chat dell'agente: "
        "non fingere di ricordarle. Puoi usare ciò che viene detto "
        "durante questa conversazione. "
        "Non delegare compiti: il collegamento al backend non è ancora attivo."
    )
