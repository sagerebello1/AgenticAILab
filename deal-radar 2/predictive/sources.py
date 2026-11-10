"""Data-source adapters. A missing key raises. Nothing here fills in a number."""
import os


class SourceError(Exception):
    pass


def financial_modeling_prep():
    if not os.environ.get("FMP_API_KEY", "").strip():
        raise SourceError(
            "FMP_API_KEY is not set. Financial Modeling Prep was not called, and no fundamentals were filled in."
        )
    raise SourceError("The Financial Modeling Prep adapter is not implemented. No request was sent.")


def polygon():
    if not os.environ.get("POLYGON_API_KEY", "").strip():
        raise SourceError(
            "POLYGON_API_KEY is not set. Polygon was not called, and no prices were filled in."
        )
    raise SourceError("The Polygon adapter is not implemented. No request was sent.")


def historical_news():
    raise SourceError(
        "There is no historical headline archive. Today's Yahoo headlines were not requested, "
        "because they can mention an announcement that had not happened on the prediction date."
    )
