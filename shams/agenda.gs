
/* ====================== Agenda de Shams (écran de veille Kindle) ======================
 * Rassemble les évaluations, dictées, quiz, projets et devoirs à venir depuis :
 *   - le calendrier mensuel des évaluations (PDF joint aux annonces du cours « Projets… »)
 *   - les devoirs Classroom qui ont une date limite (ex. Anglais)
 *   - les dates écrites dans les annonces et consignes (« pour mercredi 18 dictée », « Wednesday, November 25 »)
 * et les derniers thèmes étudiés en Maths et Français (devoirs sans date = leçons vues en classe).
 * Résultat : /Agenda-Shams/agenda.json sur Koofr, lu par GitHub qui fabrique l'image.
 */
const AGENDA_KOOFR = '/Agenda-Shams';
const HEURES_AGENDA = [6, 15, 17];          // avant les publications GitHub de 8 h 05, 16 h et 18 h 30
const COURS_THEMES = ['Maths', 'Français']; // devoirs sans date = thèmes étudiés en classe

const JOURS_FR_ = ['dimanche', 'lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi'];
const JOURS_EN_ = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'];
const MOIS_FR_ = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];
const MOIS_EN_ = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'];
const MATIERES_TEXTE_ = [
  [/math/i, 'Maths'], [/fran[cç]ais|dict[ée]e(?!.*english)|po[ée]sie|lecture|conjugaison|grammaire/i, 'Français'],
  [/g[ée]ograph/i, 'Géographie'], [/histoire/i, 'Histoire'], [/sciences?\b|science test/i, 'Sciences'],
  [/anglais|english/i, 'Anglais'], [/arabe|arabic/i, 'Arabe'], [/emc/i, 'EMC'],
];

function installerAgenda() {
  ScriptApp.getProjectTriggers().filter(t => t.getHandlerFunction() === 'agenda').forEach(t => ScriptApp.deleteTrigger(t));
  HEURES_AGENDA.forEach(h => ScriptApp.newTrigger('agenda').timeBased().atHour(h).everyDays(1).inTimezone('Asia/Dubai').create());
  console.log('Agenda programmé vers ' + HEURES_AGENDA.join(' h, ') + ' h ✔');
}

