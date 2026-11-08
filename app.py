"""Application Streamlit d'aide à la décision AHP pour le choix de candidats."""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime
from html import escape
from itertools import combinations
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import ahp_core as ahp
import charts
import report
from auth import DEFAULT_PASSWORD_HASH, DEFAULT_USERNAME, verify_credentials
from mailer import MailError, SmtpConfig, compose_message, send_message

REPORT_RECIPIENT = "ab.ysf.ghni@gmail.com"
TIMEZONE = ZoneInfo("Africa/Casablanca")
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 30
CRITERIA_SCOPE = "criteria"
STEPS = ["Préparer", "Pondérer les critères", "Évaluer les candidats", "Résultats"]
ADVERBS = {
    2: "à peine", 3: "modérément", 4: "nettement", 5: "fortement", 6: "très nettement",
    7: "très fortement", 8: "considérablement", 9: "extrêmement",
}

CSS = """
<style>
.block-container { padding-top: 2.4rem; max-width: 1240px; }
.ahp-lead { color: #5a6a7e; font-size: 1.05rem; max-width: 66ch; margin-top: -0.4rem; }
.ahp-progress { color: #5a6a7e; font-size: 0.92rem; margin-bottom: 0.25rem; }

.ahp-side { font-weight: 600; line-height: 1.25; padding: 0.35rem 0.5rem; border-radius: 6px; color: #5a6a7e; overflow-wrap: break-word; transition: background-color .15s, color .15s; }
.ahp-side.left { text-align: right; }
.ahp-side.on { background: #1f5fd0; color: #fff; }
.ahp-side.tie { color: #1b2a3d; }
.ahp-sentence { color: #5a6a7e; font-size: 0.9rem; text-align: center; margin-top: -0.35rem; }
.ahp-sentence strong { color: #1b2a3d; }

div[data-testid="stColumn"]:has(.ahp-sticky) { position: sticky; top: 3.75rem; align-self: flex-start; max-height: calc(100vh - 4.5rem); overflow-y: auto; padding-right: 0.25rem; }

.ahp-status { padding: 0.7rem 0.9rem; border-radius: 8px; border-left: 4px solid; margin-bottom: 0.8rem; line-height: 1.4; }
.ahp-status strong { display: block; font-size: 1.02rem; }
.ahp-status.ok { background: #e6f5ee; border-color: #1a8a5a; color: #0f5a39; }
.ahp-status.bad { background: #fdf0e8; border-color: #c2541a; color: #7d3009; }
.ahp-status.todo { background: #e9eff7; border-color: #8a94a3; color: #3f4e61; }

.ahp-w { margin-bottom: 0.55rem; }
.ahp-w-head { display: flex; justify-content: space-between; gap: 1rem; font-size: 0.95rem; }
.ahp-w-head span:last-child { font-weight: 700; font-variant-numeric: tabular-nums; }
.ahp-w-track { height: 7px; background: #e1e8f1; border-radius: 4px; }
.ahp-w-fill { height: 7px; background: #2a78d6; border-radius: 4px; }

.ahp-pills { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0.2rem 0 1rem; }
.ahp-pill { padding: 0.2rem 0.65rem; border-radius: 999px; font-size: 0.86rem; background: #e9eff7; color: #3f4e61; }
.ahp-pill.ok { background: #e6f5ee; color: #0f5a39; }
.ahp-pill.bad { background: #fdf0e8; color: #7d3009; }
.ahp-pill.current { outline: 2px solid #1f5fd0; }

.ahp-matrix-wrap { overflow-x: auto; }
table.ahp-matrix { border-collapse: collapse; font-size: 0.86rem; margin-bottom: 0.5rem; font-variant-numeric: tabular-nums; }
table.ahp-matrix th, table.ahp-matrix td { padding: 0.28rem 0.5rem; text-align: center; border: 1px solid #dde4ed; }
table.ahp-matrix th:first-child { text-align: left; max-width: 180px; font-weight: 600; }
table.ahp-matrix td.in { background: #dbe8fb; font-weight: 700; color: #123f8f; }
table.ahp-matrix td.auto { color: #5a6a7e; font-style: italic; }
table.ahp-matrix td.diag { background: #eef1f5; color: #5a6a7e; }
.ahp-legend { font-size: 0.85rem; color: #5a6a7e; }

.ahp-winner { background: #1f5fd0; color: #fff; padding: 1.6rem 2rem; border-radius: 10px; margin-bottom: 1.2rem; }
.ahp-winner-label { font-size: 1rem; opacity: 0.92; }
.ahp-winner-name { font-size: clamp(2.1rem, 5vw, 3.5rem); font-weight: 700; line-height: 1.08; margin: 0.15rem 0 0.5rem; overflow-wrap: anywhere; }
.ahp-winner-note { font-size: 1.05rem; }
.ahp-login-title { font-family: "Bricolage Grotesque", sans-serif; font-size: 2.3rem; font-weight: 700; line-height: 1.1; margin-bottom: 0.4rem; color: #1b2a3d; }
@media (max-width: 640px) { .ahp-side, .ahp-side.left { text-align: center; } }
@media (prefers-reduced-motion: reduce) { .ahp-side { transition: none; } }
</style>
"""


