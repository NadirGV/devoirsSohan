"""Récupère les devoirs Pronote des prochains jours et génère une page lisible sur Kindle.

Variables d'environnement (à mettre dans les secrets GitHub) :
  PRONOTE_URL       adresse Pronote de l'école (…/pronote/eleve.html ou parent.html)
  PRONOTE_USER      identifiant
  PRONOTE_PASS      mot de passe
  PRONOTE_ENT       (facultatif) nom de l'ENT dans pronotepy.ent, ex. ac_paris
  PRONOTE_CHILD     (facultatif) prénom de l'enfant, si compte parent
  PAGE_SLUG         chemin secret de la page, ex. 7f3k9q2m
Options : --demo  génère la page avec des données d'exemple (sans Pronote).

Pièces jointes : les liens deviennent cliquables (avec un QR code pour les vidéos,
que la Kindle ne lit pas), les fichiers sont téléchargés depuis Pronote et convertis
en pages d'images lisibles dans le navigateur de la Kindle (PDF, Word, LibreOffice,
PowerPoint, Excel, images).
"""
import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("TZ_NAME", "Asia/Dubai"))
JOURS = 14
JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
EVAL_RE = re.compile(r"[ée]valuation|comp[ée]tence", re.I)
DS_RE = re.compile(r"\b(DS|DST|devoir surveill[ée]|contr[ôo]le|interro(gation)?|examen|test|brevet blanc|bac blanc)\b", re.I)


def classer(texte):
    """Renvoie 'eval', 'ds' ou None selon le texte (catégorie Pronote ou consigne)."""
    if EVAL_RE.search(texte or ""):
        return "eval"
    if DS_RE.search(texte or ""):
        return "ds"
    return None


MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
           "septembre", "octobre", "novembre", "décembre"]


def date_fr(d):
    return f"{JOURS_FR[d.weekday()]} {d.day} {MOIS_FR[d.month - 1]}"


# ---------------------------------------------------------------- pièces jointes
URL_RE = re.compile(r"(https?://[^\s<>\"']+|www\.[^\s<>\"']+)", re.I)
OFFICE = {"doc", "docx", "odt", "rtf", "txt", "ppt", "pptx", "odp", "pps", "ppsx",
          "xls", "xlsx", "ods", "csv"}
IMAGES = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}
MAX_PAGES = 40
_apt_ok = False


def linkify(texte):
    """Échappe le texte et rend toutes les adresses web cliquables."""
    out, pos = [], 0
    for m in URL_RE.finditer(texte or ""):
        url = m.group(0).rstrip(".,;:!?)»")
        out.append(html.escape(texte[pos:m.start()]))
        href = url if url.lower().startswith("http") else "https://" + url
        out.append(f"<a href='{html.escape(href, quote=True)}'>{html.escape(url)}</a>")
        pos = m.start() + len(url)
    out.append(html.escape((texte or "")[pos:]))
    return "".join(out).replace("\n", "<br>")


def _besoin(cmd, paquets):
    """Installe un outil à la demande sur GitHub Actions (LibreOffice ne sert que si besoin)."""
    global _apt_ok
    if shutil.which(cmd):
        return True
    try:
        if not _apt_ok:
            subprocess.run(["sudo", "apt-get", "update", "-qq"], check=True)
            _apt_ok = True
        subprocess.run(["sudo", "apt-get", "install", "-y", "-qq", "--no-install-recommends", *paquets], check=True)
    except Exception as err:  # pas de sudo en local, etc.
        print("Installation impossible :", paquets, err)
    return bool(shutil.which(cmd))


def _youtube(url):
    u = url.lower()
    return "youtube.com" in u or "youtu.be" in u


def _titre_youtube(url):
    try:
        import requests
        r = requests.get("https://www.youtube.com/oembed", params={"url": url, "format": "json"}, timeout=10)
        return r.json().get("title", "") if r.ok else ""
    except Exception:
        return ""


def _qr(url, dossier):
    import qrcode
    nom = "qr-" + hashlib.sha1(url.encode()).hexdigest()[:10] + ".png"
    chemin = os.path.join(dossier, nom)
    if not os.path.exists(chemin):
        qrcode.make(url, box_size=6, border=2).save(chemin)
    return nom


