"""Moteur de calcul AHP (Analytic Hierarchy Process), sans dépendance à l'interface."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np

# Indices aléatoires publiés par Saaty, utilisés pour calculer le ratio de cohérence.
RANDOM_INDEX = {
    1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41,
    9: 1.45, 10: 1.49, 11: 1.51, 12: 1.48, 13: 1.56, 14: 1.57, 15: 1.59,
}
MIN_ELEMENTS = 2
MAX_ELEMENTS = max(RANDOM_INDEX)
CR_THRESHOLD = 0.10

# Une comparaison est saisie sur 17 positions :
#   -8 ... -1 : l'élément de gauche l'emporte (valeur 9 ... 2)
#    0        : égalité (valeur 1)
#   +1 ... +8 : l'élément de droite l'emporte (valeur 1/2 ... 1/9)
POSITIONS = list(range(-8, 9))
_VALUES = np.array([
    (abs(p) + 1.0) if p <= 0 else 1.0 / (p + 1.0) for p in POSITIONS
])


def position_to_value(position: int) -> float:
    """Convertit une position de curseur en valeur a_ij de l'échelle de Saaty."""
    if position not in POSITIONS:
        raise ValueError(f"Position hors échelle : {position}")
    return float(_VALUES[position + 8])


def value_to_position(value: float) -> int:
    """Retourne la position de l'échelle la plus proche d'un rapport (au sens logarithmique)."""
    if value <= 0:
        raise ValueError("Un rapport de préférence doit être strictement positif.")
    return POSITIONS[int(np.argmin(np.abs(np.log(_VALUES) - np.log(value))))]


def value_label(value: float) -> str:
    """Affiche une valeur de l'échelle sous forme lisible : 3, 1 ou 1/5."""
    if value >= 1:
        rounded = round(value, 2)
        return f"{rounded:g}"
    return f"1/{round(1 / value):d}"


def pair_count(n: int) -> int:
    """Nombre de saisies nécessaires pour n éléments : n(n-1)/2."""
    return n * (n - 1) // 2


def build_matrix(n: int, positions: dict[tuple[int, int], int]) -> np.ndarray:
    """Construit la matrice complète à partir des seules saisies du triangle supérieur.

    Les paires absentes valent 1 (égalité) et a_ji = 1 / a_ij est calculé automatiquement.
    """
    matrix = np.ones((n, n), dtype=float)
    for i, j in combinations(range(n), 2):
        value = position_to_value(positions.get((i, j), 0))
        matrix[i, j] = value
        matrix[j, i] = 1.0 / value
    return matrix


@dataclass(frozen=True)
class Analysis:
    matrix: np.ndarray
    normalized: np.ndarray
    weights: np.ndarray            # vecteur propre principal normalisé
    weights_row_mean: np.ndarray   # moyenne des lignes de la matrice normalisée
    lambda_max: float
    ci: float
    ri: float
    cr: float

    @property
    def n(self) -> int:
        return self.matrix.shape[0]

    @property
    def is_consistent(self) -> bool:
        return self.cr <= CR_THRESHOLD

    @property
    def is_untouched(self) -> bool:
        return bool(np.all(np.isclose(self.matrix, 1.0)))


def _principal_eigen(matrix: np.ndarray) -> tuple[float, np.ndarray]:
    eigenvalues, eigenvectors = np.linalg.eig(matrix)
    index = int(np.argmax(eigenvalues.real))
    vector = np.abs(eigenvectors[:, index].real)
    return float(eigenvalues[index].real), vector / vector.sum()


def _consistency(lambda_max: float, n: int) -> tuple[float, float, float]:
    ri = RANDOM_INDEX[n]
    ci = max(0.0, (lambda_max - n) / (n - 1)) if n > 1 else 0.0
    if ci < 1e-12:
        ci = 0.0
    return ci, ri, (ci / ri if ri > 0 else 0.0)


