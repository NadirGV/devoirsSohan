"""Écran de veille Kindle de Shams.

L'agenda est préparé chaque jour par le script Google de Shams (shams/agenda.gs), qui lit son
Classroom (calendrier des évaluations, devoirs datés, annonces) et dépose /Agenda-Shams/agenda.json
sur Koofr. Ici on le récupère et on publie <slug>/shams/ecran-veille.png (+ .html).

Règle d'affichage : ce qui est prévu pour un jour reste affiché jusqu'à 8 h le matin même.
Variables d'environnement : KOOFR_USER, KOOFR_PASS, PAGE_SLUG.
"""
import datetime as dt
import html
import json
import os
import shutil
import subprocess
import tempfile
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("Asia/Dubai")
LARGEUR, HAUTEUR = 1272, 1696
LIMITE_MATIN = dt.time(8, 0)
MAX_CAR = 230
AGENDA = "https://app.koofr.net/dav/Koofr/Agenda-Shams/agenda.json"
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
JOURS_COURTS = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]

CSS = f"""
* {{ box-sizing: border-box }}
html, body {{ margin: 0; width: {LARGEUR}px; height: {HAUTEUR}px; overflow: hidden; background: #fff; color: #000;
  font-family: 'DejaVu Sans', Arial, sans-serif }}
body {{ padding: 56px 64px }}
h1 {{ font-size: 64px; margin: 0; letter-spacing: -1px }}
.maj {{ font-size: 26px; color: #444; margin: 6px 0 24px }}
h2 {{ font-size: 40px; margin: 28px 0 12px; padding-bottom: 6px; border-bottom: 4px solid #000 }}
.d {{ font-size: 31px; line-height: 1.28; margin: 0 0 14px; padding-left: 18px; border-left: 8px solid #000 }}
.d.info {{ border-left-color: #999 }}
.m, .q {{ font-weight: bold }}
.t {{ font-weight: bold; text-transform: uppercase; font-size: 23px; border: 2px solid #000; padding: 0 6px;
  border-radius: 6px; vertical-align: 3px; white-space: nowrap }}
.vide {{ font-size: 30px; color: #555; font-style: italic }}
.r {{ font-size: 28px; line-height: 1.35; margin: 0 0 6px }}
.x {{ color: #555; font-size: 24px }}
.pied {{ position: absolute; bottom: 36px; left: 64px; right: 64px; font-size: 24px; color: #555;
  border-top: 2px solid #999; padding-top: 10px }}
"""


def date_fr(d):
    return f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]}"


def court(t):
    t = " ".join(str(t or "").split())
    return t if len(t) <= MAX_CAR else t[:MAX_CAR].rsplit(" ", 1)[0] + " …"


def prochain_jour_de_cours(d):
    d += dt.timedelta(days=1)
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d


def charger_agenda():
    user, mdp = os.environ.get("KOOFR_USER", "").strip(), os.environ.get("KOOFR_PASS", "").strip()
    r = requests.get(AGENDA, auth=(user, mdp), timeout=30)
    r.raise_for_status()
    return r.json()


