import argparse
import re
from pathlib import Path
import shutil

import duckdb
import httpx
import py7zr
from bs4 import BeautifulSoup, Tag
from httpx_retries import Retry, RetryTransport
from tqdm import tqdm


def donwload_links_filter(tag: Tag) -> bool:
    if not tag.name == "a":
        return False

    if not "href" in tag.attrs:
        return False

    if (
        tag["href"].startswith(
            "https://data.geopf.fr/telechargement/download/OCSGE-ARTIFICIALISATION/"
        )
        and not "DIFF" in tag["href"]
    ):
        return True

    return False


def download_all_departement_ecs_data_files(path: Path):
    page = httpx.get(
        "https://geoservices.ign.fr/artificialisation-ocs-ge#telechargement"
    )
    soup = BeautifulSoup(page.text, "html.parser")

    all_links = soup.find_all(donwload_links_filter)

    def process_link_text(link_text: str) -> tuple[str, str, int]:
        match_o = re.match(
            r"Département ([0-9A-Z]{2,3}) ?- ?(.+) ?- ?([0-9]{4})", link_text
        )

        if match_o is None:
            raise Exception("Problem in regex")

        departement_code = match_o.group(1)
        departement_name = match_o.group(2)
        year = int(match_o.group(3))

        return departement_code, departement_name, year

    link_list = []
    for link in all_links:
        url = link["href"]
        text = link.next_element.contents[0]

        departement_code, departement_name, year = process_link_text(text)

        link_list.append(
            {
                "departement_code": departement_code,
                "departement_name": departement_name.strip(),
                "url": url,
                "year": year,
            }
        )

    client = httpx.Client(
        transport=RetryTransport(retry=Retry(total=5, backoff_factor=0.5))
    )
    for data in tqdm(link_list, desc="Downloading OCS files"):
        path_to_download = path / f"{data['departement_name']}_{data['year']}.7z"

        if path_to_download.exists():
            tqdm.write(
                f"Skipping {data['departement_name']} - {data['year']} as it already exists"
            )
            continue

        with open(
            path / f"{data['departement_name']}_{data['year']}.7z", "wb"
        ) as out_file:
            with client.stream("GET", data["url"]) as response:
                total = int(response.headers["Content-Length"])

                with tqdm(
                    total=total,
                    unit_scale=True,
                    unit_divisor=1024,
                    unit="B",
                    desc=f"{data['departement_name']} - {data['year']}",
                    leave=False,
                ) as progress:
                    num_bytes_downloaded = response.num_bytes_downloaded
                    for chunk in response.iter_bytes():
                        out_file.write(chunk)
                        progress.update(
                            response.num_bytes_downloaded - num_bytes_downloaded
                        )
                        num_bytes_downloaded = response.num_bytes_downloaded


def unzip_all_ocs_files(path: Path):
    filter_pattern = re.compile(r"artif_.*\.gpkg")

    datasets_archives_path = path

    with tqdm(
        datasets_archives_path.glob("*.7z"), desc="Extracting 7z archives"
    ) as progress:
        for file in progress:
            progress.set_description(f"Extracting archive {file.stem}")
            with py7zr.SevenZipFile(file.absolute(), "r") as archive:
                allfiles = archive.getnames()
                selective_files = [f for f in allfiles if filter_pattern.search(f)]
                archive.extract(
                    path=datasets_archives_path,
                    targets=selective_files,
                )

            root_archive_file = Path(allfiles[0])

            path_to_delete = datasets_archives_path / root_archive_file
            if len(root_archive_file.parents) > 1:
                path_to_delete = datasets_archives_path / root_archive_file.parents[0]

            file_to_move = datasets_archives_path / Path(selective_files[0])

            file_to_move.rename(datasets_archives_path / f"{file_to_move.name}")

            shutil.rmtree(path_to_delete)


def populate_ocs_table(files_path: Path, database_path: Path):
    con = duckdb.connect(database_path)
    con.load_extension("SPATIAL")
    files_path = files_path.glob("*.gpkg")

    table_dml = """
    CREATE TABLE IF NOT EXISTS ocs
    (
        id VARCHAR,
        code_cs VARCHAR,
        code_us VARCHAR,
        millesime INTEGER,
        source VARCHAR,
        ossature INTEGER,
        id_origine VARCHAR,
        code_or VARCHAR,
        aire DOUBLE,
        artif VARCHAR,
        crit_seuil BOOLEAN,
        the_geom GEOMETRY,
        filename VARCHAR
    )
    """

    con.execute(table_dml)

    query = """
                INSERT INTO ocs
                SELECT 
                    *,
                    '{}' as file
                FROM '{}'
            """
    for file in tqdm(files_path, desc="Inserting data into duckdb."):
        con.execute(query.format(file.stem, file.absolute()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="ocs_dataset",
        description="This script allows to download all IGN OCS datasets, extracts them and create a duckdb table containing data from all files.",
    )

    subparsers = parser.add_subparsers(
        help="Downloads all the OCS datasets files from the webpage https://geoservices.ign.fr/ocsge#telechargement.",
        required=True,
        dest="action_f",
    )
    dl_subparser = subparsers.add_parser(
        "download",
        help="Downloads all files.",
    )
    dl_subparser.add_argument(
        "--path",
        help="Path of the folder where to donwload and extract the files.",
        default="./datasets",
    )

    dl_subparser = subparsers.add_parser(
        "extract", help="Extracts all OCS 7zip archives as gpkg files."
    )
    dl_subparser.add_argument(
        "--path",
        help="Path of the folder where are located download archive files",
        default="./datasets",
    )

    files_processing_subparser = subparsers.add_parser(
        "process_files", help="Inserts all data from all files in a duckdb table"
    )
    files_processing_subparser.add_argument(
        "--path",
        help="Path where are located all gpkg files",
        default="./datasets",
    )
    files_processing_subparser.add_argument(
        "--duckdb_path",
        help="Path where is located the duckdb database file, if not present, the file is created.",
        default="./escosol.duckdb",
    )

    args = parser.parse_args()
    path = Path(args.path)

    match args.action_f:
        case "download":
            download_all_departement_ecs_data_files(path)
        case "extract":
            unzip_all_ocs_files(path)
        case "process_files":
            duckdb_path = Path(args.duckdb_path)
            populate_ocs_table(files_path=path, database_path=duckdb_path)