# --- État de l'application ----------------------------------------------------------------------------------

def new_item(name: str = "") -> dict:
    return {"id": uuid.uuid4().hex[:10], "name": name}


def fresh_data() -> dict:
    return {
        "job": "",
        "criteria": [new_item(n) for n in ("Expérience", "Compétences techniques", "Formation", "Savoir-être")],
        "candidates": [new_item(), new_item(), new_item()],
        "judgments": {},
        "current_criterion": None,
    }


def clear_widget_state() -> None:
    for key in list(st.session_state):
        if isinstance(key, str) and key.startswith(("cmp::", "name::", "job_input", "criterion_picker")):
            del st.session_state[key]


def init_state() -> None:
    st.session_state.setdefault("authenticated", False)
    st.session_state.setdefault("username", "")
    st.session_state.setdefault("failed_logins", 0)
    st.session_state.setdefault("locked_until", 0.0)
    st.session_state.setdefault("step", 0)
    st.session_state.setdefault("scroll_token", 0)
    st.session_state.setdefault("data", fresh_data())


def data() -> dict:
    return st.session_state["data"]


def go_to(step: int) -> None:
    st.session_state["step"] = step
    st.session_state["scroll_token"] += 1


def add_item(kind: str) -> None:
    if len(data()[kind]) < ahp.MAX_ELEMENTS:
        data()[kind].append(new_item())


def remove_item(kind: str, item_id: str) -> None:
    if len(data()[kind]) > ahp.MIN_ELEMENTS:
        data()[kind] = [item for item in data()[kind] if item["id"] != item_id]


def reset_all() -> None:
    clear_widget_state()
    st.session_state["data"] = fresh_data()
    go_to(0)


def load_example() -> None:
    clear_widget_state()
    criteria = [new_item(n) for n in ("Expérience", "Compétences techniques", "Formation", "Savoir-être")]
    candidates = [new_item(n) for n in ("Amina El Idrissi", "Youness Benali", "Sara Haddad")]
    criteria_values = {(0, 1): 1, (0, 2): -2, (0, 3): -1, (1, 2): -4, (1, 3): -2, (2, 3): 1}
    per_criterion = [
        {(0, 1): -2, (0, 2): -4, (1, 2): -1},
        {(0, 1): 1, (0, 2): -2, (1, 2): -4},
        {(0, 1): 0, (0, 2): 2, (1, 2): 2},
        {(0, 1): -2, (0, 2): -1, (1, 2): 1},
    ]
    def as_store(items: list[dict], values: dict) -> dict:
        return {f"{items[i]['id']}|{items[j]['id']}": v for (i, j), v in values.items()}
    judgments = {CRITERIA_SCOPE: as_store(criteria, criteria_values)}
    for criterion, values in zip(criteria, per_criterion):
        judgments[criterion["id"]] = as_store(candidates, values)
    st.session_state["data"] = {
        "job": "Développeur full-stack",
        "criteria": criteria,
        "candidates": candidates,
        "judgments": judgments,
        "current_criterion": criteria[0]["id"],
    }
    go_to(0)


def names(kind: str) -> list[str]:
    return [item["name"].strip() for item in data()[kind]]


def ids(kind: str) -> list[str]:
    return [item["id"] for item in data()[kind]]


def pair_key(item_ids: list[str], i: int, j: int) -> str:
    return f"{item_ids[i]}|{item_ids[j]}"


def positions_for(scope: str, item_ids: list[str]) -> dict[tuple[int, int], int]:
    store = data()["judgments"].get(scope, {})
    return {
        (i, j): store.get(pair_key(item_ids, i, j), 0)
        for i, j in combinations(range(len(item_ids)), 2)
    }


