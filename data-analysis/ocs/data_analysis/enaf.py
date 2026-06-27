"""Classification ENAF des polygones d'occupation du sol (OCS-GE).

L'objectif du projet (cf. README) est de mesurer la consommation d'**Espaces
Naturels, Agricoles et Forestiers (ENAF)** — et des espaces artificialisés — par
le photovoltaïque au sol. L'analyse OCS travaille pour l'instant au niveau du
code d'usage brut (``code_us``) ; ce module ajoute la couche manquante : le
regroupement des codes OCS-GE dans les cinq catégories ENAF.

Cinq catégories :

* ``Surfaces agricoles``
* ``Surfaces forestières``
* ``Surfaces naturelles``
* ``Surfaces artificialisées``
* ``Surfaces de friche``

Un polygone OCS est classé selon l'ordre de priorité suivant :

1. s'il porte le marqueur OCS-GE *artificialisé* → ``Surfaces artificialisées`` ;
2. sinon, selon son code d'usage ``code_us`` (table ``CODES_US_ENAF``) ;
3. uniquement lorsque (2) donne ``Surfaces naturelles`` et que le code de
   couverture ``code_cs`` est ligneux → ``Surfaces forestières`` (cela rattrape
   les forêts non exploitées sans reclasser les vergers ou haies agricoles) ;
4. tout code non reconnu (ou absent) → ``DEFAUT``.

Le module est volontairement sans dépendance (uniquement la bibliothèque
standard) afin de rester testable sans base de données et importable depuis le
notebook ``analysis.py`` comme depuis la suite de tests.
"""

from __future__ import annotations

# --- catégories ENAF ---------------------------------------------------------

SURFACES_AGRICOLES = "Surfaces agricoles"
SURFACES_FORESTIERES = "Surfaces forestières"
SURFACES_NATURELLES = "Surfaces naturelles"
SURFACES_ARTIFICIALISEES = "Surfaces artificialisées"
SURFACES_FRICHES = "Surfaces de friche"

CATEGORIES_ENAF: tuple[str, ...] = (
    SURFACES_AGRICOLES,
    SURFACES_FORESTIERES,
    SURFACES_NATURELLES,
    SURFACES_ARTIFICIALISEES,
    SURFACES_FRICHES,
)

# Surface d'un parc n'intersectant aucun polygone OCS — suivie à part, ce n'est
# pas une catégorie ENAF.
SANS_CORRESPONDANCE = "Sans correspondance"

# Catégorie retenue pour un code d'usage absent ou non reconnu.
DEFAUT = SURFACES_NATURELLES

# --- table de correspondance code_us → ENAF ---------------------------------

# Reprend la nomenclature OCS-GE des usages (les libellés en commentaire
# correspondent au ``CODES_US_MAPPING`` du notebook).
CODES_US_ENAF: dict[str, str] = {
    "US1.1": SURFACES_AGRICOLES,  # Agriculture
    "US1.2": SURFACES_FORESTIERES,  # Sylviculture
    "US1.3": SURFACES_ARTIFICIALISEES,  # Activités d'extraction
    "US1.4": SURFACES_NATURELLES,  # Pêche et aquaculture
    "US1.5": SURFACES_AGRICOLES,  # Autres productions primaires
    "US2": SURFACES_ARTIFICIALISEES,  # Production secondaire
    "US235": SURFACES_ARTIFICIALISEES,  # Usage mixte
    "US3": SURFACES_ARTIFICIALISEES,  # Production tertiaire
    "US4.1.1": SURFACES_ARTIFICIALISEES,  # Réseaux routiers
    "US4.1.2": SURFACES_ARTIFICIALISEES,  # Réseaux ferrés
    "US4.1.3": SURFACES_ARTIFICIALISEES,  # Réseaux aériens
    "US4.1.4": SURFACES_ARTIFICIALISEES,  # Transport fluvial et maritime
    "US4.1.5": SURFACES_ARTIFICIALISEES,  # Autres réseaux de transport
    "US4.2": SURFACES_ARTIFICIALISEES,  # Services de logistique et de stockage
    "US4.3": SURFACES_ARTIFICIALISEES,  # Réseaux d'utilité publique
    "US5": SURFACES_ARTIFICIALISEES,  # Usage résidentiel
    "US6.1": SURFACES_ARTIFICIALISEES,  # Zones en transition (chantiers)
    "US6.2": SURFACES_FRICHES,  # Zones abandonnées
    "US6.3": SURFACES_NATURELLES,  # Sans usage
    "US6.6": SURFACES_NATURELLES,  # Usage inconnu
}

# Préfixes de codes de couverture (CS) ligneux → forestier. La correspondance se
# fait par préfixe : "CS1.1.1" (formations arborées) couvre "CS1.1.1.1" (feuillus)
# et "CS1.1.1.2" (conifères).
CODES_CS_FORESTIERS: tuple[str, ...] = ("CS1.1.1",)


def _normaliser(code: str | None) -> str | None:
    return str(code).strip().upper() if code is not None else None


def _est_artificialise(valeur) -> bool:
    """Interprète au mieux le marqueur d'artificialisation de l'OCS-GE.

    Gère les encodages booléen / "Artificialisé" / "Non artificialisé" / "Oui".
    Les valeurs exactes restent à confirmer sur les données réelles.
    """
    if valeur is None:
        return False
    if isinstance(valeur, bool):
        return valeur
    s = str(valeur).strip().lower()
    if s.startswith("non"):
        return False
    return s in {"1", "true", "oui"} or s.startswith("artif")


def classer_enaf(code_us, code_cs=None, artif=None) -> str:
    """Classe un polygone OCS (``code_us`` [, ``code_cs``, ``artif``]) en ENAF.

    Seul ``code_us`` est obligatoire ; ``code_cs`` et ``artif`` affinent le
    résultat lorsqu'ils sont disponibles dans la jointure.
    """
    if _est_artificialise(artif):
        return SURFACES_ARTIFICIALISEES
    categorie = CODES_US_ENAF.get(_normaliser(code_us), DEFAUT)
    if categorie == SURFACES_NATURELLES and code_cs is not None:
        cs = _normaliser(code_cs)
        if any(cs.startswith(prefixe) for prefixe in CODES_CS_FORESTIERS):
            return SURFACES_FORESTIERES
    return categorie
