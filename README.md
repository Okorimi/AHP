# Sélection de candidats par la méthode AHP

Application Streamlit d'aide à la décision : le recruteur compare critères et candidats deux par deux,
l'application calcule les poids, contrôle la cohérence, classe les candidats et envoie le rapport par e-mail.

## Lancer l'application

Python 3.11 ou plus récent est requis.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Identifiants de test : `youssouf` / `safi2026`. Le bouton **Charger un exemple** remplit une évaluation complète.

## Activer l'envoi d'e-mail

Le rapport part toujours vers `ab.ysf.ghni@gmail.com`. Il faut seulement fournir un compte d'envoi :

1. Copiez `.streamlit/secrets.toml.example` vers `.streamlit/secrets.toml`.
2. Renseignez `host`, `port`, `username`, `password` et `sender`.
3. Avec Gmail, activez la validation en deux étapes puis utilisez un mot de passe d'application.
4. Relancez l'application.

Ce fichier contient un secret : il est exclu de Git par `.gitignore`. Les variables d'environnement
`SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SENDER` et `SMTP_SECURITY` sont aussi acceptées.

## Organisation du code

| Fichier | Rôle |
|---|---|
| `app.py` | Interface Streamlit |
| `ahp_core.py` | Matrices, vecteur propre, CI, CR, suggestions, classement |
| `charts.py` | Graphiques Plotly |
| `report.py` | Rapport texte, HTML et PDF |
| `mailer.py` | Envoi avec `smtplib` et `email.mime` |
| `auth.py` | Vérification du mot de passe haché (PBKDF2) |
| `tests/` | Tests du moteur (`pip install pytest`, puis `pytest`) |

## Méthode

Pour n éléments, seules n(n-1)/2 comparaisons sont saisies ; chaque inverse est calculé (a_ji = 1 / a_ij).
Les poids viennent du vecteur propre principal. `CI = (λmax - n) / (n - 1)` et `CR = CI / RI`, avec les
indices aléatoires de Saaty. Au-delà de `CR = 0,10`, l'application signale le jugement incohérent et propose
les corrections qui réduisent le plus le ratio. Score global = somme (poids du critère x priorité du candidat).

## Limites

- De 2 à 15 critères et de 2 à 15 candidats.
- Les données restent en mémoire pendant la session : recharger la page déconnecte et efface la saisie.
- Le PDF utilise une police latine : l'alphabet arabe n'y est pas pris en charge (l'interface et l'e-mail HTML le sont).