def setup_problems() -> list[str]:
    problems = []
    for kind, plural in (("criteria", "critères"), ("candidates", "candidats")):
        values = names(kind)
        if not all(values):
            problems.append(f"Donnez un nom à tous les {plural}, ou retirez les lignes vides.")
        filled = [v.casefold() for v in values if v]
        if len(set(filled)) != len(filled):
            problems.append(f"Chaque nom de la liste des {plural} doit être unique.")
    return problems


def current_decision() -> ahp.Decision:
    criteria_ids, candidate_ids = ids("criteria"), ids("candidates")
    return ahp.build_decision(
        data()["job"].strip(), names("criteria"), names("candidates"),
        positions_for(CRITERIA_SCOPE, criteria_ids),
        [positions_for(cid, candidate_ids) for cid in criteria_ids],
    )


# --- Connexion ----------------------------------------------------------------------------------------------

def read_secret_section(section: str) -> dict:
    try:
        return dict(st.secrets[section])
    except Exception:
        return {}


def login_page() -> None:
    _, center, _ = st.columns([1, 1.15, 1])
    with center:
        st.write("")
        st.markdown('<div class="ahp-login-title">Sélection de candidats</div>', unsafe_allow_html=True)
        st.markdown('<p class="ahp-lead">Connectez-vous pour comparer vos candidats et obtenir un classement argumenté.</p>',
                    unsafe_allow_html=True)
        remaining = st.session_state["locked_until"] - time.time()
        with st.form("login_form"):
            username = st.text_input("Identifiant", autocomplete="username")
            password = st.text_input("Mot de passe", type="password", autocomplete="current-password")
            submitted = st.form_submit_button("Se connecter", type="primary", width="stretch")
        if submitted:
            if remaining > 0:
                st.error(f"Trop de tentatives. Réessayez dans {int(remaining) + 1} secondes.")
                return
            config = read_secret_section("auth")
            ok = verify_credentials(
                username, password,
                str(config.get("username", DEFAULT_USERNAME)),
                str(config.get("password_hash", DEFAULT_PASSWORD_HASH)),
            )
            if ok:
                st.session_state.update(authenticated=True, username=username.strip(), failed_logins=0)
                st.rerun()
            st.session_state["failed_logins"] += 1
            if st.session_state["failed_logins"] >= MAX_LOGIN_ATTEMPTS:
                st.session_state["failed_logins"] = 0
                st.session_state["locked_until"] = time.time() + LOCKOUT_SECONDS
                st.error(f"Trop de tentatives. Réessayez dans {LOCKOUT_SECONDS} secondes.")
            else:
                st.error("Identifiant ou mot de passe incorrect.")


def logout() -> None:
    clear_widget_state()
    st.session_state.clear()
    init_state()


# --- Étape 1 : préparer -------------------------------------------------------------------------------------

def item_editor(kind: str, placeholder: str, add_label: str) -> None:
    items = data()[kind]
    for position, item in enumerate(items):
        key = f"name::{item['id']}"
        if key not in st.session_state:
            st.session_state[key] = item["name"]
        name_col, delete_col = st.columns([12, 2], vertical_alignment="center")
        item["name"] = name_col.text_input(
            f"{placeholder} {position + 1}", key=key, placeholder=placeholder,
            label_visibility="collapsed", max_chars=60,
        )
        delete_col.button(
            "", icon=":material/close:", key=f"delete::{item['id']}", help="Retirer cette ligne",
            on_click=remove_item, args=(kind, item["id"]), disabled=len(items) <= ahp.MIN_ELEMENTS,
        )
    st.button(add_label, icon=":material/add:", key=f"add::{kind}", on_click=add_item, args=(kind,),
              disabled=len(items) >= ahp.MAX_ELEMENTS)


