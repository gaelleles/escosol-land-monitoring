import httpx
from httpx_retries import Retry, RetryTransport

TIMEOUT_CONFIG = httpx.Timeout(60.0, connect=10.0)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
RETRY_TRANSPORT = RetryTransport(retry=Retry(total=5, backoff_factor=0.5))

ARCHIVE_URLS = {
    "Bretagne": "https://www.bretagne.developpement-durable.gouv.fr/avis-de-l-ae-sur-projets-jusqu-en-2017-r743.html",
    "Grand Est": "https://www.grand-est.developpement-durable.gouv.fr/avis-et-decisions-de-l-ae-r6433.html",
    "Guadeloupe": "https://www.guadeloupe.developpement-durable.gouv.fr/annees-2010-a-2022-r1437.html",
    "Guyane": "https://www.guyane.developpement-durable.gouv.fr/avis-de-l-autorite-environnementale-r852.html",
    "Aisne": "https://www.aisne.gouv.fr/Actions-de-l-Etat/Environnement/Avis-de-l-autorite-environnementale/Avis-de-l-AE/Les-avis-de-l-autorite-environnementale",
    "Somme": "https://www.somme.gouv.fr/Actions-de-l-Etat/Environnement/Autorite-environnementale-Avis-sur-les-evaluations-environnementales",
    "Nord-Pas-de-Calais": "https://www.hauts-de-france.developpement-durable.gouv.fr/spip.php?page=rubrique&id_rubrique=1468#pagination_articles",
}