def _pages_pdf(pdf, dossier):
    if not _besoin("pdftoppm", ["poppler-utils"]):
        return []
    subprocess.run(["pdftoppm", "-jpeg", "-jpegopt", "quality=80", "-scale-to-x", "1100", "-scale-to-y", "-1",
                    "-l", str(MAX_PAGES), pdf, os.path.join(dossier, "p")], check=True, timeout=300)
    return sorted(f for f in os.listdir(dossier) if f.startswith("p-") and f.endswith(".jpg"))


def _vers_pdf(fichier, dossier_tmp):
    if not _besoin("soffice", ["libreoffice-writer-nogui", "libreoffice-impress-nogui",
                                "libreoffice-calc-nogui", "fonts-dejavu", "fonts-liberation"]):
        return None
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", dossier_tmp, fichier],
                   check=True, timeout=300, capture_output=True)
    pdf = os.path.join(dossier_tmp, os.path.splitext(os.path.basename(fichier))[0] + ".pdf")
    return pdf if os.path.exists(pdf) else None


VIEW_CSS = """a{word-break:break-all}body{font-family:Georgia,serif;margin:0;padding:14px 18px;background:#fff;color:#000;font-size:28px}
a{color:#000}.nav{margin-bottom:12px}.nav a{display:inline-block;margin-right:24px;padding:8px 0}
h1{font-size:30px;margin:6px 0 14px;word-wrap:break-word}img{width:100%;border:1px solid #999;margin:0 0 16px}
.n{font-size:20px;color:#555;margin-bottom:4px}"""


def _page_doc(dossier, nom, original, pages, image=None):
    e = html.escape
    out = ["<!doctype html><html lang='fr'><head><meta charset='utf-8'>",
           "<meta name='viewport' content='width=device-width,initial-scale=1'>",
           "<meta name='robots' content='noindex,nofollow'>",
           f"<title>{e(nom)}</title><style>{VIEW_CSS}</style></head><body>",
           "<div class='nav'><a href='../../'>← Retour aux devoirs</a>",
           f"<a href='{e(urllib.parse.quote(original))}'>Télécharger le fichier</a></div>",
           f"<h1>{e(nom)}</h1>"]
    if image:
        out.append(f"<img src='{e(urllib.parse.quote(image))}' alt=''>")
    for i, page in enumerate(pages, 1):
        out.append(f"<div class='n'>Page {i} / {len(pages)}</div><img src='{page}' alt=''>")
    if not image and not pages:
        out.append("<p>Aperçu impossible pour ce type de fichier. Utilise « Télécharger le fichier » sur un ordinateur ou un téléphone.</p>")
    if len(pages) >= MAX_PAGES:
        out.append(f"<p>Seules les {MAX_PAGES} premières pages sont affichées.</p>")
    out.append("</body></html>")
    with open(os.path.join(dossier, "index.html"), "w", encoding="utf-8") as f:
        f.write("\n".join(out))


def piece_jointe(f, docs):
    """Transforme une pièce jointe Pronote en lien utilisable sur la Kindle."""
    nom = (getattr(f, "name", "") or "").strip()
    if getattr(f, "type", 1) == 0:  # lien web
        url = f.url if "://" in f.url else "https://" + f.url
        pj = {"type": "lien", "nom": nom if nom and nom != f.url else "", "url": url, "video": _youtube(url)}
        if pj["video"]:
            pj["nom"] = _titre_youtube(url) or pj["nom"] or "Vidéo YouTube"
            pj["qr"] = "docs/" + _qr(url, docs)
        return pj
    try:
        data = f.data
        if not data:
            raise ValueError("fichier vide")
        h = hashlib.sha1(data).hexdigest()[:12]
        dossier = os.path.join(docs, h)
        ext = os.path.splitext(nom)[1].lower().lstrip(".")
        if not os.path.exists(os.path.join(dossier, "index.html")):
            os.makedirs(dossier, exist_ok=True)
            original = re.sub(r"[^\w.\-]+", "_", nom) or f"fichier.{ext or 'bin'}"
            with open(os.path.join(dossier, original), "wb") as out:
                out.write(data)
            pages, image = [], None
            try:
                if ext == "pdf":
                    pages = _pages_pdf(os.path.join(dossier, original), dossier)
                elif ext in OFFICE:
                    with tempfile.TemporaryDirectory() as tmp:
                        src = os.path.join(tmp, "doc." + ext)
                        shutil.copy(os.path.join(dossier, original), src)
                        pdf = _vers_pdf(src, tmp)
                        if pdf:
                            pages = _pages_pdf(pdf, dossier)
                elif ext in IMAGES:
                    image = original
            except Exception as err:
                print("Conversion impossible :", nom, err)
            _page_doc(dossier, nom, original, pages, image)
        return {"type": "fichier", "nom": nom, "page": f"docs/{h}/", "ext": ext}
    except Exception as err:
        print("Pièce jointe non récupérée :", nom, err)
        return {"type": "erreur", "nom": nom}