def setup_step() -> None:
    title_col, action_col = st.columns([3, 2], vertical_alignment="bottom")
    with title_col:
        st.title("Préparez votre évaluation")
    with action_col:
        example_col, reset_col = st.columns(2)
        example_col.button("Charger un exemple", width="stretch", on_click=load_example)
        reset_col.button("Tout effacer", width="stretch", on_click=reset_all)
    st.markdown(
        '<p class="ahp-lead">Indiquez ce qui compte pour ce poste et qui postule. Vous comparerez ensuite '
        "les éléments deux par deux, et l'application calculera le classement.</p>",
        unsafe_allow_html=True,
    )
    if "job_input" not in st.session_state:
        st.session_state["job_input"] = data()["job"]
    data()["job"] = st.text_input("Poste à pourvoir", key="job_input", placeholder="Ex. : Chargé de clientèle", max_chars=100)

    criteria_col, candidates_col = st.columns(2, gap="large")
    with criteria_col:
        st.subheader("Critères")
        item_editor("criteria", "Nom du critère", "Ajouter un critère")
    with candidates_col:
        st.subheader("Candidats")
        item_editor("candidates", "Nom du candidat", "Ajouter un candidat")

    k, m = len(data()["criteria"]), len(data()["candidates"])
    criteria_pairs, candidate_pairs = ahp.pair_count(k), ahp.pair_count(m)
    st.divider()
    st.markdown(
        f"**{criteria_pairs + k * candidate_pairs} comparaisons à faire** : "
        f"{criteria_pairs} entre les {k} critères, puis {candidate_pairs} entre les {m} candidats "
        f"pour chacun des {k} critères. L'inverse de chaque réponse est déduit automatiquement."
    )
    problems = setup_problems()
    for problem in problems:
        st.caption(problem)
    st.button("Pondérer les critères", type="primary", icon=":material/arrow_forward:", icon_position="right",
              disabled=bool(problems), on_click=go_to, args=(1,))


# --- Comparaisons par paires --------------------------------------------------------------------------------

def compare_sentence(a: str, b: str, position: int, mode: str) -> str:
    a_html, b_html = f"<strong>{escape(a)}</strong>", f"<strong>{escape(b)}</strong>"
    if position == 0:
        return f"{a_html} et {b_html} ont la même importance" if mode == "criteria" else f"{a_html} et {b_html} sont à égalité"
    winner, loser = (a_html, b_html) if position < 0 else (b_html, a_html)
    adverb = ADVERBS[abs(position) + 1]
    if mode == "criteria":
        return f"{winner} compte {adverb} plus que {loser}"
    return f"{winner} l'emporte {adverb} sur {loser}"


def comparison_rows(scope: str, labels: list[str], item_ids: list[str], mode: str) -> None:
    store = data()["judgments"].setdefault(scope, {})
    for i, j in combinations(range(len(labels)), 2):
        pair = pair_key(item_ids, i, j)
        widget_key = f"cmp::{scope}::{pair}"
        if widget_key not in st.session_state:
            st.session_state[widget_key] = store.get(pair, 0)
        left, center, right = st.columns([3.2, 5, 3.2], vertical_alignment="center")
        with center:
            position = st.select_slider(
                f"{labels[i]} comparé à {labels[j]}", options=ahp.POSITIONS,
                format_func=lambda p: str(abs(p) + 1), key=widget_key, label_visibility="collapsed",
            )
            st.markdown(f'<div class="ahp-sentence">{compare_sentence(labels[i], labels[j], position, mode)}</div>',
                        unsafe_allow_html=True)
        store[pair] = position
        left_state = "on" if position < 0 else "tie" if position == 0 else ""
        right_state = "on" if position > 0 else "tie" if position == 0 else ""
        left.markdown(f'<div class="ahp-side left {left_state}">{escape(labels[i])}</div>', unsafe_allow_html=True)
        right.markdown(f'<div class="ahp-side {right_state}">{escape(labels[j])}</div>', unsafe_allow_html=True)
        st.write("")


def apply_suggestion(scope: str, pair: str, position: int) -> None:
    data()["judgments"].setdefault(scope, {})[pair] = position
    st.session_state[f"cmp::{scope}::{pair}"] = position


def matrix_html(labels: list[str], matrix, mode: str) -> str:
    n = len(labels)
    head = "".join(f"<th>{k + 1}</th>" for k in range(n))
    rows = []
    for i in range(n):
        cells = []
        for j in range(n):
            if mode == "pairwise":
                css = "diag" if i == j else "in" if i < j else "auto"
                text = ahp.value_label(float(matrix[i, j]))
            else:
                css, text = "", f"{matrix[i, j]:.3f}".replace(".", ",")
            cells.append(f'<td class="{css}">{text}</td>')
        rows.append(f"<tr><th>{i + 1}. {escape(labels[i])}</th>{''.join(cells)}</tr>")
    return f'<div class="ahp-matrix-wrap"><table class="ahp-matrix"><thead><tr><th></th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def status_html(analysis: ahp.Analysis) -> str:
    if analysis.is_untouched:
        return ('<div class="ahp-status todo"><strong>À compléter</strong>'
                "Déplacez les curseurs lorsque deux éléments ne se valent pas.</div>")
    if analysis.is_consistent:
        return (f'<div class="ahp-status ok"><strong>✓ Réponses cohérentes</strong>'
                f"Ratio de cohérence : {ahp.percent(analysis.cr)} (limite : 10 %)</div>")
    return (f'<div class="ahp-status bad"><strong>⚠ Jugement incohérent</strong>'
            f"Ratio de cohérence : {ahp.percent(analysis.cr)}, au-delà de la limite de 10 %. "
            "Certaines réponses se contredisent : si A dépasse B et B dépasse C, A doit dépasser C.</div>")


