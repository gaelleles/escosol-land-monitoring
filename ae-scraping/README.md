# Scraping des Avis Environnementaux relatifs aux parcs photovoltaïques

Ce dossier contient les scripts Python permettant de scraper les différents sites des Autorités Environnementales et de récupérer l'ensemble des PDFs relatifs aux parcs photovoltaïques/solaires.

## `MRAE`

Ce sous-dossier contient les scripts permettant d'aller scraper les sites actuels des Autorités Environnementales.

## `archive`

Ce sous-dossier contient les modules permettant de scraper les sites des archives des autorités environnementales.
Chaque module contient une fonction permettant de récupérer un DataFrame contenant le lien de téléchargement de chaque PDF ainsi que des métadonnées associées à chaque PDF.

## data_processing

Ce dossier contient des modules pour extraire des informations depuis les PDFs ou leurs métadonnées comme la surface, la puissance...etc.

## Utilisation

Trois scripts permettent de lancer l'ensemble des opérations de scraping et de télécharger les PDFs et leurs métadonnées :

- `full_scraping.py` : Télécharge les avis depuis les sites actuels des MRAe ainsi que les sites archives (scraping complet) ;
- `mrae_scraping.py`: Idem mais uniquement les sites actuels de la MRAe ;
- `mrae_archive_pdf_downloader.py` : Idem mais uniquement les sites archives.

Exemple d'utilisation :

```bash
# Exécuter le scraping complet (récupération des métadonnées + téléchargement des PDFs) dans le dossier "output"
python full_scraping.py -o ./output

# Récupérer uniquement les métadonnées sans télécharger les PDFs
python full_scraping.py --metadata-only

# Télécharger les PDFs à partir d'un fichier de métadonnées existant (sans refaire le scraping)
python full_scraping.py --metadata-filepath archive_pdf_links.csv
```

Fichiers générés :

- `_pdfs_metadata_.csv` : Fichier CSV contenant les URLs et métadonnées des PDFs scrapés ;
- Dossier de PDFs : Les fichiers PDF sont téléchargés dans le dossier de sortie spécifié (ou répertoire courant par défaut).