def pieces(objet, docs):
    return [piece_jointe(f, docs) for f in (getattr(objet, "files", None) or [])]


def connexion():
    import pronotepy
    import pronotepy.ent
    url = os.environ["PRONOTE_URL"]
    ent_name = os.environ.get("PRONOTE_ENT", "").strip()
    ent = getattr(pronotepy.ent, ent_name) if ent_name else None
    child = os.environ.get("PRONOTE_CHILD", "").strip()
    cls = pronotepy.ParentClient if "parent" in url.lower() else pronotepy.Client
    client = cls(url, username=os.environ["PRONOTE_USER"], password=os.environ["PRONOTE_PASS"], ent=ent)
    if not client.logged_in:
        sys.exit("Connexion Pronote refusée")
    if cls is pronotepy.ParentClient and child:
        client.set_child(child)
    return client


def fetch(docs):
    client = connexion()
    today = dt.datetime.now(TZ).date()

    devoirs = []
    for h in client.homework(today, today + dt.timedelta(days=JOURS)):
        devoirs.append({
            "date": h.date.isoformat(),
            "matiere": h.subject.name if h.subject else "Autre",
            "couleur": h.background_color or "",
            "texte": h.description or "",
            "fait": bool(h.done),
            "pj": pieces(h, docs),
        })
    demain = today + dt.timedelta(days=1)
    while demain.weekday() >= 5:  # emploi du temps du prochain jour de cours
        demain += dt.timedelta(days=1)
    cours = []
    for c in client.lessons(demain):
        cours.append({
            "debut": c.start.strftime("%H:%M"),
            "matiere": c.subject.name if c.subject else "",
            "annule": bool(c.canceled),
            "statut": c.status or "",
        })
    cours.sort(key=lambda c: c["debut"])

    # Prochains DS et évaluations : cours marqués « devoir » dans l'emploi du temps,
    # ou dont le contenu (cahier de textes) est de catégorie DS / évaluation.
    ds, docs_cours = [], []
    for c in client.lessons(today - dt.timedelta(days=7), today + dt.timedelta(days=JOURS)):
        if c.canceled:
            continue
        contenu = c.content
        # Documents et liens déposés dans le cahier de textes (7 derniers jours)
        if contenu and c.start.date() <= today:
            pj = pieces(contenu, docs)
            liens = URL_RE.findall(contenu.description or "")
            if pj or liens:
                docs_cours.append({"date": c.start.date().isoformat(),
                                   "matiere": c.subject.name if c.subject else "",
                                   "titre": contenu.title or "", "texte": contenu.description or "", "pj": pj})
        if c.start.date() < today:
            continue
        cat = " ".join(filter(None, [getattr(contenu, "category", None), getattr(contenu, "title", None)])) if contenu else ""
        genre = classer(cat) or ("ds" if getattr(c, "test", False) else None)
        if genre:
            ds.append({"date": c.start.date().isoformat(), "heure": c.start.strftime("%H:%M"),
                       "matiere": c.subject.name if c.subject else "", "texte": cat.strip(), "genre": genre})
    docs_cours.sort(key=lambda x: x["date"], reverse=True)

    # Copie de tous les documents Pronote dans Koofr, APRÈS la page, avec une session à part :
    # une erreur Pronote ici ne peut plus empêcher la mise à jour de la page des devoirs.
    try:
        import koofr_pronote
        koofr_pronote.archiver(connexion(), _vers_pdf, today)
    except Exception as err:
        print("Koofr : étape ignorée suite à une erreur :", err)

    return {"maj": dt.datetime.now(TZ).isoformat(), "devoirs": devoirs, "ds": ds,
            "edt_date": demain.isoformat(), "edt": cours, "docs_cours": docs_cours}