def weights_html(labels: list[str], weights) -> str:
    top = float(weights.max())
    rows = [
        f'<div class="ahp-w"><div class="ahp-w-head"><span>{escape(labels[i])}</span><span>{ahp.percent(float(weights[i]))}</span></div>'
        f'<div class="ahp-w-track"><div class="ahp-w-fill" style="width:{float(weights[i]) / top * 100:.1f}%"></div></div></div>'
        for i in sorted(range(len(labels)), key=lambda k: -weights[k])
    ]
    return "".join(rows)


def suggestions_panel(scope: str, labels: list[str], item_ids: list[str], analysis: ahp.Analysis, mode: str) -> None:
    suggestions = ahp.suggest_adjustments(analysis)
    if not suggestions:
        st.markdown("Reprenez les comparaisons où vous hésitiez : aucune correction d'une seule réponse ne suffit.")
        return
    st.markdown("**Réajustements suggérés**")
    for s in suggestions:
        a, b = labels[s.i], labels[s.j]
        pair = pair_key(item_ids, s.i, s.j)
        st.markdown(
            f'<span class="ahp-legend">Vous avez indiqué : {compare_sentence(a, b, s.current_position, mode)}.</span><br>'
            f"Essayez : {compare_sentence(a, b, s.suggested_position, mode)}. "
            f'<span class="ahp-legend">Cohérence obtenue : {ahp.percent(s.new_cr)}.</span>',
            unsafe_allow_html=True,
        )
        st.button("Appliquer", key=f"apply::{scope}::{pair}::{s.suggested_position}", on_click=apply_suggestion,
                  args=(scope, pair, s.suggested_position))


def calculation_details(labels: list[str], analysis: ahp.Analysis) -> None:
    with st.expander("Voir le détail des calculs"):
        st.markdown(f"**Matrice de comparaison** ({ahp.pair_count(analysis.n)} saisies pour {analysis.n} éléments)")
        st.markdown(matrix_html(labels, analysis.matrix, "pairwise"), unsafe_allow_html=True)
        st.markdown('<span class="ahp-legend">En bleu, vos réponses. En italique, les inverses calculés automatiquement.</span>',
                    unsafe_allow_html=True)
        st.markdown("**Matrice normalisée**")
        st.markdown(matrix_html(labels, analysis.normalized, "normalized"), unsafe_allow_html=True)
        table = pd.DataFrame({
            "Élément": labels,
            "Vecteur propre": [f"{w:.4f}".replace(".", ",") for w in analysis.weights],
            "Moyenne des lignes": [f"{w:.4f}".replace(".", ",") for w in analysis.weights_row_mean],
        })
        st.dataframe(table, hide_index=True, width="stretch")
        st.markdown(
            f"λmax = {analysis.lambda_max:.4f}, CI = (λmax − n) / (n − 1) = {analysis.ci:.4f}, "
            f"RI = {analysis.ri:.2f}, CR = CI / RI = {ahp.percent(analysis.cr, 2)}"
        )


def live_panel(scope: str, labels: list[str], item_ids: list[str], title: str, mode: str) -> ahp.Analysis:
    analysis = ahp.analyze(ahp.build_matrix(len(labels), positions_for(scope, item_ids)))
    st.markdown('<div class="ahp-sticky"></div>', unsafe_allow_html=True)
    st.subheader(title)
    st.markdown(status_html(analysis), unsafe_allow_html=True)
    if not analysis.is_consistent:
        suggestions_panel(scope, labels, item_ids, analysis, mode)
    st.markdown(weights_html(labels, analysis.weights), unsafe_allow_html=True)
    calculation_details(labels, analysis)
    return analysis


def scale_help(mode: str) -> None:
    target = "compte le plus pour ce poste" if mode == "criteria" else "répond le mieux à ce critère"
    st.markdown(
        f'<p class="ahp-lead">Pour chaque paire, tirez le curseur vers ce qui {target}. '
        "Plus vous vous éloignez du centre, plus l'écart est grand : 1 signifie égalité, 9 écart extrême.</p>",
        unsafe_allow_html=True,
    )