def html_ecran(agenda, maintenant):
    e = html.escape
    today = maintenant.date()
    avant_8h = maintenant.time() < LIMITE_MATIN
    items = []
    for i in agenda.get("items", []):
        d = dt.date.fromisoformat(i["date"])
        if d > today or (d == today and avant_8h):
            items.append(dict(i, d=d))
    items.sort(key=lambda i: (i["d"], i["matiere"]))

    def ligne(i, avec_quand):
        cls = "d info" if i["type"] == "Info" else "d"
        quand = ""
        if avec_quand:
            quand = i.get("quand") or f"{JOURS_COURTS[i['d'].weekday()]} {i['d'].day}"
            quand = f"<span class='q'>{e(quand)}</span> "
        texte = court(i.get("texte"))
        return (f"<div class='{cls}'>{quand}<span class='m'>{e(i['matiere'])}</span> "
                f"<span class='t'>{e(i['type'])}</span>{(' — ' + e(texte)) if texte else ''}</div>")

    maj = dt.datetime.fromisoformat(agenda["maj"].replace("Z", "+00:00")).astimezone(TZ)
    out = ["<!doctype html><html lang='fr'><head><meta charset='utf-8'><style>", CSS, "</style></head><body>",
           "<h1>Devoirs de Shams</h1>",
           f"<div class='maj'>Mis à jour {e(date_fr(maj.date()))} à {maj:%H:%M}</div>"]

    deja = set()
    if avant_8h and any(i["d"] == today for i in items):
        out.append(f"<h2>Aujourd'hui — {e(date_fr(today))}</h2>")
        for i in items:
            if i["d"] == today:
                out.append(ligne(i, False)); deja.add(id(i))

    jour = prochain_jour_de_cours(today)
    titre = "Pour demain" if (jour - today).days == 1 else f"Pour {date_fr(jour)}"
    if (jour - today).days == 1:
        titre += f" — {date_fr(jour)}"
    out.append(f"<h2>{e(titre)}</h2>")
    du_jour = [i for i in items if i["d"] == jour]
    if not du_jour:
        out.append("<div class='vide'>Rien de prévu.</div>")
    for i in du_jour:
        out.append(ligne(i, False)); deja.add(id(i))

    reste = [i for i in items if id(i) not in deja and i["d"] > jour]
    out.append("<h2>À venir</h2>")
    if not reste:
        out.append("<div class='vide'>Rien d'autre de prévu pour l'instant.</div>")
    # les échéances « semaine du … » (sans jour précis) à la fin
    for i in sorted(reste, key=lambda i: (bool(i.get("quand")), i["d"], i["matiere"])):
        out.append(ligne(i, True))

    themes = agenda.get("themes", [])
    if themes:
        out.append("<h2 class='remplir'>Derniers thèmes étudiés en Maths et Français</h2>")
        for t in themes:
            d = dt.date.fromisoformat(t["date"])
            out.append(f"<div class='r remplir'><b>{e(t['matiere'])}</b> — {e(court(t['titre']))} "
                       f"<span class='x'>({d.day:02d}/{d.month:02d})</span></div>")

    out.append("<div class='pied'>D'après Classroom et le calendrier des évaluations.</div>")
    out.append("""<script>
(function () {
  var limite = document.querySelector('.pied').getBoundingClientRect().top - 12;
  var els = Array.prototype.slice.call(document.querySelectorAll('.remplir'));
  while (els.length && els[els.length - 1].getBoundingClientRect().bottom > limite) els.pop().remove();
  if (els.length === 1 && els[0].tagName === 'H2') els.pop().remove();   // titre seul : on l'enlève
})();
</script></body></html>""")
    return "\n".join(out)


def capturer(page, png):
    chrome = next((shutil.which(n) for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
                   if shutil.which(n)), None)
    if not chrome:
        raise RuntimeError("Chrome introuvable")
    brut = os.path.join(tempfile.mkdtemp(), "capture.png")
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
                    "--force-device-scale-factor=1", f"--window-size={LARGEUR},{HAUTEUR}",
                    f"--screenshot={brut}", "file://" + os.path.abspath(page)],
                   check=True, timeout=90, capture_output=True)
    from PIL import Image
    img = Image.open(brut).convert("L")
    if img.size != (LARGEUR, HAUTEUR):
        img = img.crop((0, 0, LARGEUR, HAUTEUR))
    img.save(png, optimize=True)


def main():
    slug = os.environ.get("PAGE_SLUG", "demo").strip().strip("/")
    dossier = f"site/{slug}/shams"
    os.makedirs(dossier, exist_ok=True)
    agenda = json.load(open(os.environ["AGENDA_FICHIER"], encoding="utf-8")) if os.environ.get("AGENDA_FICHIER") else charger_agenda()
    maintenant = dt.datetime.fromisoformat(os.environ["MAINTENANT"]).astimezone(TZ) if os.environ.get("MAINTENANT") else dt.datetime.now(TZ)
    page = os.path.join(dossier, "ecran-veille.html")
    with open(page, "w", encoding="utf-8") as f:
        f.write(html_ecran(agenda, maintenant))
    capturer(page, os.path.join(dossier, "ecran-veille.png"))
    print(f"Shams : écran de veille généré ({len(agenda.get('items', []))} éléments dans l'agenda)")


if __name__ == "__main__":
    main()
