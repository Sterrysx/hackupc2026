from __future__ import annotations

from collections.abc import Iterable

import pandas as pd
import pyarrow as pa

COMPONENT_IDS: tuple[str, ...] = ("C1", "C2", "C3", "C4", "C5", "C6")
STATUS_CATEGORIES: tuple[str, ...] = ("OK", "WARNING", "CRITICAL", "FAILED")
CITY_CATEGORIES: tuple[str, ...] = (
    "Helsinki",
    "Stockholm",
    "Oslo",
    "Warsaw",
    "Prague",
    "Vienna",
    "London",
    "Amsterdam",
    "Paris",
    "Barcelona",
    "Madrid",
    "Rome",
    "Budapest",
    "Bucharest",
    "Athens",
)
CLIMATE_CATEGORIES: tuple[str, ...] = (
    "nordic",
    "continental",
    "oceanic",
    "mediterranean",
    "eastern",
)

_DICT = pa.dictionary(pa.int8(), pa.string())


def _field(name: str, typ: pa.DataType, *, nullable: bool = False) -> pa.Field:
    return pa.field(name, typ, nullable=nullable)


def _schema_fields(include_rul: bool) -> list[pa.Field]:
    fields: list[pa.Field] = [
        _field("printer_id", pa.int16()),
        _field("city", _DICT),
        _field("climate_zone", _DICT),
        _field("date", pa.date32()),
        _field("day", pa.int16()),
        _field("ambient_temp_c", pa.float32()),
        _field("humidity_pct", pa.float32()),
        _field("dust_concentration", pa.float32()),
        _field("Q_demand", pa.float32()),
        _field("daily_print_hours", pa.float32()),
        _field("cumulative_print_hours", pa.float32()),
    ]
    fields += [_field(f"H_{component_id}", pa.float32()) for component_id in COMPONENT_IDS]
    fields += [_field(f"status_{component_id}", _DICT) for component_id in COMPONENT_IDS]
    fields += [_field(f"tau_{component_id}", pa.float32()) for component_id in COMPONENT_IDS]
    fields += [_field(f"L_{component_id}", pa.float32()) for component_id in COMPONENT_IDS]
    fields += [
        _field("N_f", pa.int64()),
        _field("N_c", pa.int64()),
        _field("N_TC", pa.int64()),
        _field("N_on", pa.int64()),
    ]
    fields += [_field(f"lambda_{component_id}", pa.float32()) for component_id in COMPONENT_IDS]
    fields += [_field(f"maint_{component_id}", pa.bool_()) for component_id in COMPONENT_IDS]
    fields += [_field(f"failure_{component_id}", pa.bool_()) for component_id in COMPONENT_IDS]
    fields += [
        _field(f"hours_since_{component_id}_failure", pa.float32()) for component_id in COMPONENT_IDS
    ]
    if include_rul:
        fields += [_field(f"rul_{component_id}", pa.int32(), nullable=True) for component_id in COMPONENT_IDS]
        fields.append(_field("rul_system", pa.int32(), nullable=True))
    return fields


RAW_SCHEMA = pa.schema(_schema_fields(include_rul=False))
FINAL_SCHEMA = pa.schema(_schema_fields(include_rul=True))


def raw_column_names() -> list[str]:
    return RAW_SCHEMA.names


def final_column_names() -> list[str]:
    return FINAL_SCHEMA.names


def coerce_dataframe(df: pd.DataFrame, *, include_rul: bool) -> pd.DataFrame:
    """Return a DataFrame whose dtypes match the frozen Arrow schema."""
    expected = final_column_names() if include_rul else raw_column_names()
    df = df.copy()

    for column in expected:
        if column not in df.columns:
            if include_rul and (column.startswith("rul_") or column == "rul_system"):
                df[column] = pd.Series(pd.NA, index=df.index, dtype="Int32")
            else:
                raise ValueError(f"missing required column: {column}")

    df = df[expected]
    df["printer_id"] = df["printer_id"].astype("int16")
    df["city"] = pd.Categorical(df["city"], categories=CITY_CATEGORIES)
    df["climate_zone"] = pd.Categorical(df["climate_zone"], categories=CLIMATE_CATEGORIES)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["day"] = df["day"].astype("int16")

    for column in _float_columns():
        df[column] = df[column].astype("float32")
    for column in ("N_f", "N_c", "N_TC", "N_on"):
        df[column] = df[column].astype("int64")
    for component_id in COMPONENT_IDS:
        df[f"status_{component_id}"] = pd.Categorical(
            df[f"status_{component_id}"], categories=STATUS_CATEGORIES
        )
        df[f"maint_{component_id}"] = df[f"maint_{component_id}"].astype("bool")
        df[f"failure_{component_id}"] = df[f"failure_{component_id}"].astype("bool")
        if include_rul:
            df[f"rul_{component_id}"] = df[f"rul_{component_id}"].astype("Int32")
    if include_rul:
        df["rul_system"] = df["rul_system"].astype("Int32")

    return df


def table_from_dataframe(df: pd.DataFrame, *, include_rul: bool) -> pa.Table:
    schema = FINAL_SCHEMA if include_rul else RAW_SCHEMA
    coerced = coerce_dataframe(df, include_rul=include_rul)
    table = pa.Table.from_pandas(coerced, schema=schema, preserve_index=False)
    if not include_rul:
        table = table.replace_schema_metadata(None)
    table.validate(full=True)
    return table


def table_from_rows(rows: Iterable[dict], *, include_rul: bool = False) -> pa.Table:
    return table_from_dataframe(pd.DataFrame.from_records(rows), include_rul=include_rul)


def _float_columns() -> list[str]:
    columns = [
        "ambient_temp_c",
        "humidity_pct",
        "dust_concentration",
        "Q_demand",
        "daily_print_hours",
        "cumulative_print_hours",
    ]
    columns += [f"H_{component_id}" for component_id in COMPONENT_IDS]
    columns += [f"tau_{component_id}" for component_id in COMPONENT_IDS]
    columns += [f"L_{component_id}" for component_id in COMPONENT_IDS]
    columns += [f"lambda_{component_id}" for component_id in COMPONENT_IDS]
    columns += [f"hours_since_{component_id}_failure" for component_id in COMPONENT_IDS]
    return columns
