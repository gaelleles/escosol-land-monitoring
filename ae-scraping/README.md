# Scraping des Avis Environnementaux relatifs aux parcs photovoltaïques

Ce dossier contient les scripts Python permettant de scraper les différents sites des Autorités Environnementales et de récupérer l'ensemble des PDFs relatifs aux parcs photovoltaïques/solaires.

## `dl-pdfs`

Ce sous-dossier contient les scripts permettant d'aller scraper les sites actuels des Autorités Environnementales à partir d'un fichier CSV listant les liens pour chaque Autorité Environnementale régionale.

## `archive`

Ce sous-dossier contient les modules permettant de scraper les sites des archives des autorités environnementales.
Chaque module contient une fonction permettant de récupérer un DataFrame contenant le lien de téléchargement de chaque PDF ainsi que des métadonnées associées à chaque PDF.

- SIDE (Site d'archive réunissant plusieurs régions/départments) : `get_side_archive_pdf_urls_and_metadata`
- Bretagne : `get_bretagne_archive_pdf_and_metadata`

Un script `mrae_archive_pdf_downloader` permet de lancer l'ensemble des opérations de scraping et de télécharger les PDFs.

Exemple d'utilisation :

```bash
# Exécuter le scraping complet (récupération des métadonnées + téléchargement des PDFs) dans le dossier "output"
python mrae_archive_pdf_downloader.py -o ./output

# Récupérer uniquement les métadonnées sans télécharger les PDFs
python mrae_archive_pdf_downloader.py --metadata-only

# Télécharger les PDFs à partir d'un fichier de métadonnées existant (sans refaire le scraping)
python mrae_archive_pdf_downloader.py --metadata-filepath archive_pdf_links.csv
```

Fichiers générés :

- `archive_pdf_links.csv` : Fichier CSV contenant les URLs et métadonnées des PDFs scrapés.
- Dossier de PDFs : Les fichiers PDF sont téléchargés dans le dossier de sortie spécifié (ou répertoire courant par défaut).
