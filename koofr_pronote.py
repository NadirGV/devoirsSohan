"""Copie les documents et liens Pronote dans Koofr, à côté des documents Classroom.

Arborescence (la même que le script Classroom, pour que la Kindle voie tout au même endroit) :
    /Classroom/<Matière>/Pronote/<Thème>/<document>
  - Thème = titre du cours dans le cahier de textes (ex. « Séquence 2 - Le roman de chevalerie »)
  - « Devoirs » pour les pièces jointes des travaux à faire
  - chaque dossier reçoit aussi « Liens et vidéos.html » quand il y a des liens

Tout ce qui a été publié depuis la rentrée est récupéré ; un fichier déjà présent sur Koofr
n'est ni retéléchargé ni renvoyé.

Variables d'environnement : KOOFR_USER, KOOFR_PASS (mot de passe d'application Koofr).
"""
import datetime as dt
import html
import os
import re
import shutil
import tempfile
import unicodedata
import urllib.parse

import requests

DAV = "https://app.koofr.net/dav/Koofr"
RACINE = "/Classroom"
OFFICE_VERS_PDF = {"doc", "docx", "odt", "rtf", "ppt", "pptx", "odp", "pps", "ppsx", "xls", "xlsx", "ods"}
TAILLE_MAX = 45 * 1024 * 1024

# Matières Pronote → nom des dossiers déjà créés par le script Classroom (ordre important)
MATIERES = [
    (("SPORT", "EPS", "ED.PHYS", "EDUCATION PHYSIQUE"), "EPS"),
    (("MATH",), "Mathématiques"),
    (("FRANC",), "Français"),
    (("ANGL",), "Anglais"),
    (("ARAB",), "Arabe"),
    (("ESPAGN",), "Espagnol"),
    (("SOCIAL",), "Social Studies"),
    (("HIST", "GEOG"), "Histoire-Géographie"),
    (("PHYS", "CHIM"), "Physique-Chimie"),
    (("SVT", "S.V.T", "S V T", "VIE ET", "VIE &", "SCIENCES DE LA VIE"), "SVT"),
    (("TECHNO",), "Technologie"),
    (("MUSI",), "Éducation musicale"),
    (("ARTS", "PLAST"), "Arts plastiques"),
    (("LATIN",), "Latin"),
    (("EMC", "MORAL"), "EMC"),
]


def _sans_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").upper()


def matiere(nom):
    cle = _sans_accents(nom or "")
    for mots, dossier in MATIERES:
        if any(m in cle for m in mots):
            return dossier
    return propre((nom or "Autre").title())


def propre(nom):
    nom = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", str(nom or "Sans nom"))
    nom = re.sub(r"\s+", " ", nom).strip().rstrip(". ")
    return nom[:120] or "Sans nom"


class Koofr:
    def __init__(self, user, mdp):
        self.s = requests.Session()
        self.s.auth = (user, mdp)
        self.dossiers = set()

    def url(self, chemin):
        return DAV + urllib.parse.quote(chemin)

    def existe(self, chemin):
        r = self.s.head(self.url(chemin), timeout=60)
        if r.status_code == 401:
            raise RuntimeError("Koofr refuse l'identifiant ou le mot de passe d'application")
        return r.status_code == 200

    def creer_dossiers(self, chemin):
        courant = ""
        for part in [p for p in chemin.split("/") if p]:
            courant += "/" + part
            if courant in self.dossiers:
                continue
            r = self.s.request("MKCOL", self.url(courant), timeout=60)
            if r.status_code not in (201, 405, 301) and r.status_code >= 300:
                raise RuntimeError(f"Dossier Koofr impossible ({courant}) : {r.status_code}")
            self.dossiers.add(courant)

    def supprimer(self, chemin):
        self.s.delete(self.url(chemin), timeout=60)

    def envoyer(self, chemin, data):
        self.creer_dossiers(chemin.rsplit("/", 1)[0])
        r = self.s.put(self.url(chemin), data=data, timeout=300)
        if r.status_code >= 300:
            raise RuntimeError(f"Envoi Koofr impossible ({chemin}) : {r.status_code}")


def _convertir(nom, data, vers_pdf):
    """Renvoie (nom_final, données). Les fichiers Office deviennent des PDF lisibles par KOReader."""
    base, ext = os.path.splitext(nom)
    ext = ext.lower().lstrip(".")
    if ext not in OFFICE_VERS_PDF:
        return nom, data
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "doc." + ext)
        with open(src, "wb") as f:
            f.write(data)
        try:
            pdf = vers_pdf(src, tmp)
        except Exception as err:
            print("Conversion PDF impossible :", nom, err)
            pdf = None
        if pdf:
            with open(pdf, "rb") as f:
                return base + ".pdf", f.read()
    return nom, data


def _page_liens(liens):
    e = html.escape
    lignes = ["<!doctype html><html lang='fr'><head><meta charset='utf-8'><title>Liens et vidéos</title></head><body>",
              "<h1>Liens et vidéos (Pronote)</h1>",
              "<p><i>Les vidéos ne se lisent pas sur la Kindle : ouvre-les sur un téléphone ou une tablette "
              "(un appui long sur un lien dans KOReader permet d'afficher un QR code).</i></p><ul>"]
    for l in sorted(liens, key=lambda x: x["date"], reverse=True):
        lignes.append(f"<li><p><a href='{e(l['url'], quote=True)}'>{e(l['titre'])}</a><br>"
                      f"<small>{e(l['date'])} — {e(l['source'])}</small></p></li>")
    lignes.append("</ul></body></html>")
    return "\n".join(lignes).encode("utf-8")


URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)


def archiver(client, vers_pdf, aujourd_hui):
    user, mdp = os.environ.get("KOOFR_USER", "").strip(), os.environ.get("KOOFR_PASS", "").strip()
    if not (user and mdp):
        print("Koofr : non configuré (secrets KOOFR_USER / KOOFR_PASS absents), étape ignorée")
        return
    k = Koofr(user, mdp)
    try:
        debut = getattr(client, "start_day", None) or (aujourd_hui - dt.timedelta(days=120))
    except Exception:
        debut = aujourd_hui - dt.timedelta(days=120)
    if isinstance(debut, dt.datetime):
        debut = debut.date()

    elements = []  # (matière, thème, date, titre source, objet avec .files, texte)
    # travail à faire, semaine par semaine : Pronote refuse les trop longues périodes
    jour = debut
    while jour <= aujourd_hui + dt.timedelta(days=14):
        fin = jour + dt.timedelta(days=6)
        try:
            for h in client.homework(jour, fin):
                elements.append((matiere(h.subject.name if h.subject else ""), "Devoirs", h.date,
                                 "Devoir", h, h.description or ""))
        except Exception as err:
            print("Koofr : devoirs illisibles du", jour, "au", fin, ":", err)
        jour = fin + dt.timedelta(days=1)
    # cahier de textes, semaine par semaine, du plus récent au plus ancien.
    # Dès que Pronote refuse (cours de l'ancienne classe), on s'arrête : il bloquerait ensuite tout le reste.
    fin = aujourd_hui
    while fin >= debut:
        jour = max(fin - dt.timedelta(days=6), debut)
        try:
            cours = client.lessons(jour, fin)
        except Exception as err:
            print("Koofr : cahier de textes inaccessible avant le", fin, "→ arrêt ici (", err, ")")
            break
        refus = 0
        for c in cours:
            try:   # le contenu du cours est lu à la demande : Pronote peut le refuser
                if c.canceled:
                    continue
                contenu = c.content
                if not contenu:
                    continue
                theme = propre(contenu.title) if contenu.title else "Cours"
                elements.append((matiere(c.subject.name if c.subject else ""), theme, c.start.date(),
                                 contenu.title or "Cours", contenu, contenu.description or ""))
            except Exception:
                refus += 1
        if refus:
            print(f"Koofr : semaine du {jour} : {refus} contenu(s) refusé(s) (ancienne classe ?) → arrêt ici")
            break
        fin = jour - dt.timedelta(days=1)

    envoyes, liens_par_dossier, stats = 0, {}, {}
    for mat, theme, date, source, objet, texte in elements:
        st = stats.setdefault(mat, {"fichiers": 0, "envoyes": 0, "liens": 0})
        try:
            pjs = list(getattr(objet, "files", None) or [])   # lu à la demande, peut être refusé
        except Exception as err:
            print("Koofr : pièces jointes illisibles :", mat, date, err)
            continue
        st["fichiers"] += len([f for f in pjs if getattr(f, "type", 1) != 0])
        dossier = f"{RACINE}/{mat}/Pronote/{propre(theme)}"
        for url in URL_RE.findall(texte):
            liens_par_dossier.setdefault(dossier, {})[url] = {"url": url, "titre": url, "date": str(date), "source": source}
        for f in pjs:
            try:
                if getattr(f, "type", 1) == 0:  # lien
                    url = f.url if "://" in f.url else "https://" + f.url
                    liens_par_dossier.setdefault(dossier, {})[url] = {
                        "url": url, "titre": (f.name or url), "date": str(date), "source": source}
                    continue
                nom = propre(f.name or "fichier")
                base, ext = os.path.splitext(nom)
                nom_final = base + ".pdf" if ext.lower().lstrip(".") in OFFICE_VERS_PDF else nom
                ancien = f"{dossier}/{nom_final}"              # ancien nom, sans date
                nom = f"{date:%Y-%m-%d} - {nom}"              # date en tête : tri chronologique sur la Kindle
                nom_final = f"{date:%Y-%m-%d} - {nom_final}"
                chemin = f"{dossier}/{nom_final}"
                if k.existe(chemin):
                    continue
                if k.existe(ancien):
                    k.supprimer(ancien)
                data = f.data
                if not data or len(data) > TAILLE_MAX:
                    continue
                nom_final, data = _convertir(nom, data, vers_pdf)
                k.envoyer(f"{dossier}/{nom_final}", data)
                envoyes += 1
                st["envoyes"] += 1
            except Exception as err:
                print("Koofr : pièce jointe ignorée", getattr(f, "name", "?"), err)

    for dossier, liens in liens_par_dossier.items():
        try:
            k.envoyer(f"{dossier}/Liens et vidéos.html", _page_liens(liens.values()))
        except Exception as err:
            print("Koofr : page de liens impossible", dossier, err)
    for mat in sorted(stats):
        try:
            k.creer_dossiers(f"{RACINE}/{mat}/Pronote")   # le dossier de la matière existe même sans document
        except Exception as err:
            print("Koofr : dossier impossible pour", mat, err)
        print(f"Koofr : {mat} → {stats[mat]['fichiers']} fichier(s) trouvé(s) sur Pronote, {stats[mat]['envoyes']} nouveau(x) envoyé(s)")
    print(f"Koofr : {envoyes} nouveau(x) document(s) Pronote, {len(liens_par_dossier)} page(s) de liens "
          f"(période {debut} → {aujourd_hui}, {len(elements)} cours/devoirs examinés)")
