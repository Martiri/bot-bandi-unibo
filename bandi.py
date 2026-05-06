import requests
from bs4 import BeautifulSoup
import json
import time
import os
import io
import PyPDF2
from urllib.parse import urljoin

# --- CONFIGURAZIONE RICERCA ---
FILE_MEMORIA = "bandi_trovati.json"
URL_UNIBO_PREMI = "https://bandi.unibo.it/agevolazioni/opportunita?riservato=iscritti&tipocorso=laurea&corsi=6639%2C9244%2C8007&struttura=&search=&stato=aperto"

KEYWORDS_MERITO = ["merito", "eccellenza", "premio", "curriculum", "media ponderata", "cfu"]
KEYWORDS_ESCLUDI = ["esclusivamente isee", "solo isee"]

def crea_issue_github(titolo_bando, corpo_messaggio):
    """Crea una Issue nel repository di GitHub per inviarti la notifica."""
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")

    if not token or not repo:
        print("⚠️ Token GitHub o nome Repository mancanti. Notifica non inviata.")
        return

    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # Payload per creare l'Issue
    payload = {
        "title": f"🎓 Nuovo Bando: {titolo_bando}",
        "body": corpo_messaggio
    }

    try:
        risposta = requests.post(url, headers=headers, json=payload)
        risposta.raise_for_status()
        print(f"✅ Notifica GitHub creata con successo per: {titolo_bando}")
    except Exception as e:
        print(f"❌ Errore nella creazione della notifica su GitHub: {e}")

def carica_memoria():
    if os.path.exists(FILE_MEMORIA):
        try:
            with open(FILE_MEMORIA, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []

def salva_memoria(memoria):
    with open(FILE_MEMORIA, "w", encoding="utf-8") as f:
        json.dump(memoria, f)

def estrai_testo_pdf(url_pdf):
    print(f"📄 Lettura PDF in corso: {url_pdf}")
    try:
        response = requests.get(url_pdf, stream=True, timeout=15)
        response.raise_for_status()
        
        pdf_file = io.BytesIO(response.content)
        reader = PyPDF2.PdfReader(pdf_file)
        
        testo_completo = ""
        for page in reader.pages:
            testo_estratto = page.extract_text()
            if testo_estratto:
                testo_completo += testo_estratto + " "
                
        return testo_completo.lower()
    except Exception as e:
        print(f"Errore durante l'estrazione del PDF: {e}")
        return ""

def trova_pdf_nel_bando(url_dettaglio_bando):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url_dettaglio_bando, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            if href.lower().endswith('.pdf'):
                return urljoin("https://bandi.unibo.it", href)
        return None
    except Exception as e:
        return None

def valuta_testo_bando(testo_da_valutare):
    for kw in KEYWORDS_ESCLUDI:
        if kw in testo_da_valutare:
            return False, f"Scartato (Trovato limite: '{kw}')"
            
    for kw in KEYWORDS_MERITO:
        if kw in testo_da_valutare:
            return True, f"Trovato riferimento a: '{kw}'"
            
    return True, "Nessun limite ISEE restrittivo rilevato"

def controlla_bandi_unibo(memoria):
    print("Controllo sito UniBo in corso...")
    nuovi_bandi_trovati = 0
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(URL_UNIBO_PREMI, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for link_tag in soup.find_all('a', href=True):
            href = link_tag['href'].lower()
            
            if href == "/agevolazioni/opportunita" or href == "/agevolazioni/opportunita/" or href == "#":
                continue
            
            if '/bando/' in href or '/agevolazioni/opportunita/' in href:
                link_completo = urljoin("https://bandi.unibo.it", link_tag['href'])
                titolo = link_tag.text.strip()
                
                if len(titolo) < 10 or link_completo in memoria:
                    continue
                
                padre = link_tag.find_parent(['tr', 'li', 'div', 'article'])
                testo_circostante = padre.text.strip().lower() if padre else ""
                
                if "scaduto" in testo_circostante:
                    continue
                
                testo_totale = (titolo + " " + testo_circostante).lower()
                
                url_pdf = trova_pdf_nel_bando(link_completo)
                if url_pdf:
                    testo_pdf = estrai_testo_pdf(url_pdf)
                    testo_totale += " " + testo_pdf
                
                bando_valido, motivo = valuta_testo_bando(testo_totale)
                
                if bando_valido:
                    nota_pdf = "📄 (PDF Analizzato)" if url_pdf else "🌐 (Solo Testo Web)"
                    
                    testo_pulito = " ".join(testo_circostante.split())
                    breve_descrizione = testo_pulito[:250] + "..." if len(testo_pulito) > 250 else testo_pulito
                    
                    if not breve_descrizione or breve_descrizione == titolo.lower():
                        breve_descrizione = "Nessuna descrizione breve disponibile."

                    # Costruiamo il testo in Markdown per l'Issue di GitHub
                    corpo_issue = (
                        f"### {nota_pdf}\n\n"
                        f"✅ **Perché te lo segnalo:** {motivo}\n\n"
                        f"ℹ️ **Informazioni:** \n> {breve_descrizione.capitalize()}\n\n"
                        f"🔗 **[Clicca qui per aprire la pagina del bando]({link_completo})**"
                    )
                    
                    # Chiamata a GitHub invece che a Telegram
                    crea_issue_github(titolo, corpo_issue)
                    
                    memoria.append(link_completo)
                    nuovi_bandi_trovati += 1
                    time.sleep(3)
                    
    except requests.exceptions.RequestException as e:
        print(f"Errore di connessione a UniBo: {e}")
        
    return nuovi_bandi_trovati

def main():
    print("Avvio script di monitoraggio bandi...")
    
    memoria_bandi = carica_memoria()
    nuovi = controlla_bandi_unibo(memoria_bandi)
    
    if nuovi > 0:
        salva_memoria(memoria_bandi)
        print(f"Operazione conclusa. Trovati {nuovi} nuovi bandi validi.")
    else:
        print("Operazione conclusa. Nessun bando interessante al momento.")

if __name__ == "__main__":
    main()