class _PJ:
    """Pièce jointe factice pour --demo."""
    def __init__(self, name, type_, url="", data=b""):
        self.name, self.type, self.url, self.data = name, type_, url, data


def demo(docs):
    today = dt.datetime.now(TZ).date()
    exemples = os.environ.get("DEMO_FILES", "").split(os.pathsep)
    fichiers = [_PJ(os.path.basename(p), 1, data=open(p, "rb").read()) for p in exemples if p and os.path.exists(p)]
    pj_esp = [piece_jointe(_PJ("https://www.youtube.com/watch?v=Ga-RBgGeZzM", 0, "https://www.youtube.com/watch?v=Ga-RBgGeZzM"), docs)] + \
             [piece_jointe(f, docs) for f in fichiers]
    d = lambda n: (today + dt.timedelta(days=n)).isoformat()
    return {"maj": dt.datetime.now(TZ).isoformat(), "edt_date": d(1), "devoirs": [
        {"date": d(1), "matiere": "ESPAGNOL", "couleur": "#e6a23c", "texte": "Apprendre le vocabulaire du Día de Muertos (fiche + mots croisés). Contrôle. Voir aussi https://www.lexilogos.com/espagnol_dictionnaire.htm", "fait": False, "pj": pj_esp},
        {"date": d(1), "matiere": "MATHÉMATIQUES", "couleur": "#409eff", "texte": "Exercices 12, 14 et 15 page 87.", "fait": True},
        {"date": d(2), "matiere": "FRANÇAIS", "couleur": "#f56c6c", "texte": "Lire le chapitre 3 et répondre aux questions 1 à 5.", "fait": False},
        {"date": d(4), "matiere": "HISTOIRE-GÉOGRAPHIE", "couleur": "#67c23a", "texte": "Réviser la leçon sur les Carolingiens.", "fait": False},
    ], "ds": [
        {"date": d(3), "heure": "10:15", "matiere": "MATHÉMATIQUES", "texte": "", "genre": "ds"},
        {"date": d(5), "heure": "13:00", "matiere": "ANGLAIS", "texte": "Évaluation de compétences : expression orale", "genre": "eval"},
    ], "edt": [
        {"debut": "08:00", "matiere": "MATHÉMATIQUES", "annule": False, "statut": ""},
        {"debut": "09:00", "matiere": "ESPAGNOL", "annule": False, "statut": ""},
        {"debut": "10:15", "matiere": "SVT", "annule": True, "statut": "Prof. absent"},
        {"debut": "11:15", "matiere": "FRANÇAIS", "annule": False, "statut": ""},
    ], "docs_cours": [
        {"date": d(-1), "matiere": "SVT", "titre": "La cellule", "texte": "Schéma à compléter : www.svtlycee.fr/cellule", "pj": [piece_jointe(f, docs) for f in fichiers[:1]]},
    ]}