def criteria_step() -> None:
    labels, item_ids = names("criteria"), ids("criteria")
    st.title("Quels critères comptent le plus ?")
    scale_help("criteria")
    st.markdown(f'<div class="ahp-progress">{ahp.pair_count(len(labels))} comparaisons pour {len(labels)} critères</div>',
                unsafe_allow_html=True)
    inputs, summary = st.columns([5, 3], gap="large")
    with inputs:
        comparison_rows(CRITERIA_SCOPE, labels, item_ids, "criteria")
    with summary:
        live_panel(CRITERIA_SCOPE, labels, item_ids, "Poids obtenus", "criteria")
    navigation(0, "Préparer", 2, "Évaluer les candidats")


def set_criterion(criterion_id: str) -> None:
    data()["current_criterion"] = criterion_id
    st.session_state["criterion_picker"] = criterion_id
    st.session_state["scroll_token"] += 1


def status_pills(current: str) -> str:
    candidate_ids = ids("candidates")
    pills = []
    for item in data()["criteria"]:
        analysis = ahp.analyze(ahp.build_matrix(len(candidate_ids), positions_for(item["id"], candidate_ids)))
        if analysis.is_untouched:
            css, mark = "", "À faire"
        elif analysis.is_consistent:
            css, mark = "ok", "✓"
        else:
            css, mark = "bad", "⚠ À revoir"
        outline = " current" if item["id"] == current else ""
        pills.append(f'<span class="ahp-pill {css}{outline}">{escape(item["name"].strip())} : {mark}</span>')
    return f'<div class="ahp-pills">{"".join(pills)}</div>'


def candidates_step() -> None:
    criteria_ids, candidate_ids = ids("criteria"), ids("candidates")
    candidate_labels = names("candidates")
    label_by_id = dict(zip(criteria_ids, names("criteria")))
    if data()["current_criterion"] not in criteria_ids:
        data()["current_criterion"] = criteria_ids[0]
    if st.session_state.get("criterion_picker") not in criteria_ids:
        st.session_state["criterion_picker"] = data()["current_criterion"]

    st.title("Comparez les candidats, critère par critère")
    scale_help("candidates")
    pills = st.empty()
    current = st.selectbox("Critère évalué", options=criteria_ids, format_func=label_by_id.get, key="criterion_picker")
    data()["current_criterion"] = current
    index = criteria_ids.index(current)
    criterion_name = label_by_id[current]
    st.markdown(
        f'<div class="ahp-progress">Critère {index + 1} sur {len(criteria_ids)} : '
        f"{ahp.pair_count(len(candidate_labels))} comparaisons pour {len(candidate_labels)} candidats</div>",
        unsafe_allow_html=True,
    )
    inputs, summary = st.columns([5, 3], gap="large")
    with inputs:
        comparison_rows(current, candidate_labels, candidate_ids, "candidates")
    with summary:
        live_panel(current, candidate_labels, candidate_ids, f"Selon « {criterion_name} »", "candidates")
    pills.markdown(status_pills(current), unsafe_allow_html=True)

    st.divider()
    previous_col, _, next_col = st.columns([2, 4, 2])
    if index > 0:
        previous_col.button("Critère précédent", icon=":material/arrow_back:", width="stretch",
                            on_click=set_criterion, args=(criteria_ids[index - 1],))
    else:
        previous_col.button("Pondérer les critères", icon=":material/arrow_back:", width="stretch",
                            on_click=go_to, args=(1,))
    if index < len(criteria_ids) - 1:
        next_col.button("Critère suivant", type="primary", icon=":material/arrow_forward:", icon_position="right",
                        width="stretch", on_click=set_criterion, args=(criteria_ids[index + 1],))
    else:
        next_col.button("Voir les résultats", type="primary", icon=":material/arrow_forward:", icon_position="right",
                        width="stretch", on_click=go_to, args=(3,))


def navigation(previous: int, previous_label: str, following: int, following_label: str) -> None:
    st.divider()
    previous_col, _, next_col = st.columns([2, 4, 2])
    previous_col.button(previous_label, icon=":material/arrow_back:", width="stretch", on_click=go_to, args=(previous,))
    next_col.button(following_label, type="primary", icon=":material/arrow_forward:", icon_position="right",
                    width="stretch", on_click=go_to, args=(following,))


# --- Résultats ----------------------------------------------------------------------------------------------