function agenda() {
  const tz = 'Asia/Dubai';
  const aujourdhui = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');
  const items = [], themes = [], journal = [];
  const cours = coursActifs_().filter(c => !exclu_(c));

  for (const c of cours) {
    const mat = matiere_(c);
    let profs = null;
    try { profs = profsDuCours_(c.id); } catch (e) {}

    // 1) Calendrier mensuel des évaluations (PDF / document en tableau)
    if (/^Projets/i.test(c.name)) {
      try { calendrierEvaluations_(c, items, journal); } catch (e) { journal.push('⚠ calendrier : ' + e.message); }
    }

    // 2) Devoirs Classroom
    let travaux = [];
    try { travaux = toutesPages_(o => Classroom.Courses.CourseWork.list(c.id, o), 'courseWork'); } catch (e) { journal.push('⚠ ' + mat + ' devoirs : ' + e.message); }
    for (const w of travaux) {
      const texte = (w.title || '') + ' ' + (w.description || '');
      if (w.dueDate) {
        const d = isoDe_(w.dueDate.year, w.dueDate.month, w.dueDate.day);
        items.push({ date: d, matiere: mat, type: typeDe_(texte), texte: propreTitre_(w.title), source: 'devoir' });
      } else if (COURS_THEMES.indexOf(mat) >= 0) {
        themes.push({ matiere: mat, titre: propreTitre_(w.title), date: w.creationTime.slice(0, 10) });
      } else {
        // pas de date limite : chercher une date dans la consigne (« Deadline: the week of 7 to 11 December »)
        const sem = semaineDe_(w.description || '', w.creationTime);
        if (sem) items.push({ date: sem.fin, quand: sem.libelle, matiere: mat, type: typeDe_(texte), texte: propreTitre_(w.title), source: 'devoir' });
        else datesDansTexte_(w.description || '', w.creationTime).forEach(x =>
          items.push({ date: x.date, matiere: mat, type: typeDe_(x.segment + ' ' + w.title), texte: propreTitre_(w.title), source: 'consigne' }));
      }
    }

    // 3) Annonces des enseignants : dates écrites dans le texte
    let annonces = [];
    try { annonces = toutesPages_(o => Classroom.Courses.Announcements.list(c.id, o), 'announcements'); } catch (e) {}
    const limite = new Date(Date.now() - 45 * 864e5).toISOString();
    for (const a of annonces) {
      if (a.creationTime < limite) continue;
      if (profs && !profs.has(a.creatorUserId)) continue;
      for (const x of datesDansTexte_(a.text || '', a.creationTime)) {
        const type = typeDe_(x.segment);
        if (type === 'Devoir' && !/pour|for|réviser|reviser|revise|apprendre|lire|lisez|écoute|ecoute|prépar|prepar/i.test(x.segment)) continue;
        const matTexte = /^Projets/i.test(c.name) ? (matiereDansTexte_(x.segment) || 'Classe') : mat;
        items.push({ date: x.date, matiere: matTexte, type: type, texte: resume_(x.segment), source: 'annonce' });
      }
    }
  }

  // Garder l'utile : à venir (aujourd'hui inclus, retiré à 8 h au moment de l'affichage), sans doublons
  const vus = {}, garder = [];
  items.filter(i => i.date && i.date >= aujourdhui)
    .sort((a, b) => (a.date + prio_(a.source)).localeCompare(b.date + prio_(b.source)))
    .forEach(i => {
      const cle = i.date + '|' + i.matiere + '|' + i.type;
      if (vus[cle]) return;
      vus[cle] = 1; garder.push(i);
    });
  const derniersThemes = themes.sort((a, b) => b.date.localeCompare(a.date)).filter((t, i, l) =>
    l.findIndex(u => u.matiere === t.matiere && u.titre === t.titre) === i).slice(0, 10);

  const resultat = { maj: new Date().toISOString(), items: garder, themes: derniersThemes, journal: journal };
  creerDossiers_(AGENDA_KOOFR);
  envoyerTexte_(AGENDA_KOOFR, 'agenda.json', JSON.stringify(resultat, null, 1));
  console.log(garder.map(i => i.date + ' ' + (i.quand || '') + ' ' + i.matiere + ' [' + i.type + '] ' + i.texte + '  (' + i.source + ')').join('\n'));
  console.log('Thèmes : ' + derniersThemes.map(t => t.matiere + ' ' + t.titre).join(' / '));
  if (journal.length) console.log(journal.join('\n'));
}

function prio_(source) { return { calendrier: '1', devoir: '2', annonce: '3', consigne: '4' }[source] || '9'; }

