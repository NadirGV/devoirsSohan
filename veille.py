"""Écran de veille Kindle : version condensée de la page des devoirs, rendue en image PNG
au format de l'écran (niveaux de gris), publiée à côté de la page : <slug>/ecran-veille.png
"""
import datetime as dt
import html
import os
import re
import shutil
import subprocess
import tempfile

LARGEUR, HAUTEUR = 1236, 1648        # Kindle Paperwhite (KOReader adapte si besoin)
MAX_CAR = 170                         # longueur max d'une consigne
JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
           "septembre", "octobre", "novembre", "décembre"]

CSS = f"""
@page {{ size: {LARGEUR}px {HAUTEUR}px; margin: 0 }}
* {{ box-sizing: border-box }}
html, body {{ margin: 0; width: {LARGEUR}px; height: {HAUTEUR}px; overflow: hidden;
  background: #fff; color: #000; font-family: 'DejaVu Sans', Arial, sans-serif; }}
body {{ padding: 56px 64px; }}
h1 {{ font-size: 64px; margin: 0; letter-spacing: -1px }}
.maj {{ font-size: 26px; color: #444; margin: 6px 0 28px }}
h2 {{ font-size: 40px; margin: 30px 0 12px; padding-bottom: 6px; border-bottom: 4px solid #000 }}
.d {{ font-size: 31px; line-height: 1.28; margin: 0 0 16px; padding-left: 18px; border-left: 8px solid #000 }}
.d.fait {{ border-left-color: #bbb; color: #777 }}
.m {{ font-weight: bold }}
.ok {{ font-weight: normal; font-size: 26px }}
.vide {{ font-size: 30px; color: #555; font-style: italic }}
.ctl {{ font-size: 31px; line-height: 1.3; margin: 0 0 8px }}
.edt {{ font-size: 28px; line-height: 1.45; columns: 2; column-gap: 40px }}
.edt .annule {{ text-decoration: line-through; color: #777 }}
.pied {{ position: absolute; bottom: 36px; left: 64px; right: 64px; font-size: 24px; color: #555;
  border-top: 2px solid #999; padding-top: 10px }}
"""


def _date_fr(d):
    return f"{JOURS_FR[d.weekday()]} {d.day} {MOIS_FR[d.month - 1]}"


