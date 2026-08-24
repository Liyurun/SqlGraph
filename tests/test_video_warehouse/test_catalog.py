from collections import Counter

from examples.video_commercial_warehouse.catalog import (
    ALL_TABLES,
    BASE_TABLES,
    TASKS,
    layer_counts,
    validate_catalog,
)


def test_catalog_exact_scale_and_unique_targets():
    assert len(BASE_TABLES) == 32
    assert len(TASKS) == 62
    assert len({task.target for task in TASKS}) == 62
    assert len(ALL_TABLES) == 94
    assert len(set(ALL_TABLES)) == 94


def test_catalog_layer_counts():
    assert layer_counts() == {
        "ODS": 18,
        "STG": 18,
        "DIM": 14,
        "DWD": 18,
        "DWS": 16,
        "ADS": 10,
    }


def test_catalog_covers_ten_business_domains():
    domains = {table.domain for table in BASE_TABLES.values()}
    domains |= {task.domain for task in TASKS}
    assert domains == {
        "content",
        "user",
        "traffic",
        "recommendation",
        "ad_inventory",
        "ad_delivery",
        "attribution",
        "billing",
        "experiment",
        "risk",
    }


def test_task_dag_is_acyclic_and_topologically_ordered():
    validate_catalog()
    positions = {task.target: index for index, task in enumerate(TASKS)}
    for task in TASKS:
        for dependency in task.dependencies:
            if dependency in positions:
                assert positions[dependency] < positions[task.target]


def test_each_derived_layer_has_expected_task_count():
    counts = Counter(task.layer for task in TASKS)
    assert counts == {"STG": 18, "DWD": 18, "DWS": 16, "ADS": 10}


def test_every_task_has_executable_create_table_sql():
    for task in TASKS:
        assert f"CREATE OR REPLACE TABLE {task.target} AS\n" in task.sql
        assert task.sql.rstrip().endswith(";")
        assert "SELECT" in task.sql.upper()