/* ---------- Calendrier mensuel (tableau : ligne des jours, puis ligne du contenu) ---------- */
function calendrierEvaluations_(c, items, journal) {
  const annonces = toutesPages_(o => Classroom.Courses.Announcements.list(c.id, o), 'announcements');
  const fichiers = [];
  annonces.forEach(a => (a.materials || []).forEach(m => {
    if (m.driveFile && /programme|calendrier|planning|évaluations|evaluations/i.test(m.driveFile.driveFile.title)) fichiers.push({ f: m.driveFile.driveFile, quand: a.creationTime });
  }));
  fichiers.sort((a, b) => b.quand.localeCompare(a.quand));
  fichiers.slice(0, 2).forEach(({ f, quand }) => {
    const lignes = tableauDe_(f.id);
    const annee = Number(quand.slice(0, 4)), moisAnnonce = Number(quand.slice(5, 7));
    let datesLigne = [];
    for (const cellules of lignes) {
      const enTete = cellules.map(x => x.match(/^(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+(\d{1,2})\/(\d{1,2})\s*(.*)$/i));
      if (enTete.some(Boolean)) {
        datesLigne = enTete.map(m => m ? isoDe_(Number(m[3]) < moisAnnonce - 6 ? annee + 1 : annee, Number(m[3]), Number(m[2])) : null);
        enTete.forEach((m, k) => { if (m && m[4].trim()) ajouterCase_(datesLigne[k], m[4], items); });
      } else {
        cellules.forEach((x, k) => { if (x && datesLigne[k]) ajouterCase_(datesLigne[k], x, items); });
      }
    }
    journal.push('calendrier lu : ' + f.title);
  });
}

function ajouterCase_(date, texte, items) {
  // une case peut contenir plusieurs choses : « Dictée n°5 Mon voisin Totoro Visite médicale des CM2 »
  const morceaux = texte.split(/(?=\b(?:[ÉE]valuation|Dict[ée]e|Po[ée]sie|Visite|Sortie|Quiz|Contr[ôo]le|Spectacle|Photo)\b)/i).map(s => s.trim()).filter(Boolean);
  morceaux.forEach(m => {
    const type = typeDe_(m);
    let mat = matiereDansTexte_(m) || (type === 'Dictée' || type === 'Poésie' ? 'Français' : 'Classe');
    let detail = m.replace(/^[ÉE]valuation\s+(de|d'|en)\s+\S+\s*/i, '').replace(/^Dict[ée]e\s*/i, '').replace(/^Po[ée]sie\s*/i, '').trim();
    items.push({ date: date, matiere: mat, type: type === 'Devoir' ? 'Info' : type, texte: detail || m, source: 'calendrier' });
  });
}

function tableauDe_(idFichier) {
  const meta = Drive.Files.get(idFichier, { fields: 'mimeType' });
  let idDoc = idFichier, temporaire = null;
  if (meta.mimeType !== 'application/vnd.google-apps.document') {
    temporaire = Drive.Files.copy({ name: 'tmp-kindle-ocr', mimeType: 'application/vnd.google-apps.document' }, idFichier);
    idDoc = temporaire.id;
  }
  try {
    const r = UrlFetchApp.fetch('https://www.googleapis.com/drive/v3/files/' + idDoc + '/export?mimeType=text%2Fhtml',
      { headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() } });
    const h = r.getContentText();
    return (h.match(/<tr[\s\S]*?<\/tr>/g) || []).map(tr => (tr.match(/<td[\s\S]*?<\/td>/g) || []).map(td => texteHtml_(td)));
  } finally {
    if (temporaire) try { Drive.Files.remove(temporaire.id); } catch (e) {}
  }
}

function texteHtml_(h) {
  const ent = { nbsp: ' ', amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", rsquo: "'", lsquo: "'", eacute: 'é', egrave: 'è', ecirc: 'ê', agrave: 'à',
    acirc: 'â', ccedil: 'ç', icirc: 'î', ocirc: 'ô', ucirc: 'û', ugrave: 'ù', deg: '°', Eacute: 'É', laquo: '«', raquo: '»', euml: 'ë', iuml: 'ï' };
  return h.replace(/<[^>]+>/g, ' ').replace(/&#(\d+);/g, (_, n) => String.fromCharCode(n))
    .replace(/&(\w+);/g, (m, n) => ent[n] !== undefined ? ent[n] : m).replace(/''/g, "'").replace(/\s+/g, ' ').trim();
}

/* ---------- Dates écrites dans un texte ---------- */
// Renvoie [{date, segment}] : « pour lundi 16 … », « jeudi 19 novembre », « Wednesday, November 25 »
function datesDansTexte_(texte, creation) {
  const t = String(texte || '').replace(/\s+/g, ' ');
  const re = new RegExp('\\b(' + JOURS_FR_.join('|') + '|' + JOURS_EN_.join('|') + ')\\s*,?\\s*(?:(\\d{1,2})(?:er)?\\s*(' + MOIS_FR_.join('|') +
    '|' + MOIS_EN_.join('|') + ')?|(' + MOIS_EN_.join('|') + ')\\s+(\\d{1,2}))', 'gi');
  const trouves = [];
  let m;
  while ((m = re.exec(t)) !== null) {
    const jour = m[1].toLowerCase();
    const jsem = JOURS_FR_.indexOf(jour) >= 0 ? JOURS_FR_.indexOf(jour) : JOURS_EN_.indexOf(jour);
    const num = Number(m[2] || m[5]);
    if (!num) continue;
    const moisNom = (m[3] || m[4] || '').toLowerCase();
    const mois = moisNom ? (MOIS_FR_.indexOf(moisNom) >= 0 ? MOIS_FR_.indexOf(moisNom) : MOIS_EN_.indexOf(moisNom)) : -1;
    const date = resoudreDate_(jsem, num, mois, creation);
    if (date) trouves.push({ date: date, debut: m.index });
  }
  // segment = depuis « pour » juste avant la date (ou le début de la phrase) jusqu'à la date suivante
  const bas = t.toLowerCase();
  return trouves.map((x, i) => {
    const pour = bas.lastIndexOf('pour ', x.debut);
    const point = Math.max(t.lastIndexOf('.', x.debut), t.lastIndexOf('!', x.debut)) + 1;
    const debut = pour >= 0 && pour >= x.debut - 8 ? pour : point;
    let fin = i + 1 < trouves.length ? trouves[i + 1].debut : t.length;
    const pourSuivant = bas.lastIndexOf('pour ', fin);
    if (i + 1 < trouves.length && pourSuivant > x.debut && pourSuivant >= fin - 8) fin = pourSuivant;
    return { date: x.date, segment: t.slice(debut, Math.min(fin, x.debut + 260)).trim() };
  });
}

// Jour de la semaine + numéro (+ mois) : la date réelle la plus proche, autour de la date de publication.
// Si le numéro ne correspond pas au jour (« mercredi 24 »), on garde le bon jour de la semaine le plus proche.
function resoudreDate_(jsem, num, mois, creation) {
  const base = new Date(creation);
  let meilleure = null, ecart = 99;
  for (let k = -10; k <= 75; k++) {
    const d = new Date(base.getTime() + k * 864e5);
    if (d.getUTCDay() !== jsem) continue;
    if (mois >= 0 && Math.abs(d.getUTCMonth() - mois) > 1 && Math.abs(d.getUTCMonth() - mois) < 11) continue;
    let e = Math.abs(d.getUTCDate() - num);
    if (mois >= 0 && d.getUTCMonth() !== mois) e += 3;
    if (e < ecart) { ecart = e; meilleure = d; }
  }
  return meilleure && ecart <= 3 ? meilleure.toISOString().slice(0, 10) : null;
}

// « the week of 7 to 11 December » / « semaine du 7 au 11 décembre »
function semaineDe_(texte, creation) {
  const m = String(texte).match(new RegExp('(?:week of|semaine du)\\s+(\\d{1,2})\\s*(?:to|au|-|–)\\s*(\\d{1,2})\\s*(' + MOIS_FR_.join('|') + '|' + MOIS_EN_.join('|') + ')', 'i'));
  if (!m) return null;
  const nom = m[3].toLowerCase();
  const mois = MOIS_FR_.indexOf(nom) >= 0 ? MOIS_FR_.indexOf(nom) : MOIS_EN_.indexOf(nom);
  const annee = Number(creation.slice(0, 4)) + (mois + 1 < Number(creation.slice(5, 7)) - 6 ? 1 : 0);
  return { fin: isoDe_(annee, mois + 1, Number(m[2])), libelle: 'sem. ' + m[1] + '–' + m[2] + ' ' + ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'][mois] };
}

/* ---------- Petits outils ---------- */
function typeDe_(t) {
  t = String(t || '');
  if (/dict[ée]e|dictation/i.test(t)) return 'Dictée';
  if (/quiz/i.test(t)) return 'Quiz';
  if (/[ée]valuation|evaluation|\btest\b|contr[ôo]le|interro|exam/i.test(t)) return 'Évaluation';
  if (/po[ée]sie|r[ée]citation/i.test(t)) return 'Poésie';
  if (/projet|project|expos[ée]/i.test(t)) return 'Projet';
  return 'Devoir';
}
function matiereDansTexte_(t) { for (const [re, nom] of MATIERES_TEXTE_) if (re.test(t)) return nom; return null; }
function propreTitre_(t) { return String(t || '').replace(/\s+/g, ' ').trim(); }
function resume_(t) { t = String(t || '').replace(/\s+/g, ' ').trim(); return t.length > 160 ? t.slice(0, 160).replace(/\s\S*$/, '') + ' …' : t; }
function isoDe_(a, m, j) { return a + '-' + ('0' + m).slice(-2) + '-' + ('0' + j).slice(-2); }