CSS = """
body{font-family:Georgia,'Times New Roman',serif;margin:0;padding:18px 22px;background:#fff;color:#000;font-size:30px;line-height:1.35}
h1{font-size:40px;margin:0 0 4px}
.maj{font-size:22px;color:#444;margin-bottom:18px}
h2{font-size:32px;margin:26px 0 10px;padding:6px 10px;background:#000;color:#fff}
h2.loin{background:#555}
.d{border-left:14px solid #888;padding:6px 0 10px 14px;margin:0 0 14px}
.m{font-weight:bold;font-size:26px;letter-spacing:1px}
.t{margin-top:2px}
.fait{color:#666}
.fait .t{text-decoration:line-through}
.ok{font-size:22px}
.ds{border:4px solid #000;padding:10px 14px;margin:0 0 16px}
.dst{font-size:32px;font-weight:bold;margin-bottom:6px}
.dsi{padding:6px 0;border-top:1px solid #999;font-size:28px}
.dsi:first-of-type{border-top:0}
.vide{font-style:italic;color:#444}
table{border-collapse:collapse;width:100%;font-size:26px}
td{padding:6px 8px;border-bottom:1px solid #999;vertical-align:top}
td.h{width:110px;font-weight:bold}
.annule{text-decoration:line-through;color:#666}
a{color:#000;word-break:break-all;word-wrap:break-word}
.pj{margin:8px 0 0;padding:0;list-style:none;font-size:26px}
.pj li{margin:0 0 8px;padding:8px 10px;border:2px solid #000}
.pj a{font-weight:bold;text-decoration:underline;word-wrap:break-word}
.pj .x{font-size:20px;color:#444}
.pj img{display:block;width:150px;height:150px;margin-top:6px}
.dc{padding:8px 0;border-top:1px solid #999}
"""


ICONES = {"pdf": "PDF", "doc": "Word", "docx": "Word", "odt": "Texte", "rtf": "Texte", "txt": "Texte",
          "ppt": "Diaporama", "pptx": "Diaporama", "odp": "Diaporama", "xls": "Tableur", "xlsx": "Tableur",
          "ods": "Tableur", "jpg": "Image", "jpeg": "Image", "png": "Image"}


def render_pj(liste):
    if not liste:
        return ""
    e = html.escape
    out = ["<ul class='pj'>"]
    for p in liste:
        if p["type"] == "lien":
            libelle = p["nom"] or p["url"]
            if p.get("video"):
                out.append(f"<li>▶ <a href='{e(p['url'], quote=True)}'>{e(libelle)}</a>"
                           "<div class='x'>Vidéo : la Kindle ne lit pas les vidéos, scanne ce code avec un téléphone ou une tablette.</div>"
                           f"<img src='{e(p['qr'], quote=True)}' alt='QR code'></li>")
            else:
                out.append(f"<li><span class='x'>Lien :</span> <a href='{e(p['url'], quote=True)}'>{e(libelle)}</a></li>")
        elif p["type"] == "fichier":
            genre = ICONES.get(p.get("ext", ""), "Fichier")
            out.append(f"<li><a href='{e(p['page'], quote=True)}'>{e(p['nom'])}</a> <span class='x'>({genre})</span></li>")
        else:
            out.append(f"<li>{e(p['nom'])} <span class='x'>(non récupéré, à voir sur Pronote)</span></li>")
    out.append("</ul>")
    return "".join(out)