def winner_html(decision: ahp.Decision) -> str:
    job = f" au poste de {escape(decision.job)}" if decision.job else ""
    winners = decision.winners
    if len(winners) == 1:
        winner = winners[0]
        order = decision.order
        gap = float(decision.scores[order[0]] - decision.scores[order[1]])
        runner = decision.candidates[order[1]]
        note = (f"{ahp.percent(float(decision.scores[winner]))} du score total, "
                f"{f'{gap * 100:.1f}'.replace('.', ',')} points devant {escape(runner)}.")
        return (f'<div class="ahp-winner"><div class="ahp-winner-label">Meilleur candidat{job}</div>'
                f'<div class="ahp-winner-name">{escape(decision.candidates[winner])}</div>'
                f'<div class="ahp-winner-note">{note}</div></div>')
    tied = ", ".join(escape(decision.candidates[c]) for c in winners)
    return (f'<div class="ahp-winner"><div class="ahp-winner-label">Égalité en tête{job}</div>'
            f'<div class="ahp-winner-name">{tied}</div>'
            f'<div class="ahp-winner-note">{ahp.percent(float(decision.scores[winners[0]]))} chacun. '
            "Affinez vos comparaisons pour les départager.</div></div>")


RESERVED_COLUMNS = {"Rang", "Candidat", "Score global"}


def criterion_column(criterion: str) -> str:
    return f"{criterion} (critère)" if criterion in RESERVED_COLUMNS else criterion


def results_table(decision: ahp.Decision) -> pd.DataFrame:
    rows = []
    for c in decision.order:
        row = {"Rang": int(decision.ranks[c]), "Candidat": decision.candidates[c], "Score global": decision.scores[c] * 100}
        row.update({criterion_column(criterion): decision.local[c, k] * 100 for k, criterion in enumerate(decision.criteria)})
        rows.append(row)
    return pd.DataFrame(rows)


def consistency_table(decision: ahp.Decision) -> pd.DataFrame:
    entries = [("Pondération des critères", decision.criteria_analysis)]
    entries += [(f"Candidats selon « {c} »", a) for c, a in zip(decision.criteria, decision.candidate_analyses)]
    return pd.DataFrame([
        {"Comparaisons": name, "λmax": a.lambda_max, "CI": a.ci, "CR (%)": a.cr * 100,
         "Statut": "✓ Cohérent" if a.is_consistent else "⚠ À revoir"}
        for name, a in entries
    ])


def smtp_settings() -> SmtpConfig | None:
    values = read_secret_section("smtp")
    if not values:
        values = {
            key: os.environ[f"SMTP_{key.upper()}"]
            for key in ("host", "port", "username", "password", "sender", "security")
            if f"SMTP_{key.upper()}" in os.environ
        }
    return SmtpConfig.from_mapping(values)


def report_section(decision: ahp.Decision) -> None:
    st.subheader("Transmettre le rapport")
    meta = report.ReportMeta(st.session_state["username"], datetime.now(TIMEZONE))
    pdf = report.build_pdf(decision, meta)
    config = smtp_settings()
    send_col, download_col = st.columns([3, 2])
    clicked = send_col.button(
        f"Envoyer le rapport à {REPORT_RECIPIENT}", type="primary", icon=":material/send:",
        width="stretch", disabled=config is None,
    )
    download_col.download_button(
        "Télécharger le rapport PDF", data=pdf, file_name=report.filename(meta), mime="application/pdf",
        icon=":material/download:", width="stretch",
    )
    if config is None:
        st.warning(
            "L'envoi d'e-mail n'est pas encore configuré. Renseignez le compte d'envoi dans "
            "`.streamlit/secrets.toml`, en suivant le modèle `secrets.toml.example`."
        )
    if decision.inconsistent_matrices:
        st.caption("Le rapport signalera les jugements incohérents.")
    if clicked and config is not None:
        with st.spinner("Envoi du rapport en cours..."):
            try:
                message = compose_message(
                    config.sender, REPORT_RECIPIENT, report.subject(decision),
                    report.build_text(decision, meta), report.build_html(decision, meta), pdf, report.filename(meta),
                )
                send_message(config, message, REPORT_RECIPIENT)
            except MailError as error:
                st.error(str(error))
            else:
                st.success(f"Rapport envoyé à {REPORT_RECIPIENT}, avec le PDF en pièce jointe.")