def _texte(t):
    t = re.sub(r"<[^>]+>", " ", t or "")
    t = html.unescape(t)
    t = re.sub(r"https?://\S+|www\.\S+", "[lien]", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= MAX_CAR else t[:MAX_CAR].rsplit(" ", 1)[0] + " …"


def _jours_de_cours(depuis, n):
    jours, d = [], depuis
    while len(jours) < n:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            jours.append(d)
    return jours


def html_veille(data, tz, classer):
    e = html.escape
    maintenant = dt.datetime.now(tz)
    today = maintenant.date()
    maj = dt.datetime.fromisoformat(data["maj"])
    jours = _jours_de_cours(today, 2)

    out = ["<!doctype html><html lang='fr'><head><meta charset='utf-8'><style>", CSS, "</style></head><body>",
           "<h1>Devoirs de Sohan</h1>",
           f"<div class='maj'>Mis à jour {e(_date_fr(maj.date()))} à {maj:%H:%M}</div>"]

    for j in jours:
        items = [h for h in data["devoirs"] if h["date"] == j.isoformat()]
        ecart = (j - today).days
        titre = "Pour demain" if ecart == 1 else f"Pour {_date_fr(j)}"
        out.append(f"<h2>{e(titre)}</h2>")
        if not items:
            out.append("<div class='vide'>Rien de noté.</div>")
        for h in sorted(items, key=lambda h: h["matiere"]):
            ok = " <span class='ok'>✓ fait</span>" if h["fait"] else ""
            out.append(f"<div class='d{' fait' if h['fait'] else ''}'><span class='m'>{e(h['matiere'])}</span>{ok}"
                       f" — {e(_texte(h['texte']))}</div>")

    # Contrôles et évaluations des 7 prochains jours
    ctl = {}
    for t in data.get("ds", []):
        ctl[(t["date"], t["matiere"])] = t.get("genre", "ds")
    for h in data["devoirs"]:
        g = classer(h["texte"])
        if g:
            ctl.setdefault((h["date"], h["matiere"]), g)
    limite = today + dt.timedelta(days=7)
    proches = sorted(k for k in ctl if today <= dt.date.fromisoformat(k[0]) <= limite)
    out.append("<h2>Contrôles de la semaine</h2>")
    if not proches:
        out.append("<div class='vide'>Aucun contrôle prévu.</div>")
    for jour, mat in proches[:6]:
        d = dt.date.fromisoformat(jour)
        ecart = (d - today).days
        quand = {0: "aujourd'hui", 1: "demain"}.get(ecart, _date_fr(d))
        genre = "évaluation" if ctl[(jour, mat)] == "eval" else "contrôle"
        out.append(f"<div class='ctl'><b>{e(mat)}</b> — {e(genre)} {e(quand)}</div>")

    if data.get("edt"):
        d = dt.date.fromisoformat(data["edt_date"])
        out.append(f"<h2>Emploi du temps — {e(_date_fr(d))}</h2><div class='edt'>")
        for c in data["edt"]:
            cls = " class='annule'" if c["annule"] else ""
            out.append(f"<div{cls}>{e(c['debut'].replace(':', ' h '))}  {e(c['matiere'])}</div>")
        out.append("</div>")

    # La suite des devoirs : on ajoute tous les jours suivants, puis le script ci-dessous retire
    # ce qui dépasse en bas de l'écran (au-dessus du pied de page).
    deja = {j.isoformat() for j in jours}
    suite = sorted({h["date"] for h in data["devoirs"] if h["date"] > today.isoformat() and h["date"] not in deja})
    for jour in suite:
        d = dt.date.fromisoformat(jour)
        out.append(f"<h2 class='remplir'>Pour {e(_date_fr(d))}</h2>")
        for h in sorted((h for h in data["devoirs"] if h["date"] == jour), key=lambda h: h["matiere"]):
            ok = " <span class='ok'>✓ fait</span>" if h["fait"] else ""
            out.append(f"<div class='d remplir{' fait' if h['fait'] else ''}'><span class='m'>{e(h['matiere'])}</span>{ok}"
                       f" — {e(_texte(h['texte']))}</div>")

    out.append("<div class='pied'>Page complète : ouvre le favori « Devoirs » dans le navigateur.</div>")
    out.append("""<script>
(function () {
  var limite = document.querySelector('.pied').getBoundingClientRect().top - 12;
  var els = Array.prototype.slice.call(document.querySelectorAll('.remplir'));
  while (els.length && els[els.length - 1].getBoundingClientRect().bottom > limite) els.pop().remove();
  // pas de titre de jour orphelin en bas
  while (els.length && els[els.length - 1].tagName === 'H2') els.pop().remove();
})();
</script>""")
    out.append("</body></html>")
    return "\n".join(out)


def _chrome():
    for nom in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        p = shutil.which(nom)
        if p:
            return p
    return None


def generer(data, tz, classer, dossier):
    """Écrit dossier/ecran-veille.html et dossier/ecran-veille.png. Ne lève jamais d'erreur."""
    try:
        page = os.path.join(dossier, "ecran-veille.html")
        with open(page, "w", encoding="utf-8") as f:
            f.write(html_veille(data, tz, classer))
        chrome = _chrome()
        if not chrome:
            print("Écran de veille : Chrome introuvable, image non générée")
            return
        brut = os.path.join(tempfile.mkdtemp(), "capture.png")
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
                        "--force-device-scale-factor=1", f"--window-size={LARGEUR},{HAUTEUR}",
                        f"--screenshot={brut}", "file://" + os.path.abspath(page)],
                       check=True, timeout=90, capture_output=True)
        from PIL import Image
        img = Image.open(brut).convert("L")
        if img.size != (LARGEUR, HAUTEUR):
            img = img.crop((0, 0, LARGEUR, HAUTEUR))
        img.save(os.path.join(dossier, "ecran-veille.png"), optimize=True)
        print("Écran de veille : image générée")
    except Exception as err:
        print("Écran de veille : étape ignorée suite à une erreur :", err)
