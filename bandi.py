import requests
from bs4 import BeautifulSoup
import json
import os
import io
import PyPDF2
from urllib.parse import urljoin

FILE_MEMORIA = "bandi_trovati.json"

URL_UNIBO = (
    "https://bandi.unibo.it/agevolazioni/opportunita"
    "?riservato=iscritti&tipocorso=laurea"
    "&corsi=6639%2C9244%2C8007&struttura=&search=&stato=aperto"
)

KEYWORDS_MERITO = [
    "merito", "eccellenza", "premio",
    "curriculum", "media ponderata", "cfu",
]
KEYWORDS_ESCLUDI = ["esclusivamente isee", "solo isee"]


def crea_issue_github(titolo_bando, corpo_messaggio):
    token = os.environ.get("GITHUB_TOKEN")
    repo  = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("⚠️  GITHUB_TOKEN o GITHUB_REPOSITORY non trovati.")
        return
    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    payload = {
        "title": f"🎓 Nuovo Bando: {titolo_bando}",
        "body": corpo_messaggio,
        "labels": ["bando"],
    }
    try:
        risposta = requests.post(url, headers=headers, json=payload, timeout=10)
        risposta.raise_for_status()
        print(f"  ✅ Issue GitHub creata: {titolo_bando}")
    except requests.exceptions.RequestException as e:
        print(f"  ❌ Errore creazione Issue GitHub: {e}")


def carica_memoria():
    if os.path.exists(FILE_MEMORIA):
        try:
            with open(FILE_MEMORIA, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
    return []


def salva_memoria(memoria):
    with open(FILE_MEMORIA, "w", encoding="utf-8") as f:
        json.dump(memoria, f, ensure_ascii=False, indent=2)


def estrai_testo_pdf(url_pdf):
    print(f"    📄 Lettura PDF: {url_pdf}")
    try:
        risposta = requests.get(url_pdf, stream=True, timeout=20,
                                headers={"User-Agent": "Mozilla/5.0"})
        risposta.raise_for_status()
        pdf_file = io.BytesIO(risposta.content)
        reader   = PyPDF2.PdfReader(pdf_file)
        testo = ""
        for pagina in reader.pages:
            estratto = pagina.extract_text()
            if estratto:
                testo += estratto + " "
        return testo.lower()
    except Exception as e:
        print(f"    ⚠️  Impossibile leggere il PDF: {e}")
        return ""


def trova_pdf_nel_bando(url_bando):
    try:
        risposta = requests.get(url_bando, timeout=10,
                                headers={"User-Agent": "Mozilla/5.0"})
        risposta.raise_for_status()
        soup = BeautifulSoup(risposta.text, "html.parser")
        for tag_a in soup.find_all("a", href=True):
            if tag_a["href"].lower().endswith(".pdf"):
                return urljoin("https://bandi.unibo.it", tag_a["href"])
        return None
    except Exception as e:
        print(f"    ⚠️  Errore ricerca PDF: {e}")
        return None


def valuta_testo_bando(testo):
    for kw in KEYWORDS_ESCLUDI:
        if kw in testo:
            return False, f"scartato — trovato: '{kw}'"
    for kw in KEYWORDS_MERITO:
        if kw in testo:
            return True, f"trovato riferimento a: '{kw}'"
    return True, "nessun limite ISEE restrittivo rilevato"


def controlla_bandi_unibo(memoria):
    print("🔍 Controllo bandi.unibo.it …")
    nuovi = 0
    try:
        risposta = requests.get(
            URL_UNIBO,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=15,
        )
        risposta.raise_for_status()
        soup = BeautifulSoup(risposta.text, "html.parser")

        for tag_a in soup.find_all("a", href=True):
            href_lower = tag_a["href"].lower().strip()

            if href_lower in ("/agevolazioni/opportunita",
                              "/agevolazioni/opportunita/", "#", ""):
                continue
            if "/bando/" not in href_lower and \
               "/agevolazioni/opportunita/" not in href_lower:
                continue

            link_completo = urljoin("https://bandi.unibo.it", tag_a["href"])
            titolo = tag_a.get_text(strip=True)

            if len(titolo) < 10:
                continue
            if link_completo in memoria:
                continue

            padre = tag_a.find_parent(["tr", "li", "div", "article"])
            testo_contesto = padre.get_text(" ", strip=True).lower() if padre else ""

            if "scaduto" in testo_contesto:
                continue

            print(f"  → Candidato: {titolo}")

            testo_totale = f"{titolo.lower()} {testo_contesto}"
            url_pdf   = trova_pdf_nel_bando(link_completo)
            testo_pdf = estrai_testo_pdf(url_pdf) if url_pdf else ""
            testo_totale += " " + testo_pdf

            valido, motivo = valuta_testo_bando(testo_totale)
            memoria.append(link_completo)

            if not valido:
                print(f"    ⛔ {motivo}")
                continue

            anteprima = " ".join(testo_contesto.split())
            if len(anteprima) > 300:
                anteprima = anteprima[:300] + "…"
            if not anteprima or anteprima.lower() == titolo.lower():
                anteprima = "Nessuna descrizione disponibile sulla pagina web."

            nota_pdf = "📄 PDF analizzato" if url_pdf else "🌐 solo testo web"
            corpo_issue = (
                f"### {nota_pdf}\n\n"
                f"✅ **Perché te lo segnalo:** {motivo}\n\n"
                f"ℹ️ **Anteprima:**\n> {anteprima.capitalize()}\n\n"
                f"🔗 **[Apri la pagina del bando]({link_completo})**"
            )

            crea_issue_github(titolo, corpo_issue)
            print(f"    ✅ Notificato — {motivo}")
            nuovi += 1

    except requests.exceptions.RequestException as e:
        print(f"❌ Errore di connessione a UniBo: {e}")

    return nuovi


def main():
    print("=" * 60)
    print("  Avvio script monitoraggio bandi UniBo")
    print("=" * 60)
    memoria = carica_memoria()
    print(f"  Bandi già in memoria: {len(memoria)}\n")
    nuovi = controlla_bandi_unibo(memoria)
    if nuovi > 0:
        salva_memoria(memoria)
        print(f"\n🏁 Completato. Nuovi bandi notificati: {nuovi}")
    else:
        print("\n🏁 Completato. Nessun nuovo bando al momento.")


if __name__ == "__main__":
    main()