def results_step() -> None:
    decision = current_decision()
    st.title("Résultats")
    st.markdown(winner_html(decision), unsafe_allow_html=True)

    if decision.inconsistent_matrices:
        st.warning(
            "Jugement incohérent dans : " + " ; ".join(decision.inconsistent_matrices)
            + ". Le classement est à considérer avec prudence tant que ces réponses ne sont pas réajustées.",
            icon=":material/warning:",
        )
    if decision.untouched_matrices:
        st.info("Tout est resté à égalité dans : " + " ; ".join(decision.untouched_matrices)
                + ". Vérifiez que ces comparaisons ont bien été faites.", icon=":material/info:")

    ranking_col, weights_col = st.columns(2, gap="large")
    with ranking_col:
        st.subheader("Classement final")
        st.plotly_chart(charts.ranking_chart(decision), width="stretch", config=charts.PLOTLY_CONFIG)
    with weights_col:
        st.subheader("Poids des critères")
        st.plotly_chart(charts.weights_chart(decision), width="stretch", config=charts.PLOTLY_CONFIG)

    st.subheader("Tableau récapitulatif")
    st.caption("Le score global est la somme des priorités de chaque candidat, pondérées par le poids des critères.")
    column_config = {
        "Rang": st.column_config.NumberColumn(width="small", format="%d"),
        "Score global": st.column_config.ProgressColumn(format="%.1f %%", min_value=0, max_value=100),
    }
    column_config.update({criterion_column(c): st.column_config.NumberColumn(format="%.1f %%") for c in decision.criteria})
    st.dataframe(results_table(decision), hide_index=True, width="stretch", column_config=column_config)

    st.subheader("Ce qui fait la différence")
    st.caption("Chaque barre additionne les points apportés par les critères au score du candidat.")
    st.plotly_chart(charts.contribution_chart(decision), width="stretch", config=charts.PLOTLY_CONFIG)

    st.subheader("Forces et faiblesses par critère")
    st.caption("Dans chaque colonne, les pourcentages se partagent 100 % entre les candidats.")
    st.plotly_chart(charts.heatmap_chart(decision), width="stretch", config=charts.PLOTLY_CONFIG)

    with st.expander("Contrôle de cohérence de toutes les comparaisons"):
        st.dataframe(
            consistency_table(decision), hide_index=True, width="stretch",
            column_config={
                "λmax": st.column_config.NumberColumn(format="%.4f"),
                "CI": st.column_config.NumberColumn(format="%.4f"),
                "CR (%)": st.column_config.NumberColumn(format="%.2f"),
            },
        )

    st.divider()
    report_section(decision)
    st.divider()
    previous_col, _ = st.columns([2, 6])
    previous_col.button("Modifier les réponses", icon=":material/arrow_back:", width="stretch", on_click=go_to, args=(2,))


# --- Structure générale -------------------------------------------------------------------------------------

def sidebar(valid: bool) -> None:
    with st.sidebar:
        st.markdown("### Sélection AHP")
        for index, label in enumerate(STEPS):
            st.button(
                f"{index + 1}. {label}", key=f"nav::{index}", width="stretch",
                type="primary" if st.session_state["step"] == index else "secondary",
                disabled=index > 0 and not valid, on_click=go_to, args=(index,),
            )
        if valid:
            decision = current_decision()
            total = 1 + len(decision.criteria)
            failing = len(decision.inconsistent_matrices)
            if failing:
                st.caption(f"⚠ {failing} comparaison(s) sur {total} à revoir")
            else:
                st.caption(f"✓ Cohérence correcte sur {total} comparaisons")
        st.divider()
        st.caption(f"Connecté : {st.session_state['username']}")
        st.button("Se déconnecter", icon=":material/logout:", width="stretch", on_click=logout)


def scroll_to_top() -> None:
    """Remonte en haut de la page après un changement d'écran."""
    token = st.session_state["scroll_token"]
    if st.session_state.get("scrolled_token") == token:
        return
    st.session_state["scrolled_token"] = token
    st.html(
        "<script>document.querySelector('[data-testid=\"stMain\"]')?.scrollTo({top: 0});</script>",
        unsafe_allow_javascript=True,
    )


def main() -> None:
    st.set_page_config(page_title="Sélection de candidats AHP", page_icon=":material/balance:", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    init_state()
    if not st.session_state["authenticated"]:
        login_page()
        return
    valid = not setup_problems()
    if not valid:
        st.session_state["step"] = 0
    step = st.session_state["step"]
    {0: setup_step, 1: criteria_step, 2: candidates_step, 3: results_step}[step]()
    sidebar(not setup_problems())
    scroll_to_top()


if __name__ == "__main__":
    main()