def analyze(matrix: np.ndarray) -> Analysis:
    """Calcule la matrice normalisée, les poids, lambda max, CI et CR."""
    n = matrix.shape[0]
    if n not in RANDOM_INDEX:
        raise ValueError(f"Le nombre d'éléments doit être compris entre 1 et {MAX_ELEMENTS}.")
    normalized = matrix / matrix.sum(axis=0)
    lambda_max, weights = _principal_eigen(matrix)
    ci, ri, cr = _consistency(lambda_max, n)
    return Analysis(matrix, normalized, weights, normalized.mean(axis=1), lambda_max, ci, ri, cr)


@dataclass(frozen=True)
class Suggestion:
    i: int
    j: int
    current_position: int
    suggested_position: int
    new_cr: float


def suggest_adjustments(analysis: Analysis, limit: int = 3) -> list[Suggestion]:
    """Propose les corrections d'une seule paire qui réduisent le plus le CR.

    Pour chaque paire, la valeur testée est la valeur de l'échelle la plus proche du rapport
    w_i / w_j déduit de l'ensemble des autres réponses.
    """
    n = analysis.n
    suggestions: list[Suggestion] = []
    for i, j in combinations(range(n), 2):
        current = value_to_position(float(analysis.matrix[i, j]))
        target = value_to_position(float(analysis.weights[i] / analysis.weights[j]))
        if target == current:
            continue
        candidate = analysis.matrix.copy()
        candidate[i, j] = position_to_value(target)
        candidate[j, i] = 1.0 / candidate[i, j]
        lambda_max, _ = _principal_eigen(candidate)
        new_cr = _consistency(lambda_max, n)[2]
        if new_cr < analysis.cr - 1e-6:
            suggestions.append(Suggestion(i, j, current, target, new_cr))
    suggestions.sort(key=lambda s: s.new_cr)
    return suggestions[:limit]


@dataclass(frozen=True)
class Decision:
    job: str
    criteria: list[str]
    candidates: list[str]
    criteria_analysis: Analysis
    candidate_analyses: list[Analysis]
    local: np.ndarray    # candidats x critères : priorité de chaque candidat par critère
    scores: np.ndarray   # score global de chaque candidat (somme = 1)
    ranks: np.ndarray    # rang de chaque candidat (les ex æquo partagent le rang)

    @property
    def order(self) -> list[int]:
        return sorted(range(len(self.candidates)), key=lambda c: (self.ranks[c], c))

    @property
    def winners(self) -> list[int]:
        return [c for c in self.order if self.ranks[c] == 1]

    @property
    def contributions(self) -> np.ndarray:
        return self.local * self.criteria_analysis.weights

    @property
    def inconsistent_matrices(self) -> list[str]:
        names = [] if self.criteria_analysis.is_consistent else ["Pondération des critères"]
        names += [
            f"Candidats selon « {criterion} »"
            for criterion, analysis in zip(self.criteria, self.candidate_analyses)
            if not analysis.is_consistent
        ]
        return names

    @property
    def untouched_matrices(self) -> list[str]:
        names = ["Pondération des critères"] if self.criteria_analysis.is_untouched else []
        names += [
            f"Candidats selon « {criterion} »"
            for criterion, analysis in zip(self.criteria, self.candidate_analyses)
            if analysis.is_untouched
        ]
        return names


def rank_scores(scores: np.ndarray, tolerance: float = 1e-9) -> np.ndarray:
    """Classe les scores par ordre décroissant ; les ex æquo partagent le même rang."""
    return np.array([1 + int(np.sum(scores > score + tolerance)) for score in scores])


def build_decision(
    job: str,
    criteria: list[str],
    candidates: list[str],
    criteria_positions: dict[tuple[int, int], int],
    candidate_positions: list[dict[tuple[int, int], int]],
) -> Decision:
    """Assemble toutes les matrices et réalise la synthèse pondérée finale."""
    criteria_analysis = analyze(build_matrix(len(criteria), criteria_positions))
    analyses = [analyze(build_matrix(len(candidates), p)) for p in candidate_positions]
    local = np.column_stack([analysis.weights for analysis in analyses])
    scores = local @ criteria_analysis.weights
    return Decision(
        job, criteria, candidates, criteria_analysis, analyses, local, scores, rank_scores(scores),
    )


def percent(value: float, digits: int = 1) -> str:
    """Formate un ratio en pourcentage à la française : 12,3 %."""
    return f"{value * 100:.{digits}f}".replace(".", ",") + " %"