def render(data):
    e = html.escape
    today = dt.datetime.now(TZ).date()
    maj = dt.datetime.fromisoformat(data["maj"])
    par_jour = {}
    for h in sorted(data["devoirs"], key=lambda h: (h["date"], h["matiere"])):
        par_jour.setdefault(h["date"], []).append(h)

    out = ["<!doctype html><html lang='fr'><head><meta charset='utf-8'>",
           "<meta name='viewport' content='width=device-width,initial-scale=1'>",
           "<meta name='robots' content='noindex,nofollow'>",
           "<title>Devoirs</title><style>", CSS, "</style></head><body>",
           "<h1>Devoirs</h1>",
           f"<div class='maj'>Mis à jour le {date_fr(maj.date())} à {maj:%H:%M}</div>"]

    # Prochains DS puis évaluations, avant les devoirs
    blocs = {"ds": {}, "eval": {}}
    for t in data.get("ds", []):
        blocs[t.get("genre", "ds")][(t["date"], t["matiere"])] = dict(t)
    for h in data["devoirs"]:
        genre = classer(h["texte"])
        if genre:
            k = (h["date"], h["matiere"])
            item = blocs[genre].setdefault(k, {"date": h["date"], "heure": "", "matiere": h["matiere"], "texte": ""})
            item["texte"] = h["texte"]
    for genre, titre, vide in (("ds", "Prochains DS", "Aucun DS prévu"),
                               ("eval", "Prochaines évaluations de compétences", "Aucune évaluation prévue")):
        out.append(f"<div class='ds'><div class='dst'>{titre}</div>")
        if not blocs[genre]:
            out.append(f"<div class='vide'>{vide} dans les {JOURS} prochains jours.</div>")
        for (jour, _), t in sorted(blocs[genre].items()):
            d = dt.date.fromisoformat(jour)
            ecart = (d - today).days
            quand = {0: "aujourd'hui", 1: "demain"}.get(ecart, f"{date_fr(d)} (dans {ecart} j)")
            heure = f" à {t['heure'].replace(':', ' h ')}" if t["heure"] else ""
            texte = f"<div class='t'>{linkify(t['texte'].strip())}</div>" if t["texte"] else ""
            out.append(f"<div class='dsi'><b>{e(t['matiere'])}</b> — {e(quand)}{e(heure)}{texte}</div>")
        out.append("</div>")

    if not par_jour:
        out.append("<p class='vide'>Aucun devoir dans les prochains jours.</p>")
    for jour, items in par_jour.items():
        d = dt.date.fromisoformat(jour)
        ecart = (d - today).days
        titre = {0: "Pour aujourd'hui", 1: "Pour demain"}.get(ecart, f"Pour {date_fr(d)}")
        if ecart not in (0, 1):
            titre += f" (dans {ecart} j)"
        out.append(f"<h2 class='{'loin' if ecart > 2 else ''}'>{e(titre)}</h2>")
        for h in items:
            couleur = h["couleur"] if h["couleur"].startswith("#") else "#888"
            cls = "d fait" if h["fait"] else "d"
            ok = " <span class='ok'>✓ fait</span>" if h["fait"] else ""
            texte = linkify(h["texte"].strip())
            out.append(f"<div class='{cls}' style='border-left-color:{couleur}'>"
                       f"<div class='m'>{e(h['matiere'])}{ok}</div><div class='t'>{texte}</div>"
                       f"{render_pj(h.get('pj'))}</div>")

    if data.get("docs_cours"):
        out.append("<h2 class='loin'>Documents des derniers cours</h2>")
        for c in data["docs_cours"]:
            d = dt.date.fromisoformat(c["date"])
            titre = f" — {e(c['titre'])}" if c["titre"] else ""
            texte = f"<div class='t'>{linkify(c['texte'].strip())}</div>" if c["texte"].strip() else ""
            out.append(f"<div class='dc'><div class='m'>{e(c['matiere'])}{titre}</div>"
                       f"<div class='x'>{e(date_fr(d))}</div>{texte}{render_pj(c['pj'])}</div>")

    if data.get("edt"):
        d = dt.date.fromisoformat(data["edt_date"])
        out.append(f"<h2 class='loin'>Emploi du temps — {e(date_fr(d))}</h2><table>")
        for c in data["edt"]:
            cls = " class='annule'" if c["annule"] else ""
            statut = f" — {e(c['statut'])}" if c["statut"] else ""
            out.append(f"<tr{cls}><td class='h'>{e(c['debut'])}</td><td>{e(c['matiere'])}{statut}</td></tr>")
        out.append("</table>")
    out.append("</body></html>")
    return "\n".join(out)


def main():
    slug = os.environ.get("PAGE_SLUG", "demo").strip().strip("/")
    docs = f"site/{slug}/docs"
    os.makedirs(docs, exist_ok=True)
    data = demo(docs) if "--demo" in sys.argv else fetch(docs)
    with open(f"site/{slug}/index.html", "w", encoding="utf-8") as f:
        f.write(render(data))
    with open("site/index.html", "w", encoding="utf-8") as f:
        f.write("<!doctype html><meta name='robots' content='noindex'><title>.</title>")
    with open("site/robots.txt", "w") as f:
        f.write("User-agent: *\nDisallow: /\n")
    nb_pj = sum(len(h.get("pj", [])) for h in data["devoirs"]) + sum(len(c["pj"]) for c in data.get("docs_cours", []))
    print(f"{len(data['devoirs'])} devoirs, {len(data.get('edt', []))} cours, {nb_pj} pièces jointes")


if __name__ == "__main__":
    main()
