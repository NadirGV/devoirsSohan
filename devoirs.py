"""Récupère les devoirs Pronote des prochains jours et génère une page lisible sur Kindle.

Variables d'environnement (à mettre dans les secrets GitHub) :
  PRONOTE_URL       adresse Pronote de l'école (…/pronote/eleve.html ou parent.html)
  PRONOTE_USER      identifiant
  PRONOTE_PASS      mot de passe
  PRONOTE_ENT       (facultatif) nom de l'ENT dans pronotepy.ent, ex. ac_paris
  PRONOTE_CHILD     (facultatif) prénom de l'enfant, si compte parent
  PAGE_SLUG         chemin secret de la page, ex. 7f3k9q2m
Options : --demo  génère la page avec des données d'exemple (sans Pronote).
"""
import datetime as dt
import html
import json
import os
import re
import sys
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


def fetch():
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

    today = dt.datetime.now(TZ).date()
    devoirs = []
    for h in client.homework(today, today + dt.timedelta(days=JOURS)):
        devoirs.append({
            "date": h.date.isoformat(),
            "matiere": h.subject.name if h.subject else "Autre",
            "couleur": h.background_color or "",
            "texte": h.description or "",
            "fait": bool(h.done),
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
    ds = []
    for c in client.lessons(today, today + dt.timedelta(days=JOURS)):
        if c.canceled:
            continue
        contenu = c.content
        cat = " ".join(filter(None, [getattr(contenu, "category", None), getattr(contenu, "title", None)])) if contenu else ""
        genre = classer(cat) or ("ds" if getattr(c, "test", False) else None)
        if genre:
            ds.append({"date": c.start.date().isoformat(), "heure": c.start.strftime("%H:%M"),
                       "matiere": c.subject.name if c.subject else "", "texte": cat.strip(), "genre": genre})
    return {"maj": dt.datetime.now(TZ).isoformat(), "devoirs": devoirs, "ds": ds,
            "edt_date": demain.isoformat(), "edt": cours}


def demo():
    today = dt.datetime.now(TZ).date()
    d = lambda n: (today + dt.timedelta(days=n)).isoformat()
    return {"maj": dt.datetime.now(TZ).isoformat(), "edt_date": d(1), "devoirs": [
        {"date": d(1), "matiere": "ESPAGNOL", "couleur": "#e6a23c", "texte": "Apprendre le vocabulaire du Día de Muertos (fiche + mots croisés). Contrôle.", "fait": False},
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
"""


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
            texte = f"<div class='t'>{e(t['texte'].strip())}</div>" if t["texte"] else ""
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
            texte = e(h["texte"].strip()).replace("\n", "<br>")
            out.append(f"<div class='{cls}' style='border-left-color:{couleur}'>"
                       f"<div class='m'>{e(h['matiere'])}{ok}</div><div class='t'>{texte}</div></div>")

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
    data = demo() if "--demo" in sys.argv else fetch()
    slug = os.environ.get("PAGE_SLUG", "demo").strip().strip("/")
    os.makedirs(f"site/{slug}", exist_ok=True)
    with open(f"site/{slug}/index.html", "w", encoding="utf-8") as f:
        f.write(render(data))
    with open("site/index.html", "w", encoding="utf-8") as f:
        f.write("<!doctype html><meta name='robots' content='noindex'><title>.</title>")
    with open("site/robots.txt", "w") as f:
        f.write("User-agent: *\nDisallow: /\n")
    print(f"{len(data['devoirs'])} devoirs, {len(data.get('edt', []))} cours")


if __name__ == "__main__":
    main()
