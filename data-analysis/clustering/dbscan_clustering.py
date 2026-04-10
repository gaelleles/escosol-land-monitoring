import argparse
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
import shapely
from geopy.distance import distance
from sklearn.cluster import DBSCAN


def get_centroid_coords(p: bytes) -> tuple[float, float]:
    p_centroid = shapely.from_wkb(p).centroid

    return (p_centroid.y, p_centroid.x)


def distance_func(row_1: np.array, row_2: np.array) -> float:
    d = distance((row_1[1], row_1[2]), (row_2[1], row_2[2])).km

    return d


def main(db_path: Path):
    engine = duckdb.connect(db_path, read_only=False)

    df_photo = engine.sql(
        """
        SELECT * from ign_photo
        """,
    ).pl()

    df_photo_with_centroid = df_photo.with_columns(
        pl.col("geom")
        .map_elements(get_centroid_coords, return_dtype=pl.Array(pl.Float64, 2))
        .alias("centroid")
    )

    estimator = DBSCAN(
        eps=1,  # 1km of distance max between the centroids of the geometries
        metric=distance_func,
        min_samples=2,
        n_jobs=-1,
    )

    X = df_photo_with_centroid.select(
        "id",
        pl.col("centroid").arr.get(0).alias("latitude"),
        pl.col("centroid").arr.get(1).alias("longitude"),
    ).to_pandas()
    labels = estimator.fit_predict(X)

    df_photo_with_centroid = df_photo_with_centroid.with_columns(
        pl.lit(labels).alias("labels")
    )

    engine.sql(
        "CREATE OR REPLACE TABLE ign_photo_cluster as (select * from df_photo_with_centroid)"
    )


if __name__ == "__main__":
    argument_parser = argparse.ArgumentParser(
        description="Takes a duckdb table containing 'IGN photovoltaïque' dataset and performs a clustering on it."
    )

    argument_parser.add_argument(
        "duckdb_path",
        help="Path to the duckdb db file containing the ign_photo table",
        type=Path,
    )

    args = argument_parser.parse_args()

    main(args.duckdb_path)
