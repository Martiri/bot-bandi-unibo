import requests
from bs4 import BeautifulSoup
import json
import os
import io
import PyPDF2
from datetime import date
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

LUNGHEZZA_MAX_RIASSUNTO = 500


def crea_issue_github(titolo_issue, corpo_messaggio):
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
        "title": titolo_issue,
        "body": corpo_messaggio,
        "labels": ["bando"],
    }
    try:
        risposta = requests.post(url, headers=headers, json=payload, timeout=10)
        risposta.raise_for_status()
        print(f"  ✅ Issue GitHub creata: {titolo_issue}")
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
        return testo
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
    testo_lower = testo.lower()
    for kw in KEYWORDS_MERITO:
        if kw in testo_lower:
            return True, f"trovato riferimento a: '{kw}'"
    return True, "nessun riferimento specifico rilevato — verificare a mano"


def crea_riassunto(testo_pdf, testo_contesto, titolo):
    """Genera un riassunto/estratto preferendo il testo del PDF a quello
    della pagina web, dato che il PDF è la fonte più affidabile e completa."""
    fonte = testo_pdf.strip() if testo_pdf and testo_pdf.strip() else testo_contesto
    riassunto = " ".join(fonte.split())
    if len(riassunto) > LUNGHEZZA_MAX_RIASSUNTO:
        riassunto = riassunto[:LUNGHEZZA_MAX_RIASSUNTO] + "…"
    if not riassunto or riassunto.lower() == titolo.lower():
        riassunto = "Nessuna descrizione disponibile."
    return riassunto.capitalize()


def controlla_bandi_unibo(memoria):
    """Analizza il portale, aggiorna 'memoria' in place con ogni link
    esaminato (anche quelli scartati, per non ricontrollarli ogni volta)
    e restituisce la lista dei bandi nuovi e validi trovati in questo giro."""
    print("🔍 Controllo bandi.unibo.it …")
    trovati = []
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
            testo_contesto = padre.get_text(" ", strip=True) if padre else ""

            if "scaduto" in testo_contesto.lower():
                continue

            print(f"  → Candidato: {titolo}")

            url_pdf   = trova_pdf_nel_bando(link_completo)
            testo_pdf = estrai_testo_pdf(url_pdf) if url_pdf else ""
            testo_totale = f"{titolo} {testo_contesto} {testo_pdf}"

            _, motivo = valuta_testo_bando(testo_totale)
            memoria.append(link_completo)

            riassunto = crea_riassunto(testo_pdf, testo_contesto, titolo)
            pdf_letto_ok = bool(url_pdf and testo_pdf.strip())
            nota_pdf = ("📄 Riassunto generato dal PDF del bando" if pdf_letto_ok
                        else "🌐 PDF non trovato o non leggibile — riassunto dal testo della pagina")

            trovati.append({
                "titolo": titolo,
                "link": link_completo,
                "motivo": motivo,
                "riassunto": riassunto,
                "nota_pdf": nota_pdf,
            })
            print(f"    ✅ Trovato — {motivo}")

    except requests.exceptions.RequestException as e:
        print(f"❌ Errore di connessione a UniBo: {e}")

    return trovati


def costruisci_issue(trovati):
    """Costruisce titolo e corpo dell'unica issue del giorno:
    un riepilogo se sono stati trovati bandi, un avviso di 'nessuna novità' altrimenti."""
    oggi = date.today().strftime("%d/%m/%Y")

    if not trovati:
        titolo_issue = f"📭 Nessun nuovo bando — {oggi}"
        corpo = (
            f"Il controllo automatico di oggi ({oggi}) non ha trovato nuovi bandi "
            f"rispetto a quelli già segnalati in precedenza.\n\n"
            f"Il prossimo controllo è previsto per domani."
        )
        return titolo_issue, corpo

    titolo_issue = f"🎓 {len(trovati)} nuovo/i bando/i trovato/i — {oggi}"
    sezioni = []
    for b in trovati:
        sezioni.append(
            f"## {b['titolo']}\n\n"
            f"{b['nota_pdf']}\n\n"
            f"✅ **Perché te lo segnalo:** {b['motivo']}\n\n"
            f"ℹ️ **Riassunto:**\n> {b['riassunto']}\n\n"
            f"🔗 **[Apri la pagina del bando]({b['link']})**"
        )
    corpo = (
        f"Trovati **{len(trovati)}** nuovi bandi il {oggi}:\n\n"
        + "\n\n---\n\n".join(sezioni)
    )
    return titolo_issue, corpo


def main():
    print("=" * 60)
    print("  Avvio script monitoraggio bandi UniBo")
    print("=" * 60)
    memoria = carica_memoria()
    lunghezza_iniziale = len(memoria)
    print(f"  Bandi già in memoria: {lunghezza_iniziale}\n")

    trovati = controlla_bandi_unibo(memoria)

    titolo_issue, corpo_issue = costruisci_issue(trovati)
    crea_issue_github(titolo_issue, corpo_issue)

    # Salva la memoria se sono stati esaminati nuovi link (trovati o scartati)
    if len(memoria) > lunghezza_iniziale:
        salva_memoria(memoria)

    if trovati:
        print(f"\n🏁 Completato. Nuovi bandi notificati: {len(trovati)}")
    else:
        print("\n🏁 Completato. Nessun nuovo bando — issue di stato inviata.")


if __name__ == "__main__":
    main()
    
