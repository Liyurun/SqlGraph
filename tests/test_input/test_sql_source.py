import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from sqlgraph.input.sql_source import SqlSource


def test_from_string():
    source = SqlSource.from_string("SELECT 1 AS a", name="test")
    assert len(source) == 1
    assert source[0].name == "test"
    assert source[0].content == "SELECT 1 AS a"


def test_from_file():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.sql', delete=False) as f:
        f.write("SELECT * FROM t")
        f.flush()
        path = f.name
    try:
        source = SqlSource.from_file(path)
        assert len(source) == 1
        assert source[0].source_type == "file"
    finally:
        os.unlink(path)


def test_from_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(3):
            with open(os.path.join(tmpdir, f"test{i}.sql"), "w") as f:
                f.write(f"SELECT {i}")
        source = SqlSource.from_dir(tmpdir)
        assert len(source) == 3


def test_from_any_detects_string_as_sql():
    source = SqlSource.from_any("SELECT 1")
    assert len(source) == 1
    assert source[0].source_type == "string"


def test_from_df_csv_loads_table_name_code_format():
    content = (
        '"table_name","code"\n'
        '"target","set spark.sql.shuffle.partitions=10;\\n'
        'INSERT OVERWRITE TABLE target SELECT id FROM source;"\n'
        '"target_dup","set spark.sql.shuffle.partitions=10;\\n'
        'INSERT OVERWRITE TABLE target SELECT id FROM source;"\n'
        '"empty","null"\n'
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(content)
        f.flush()
        path = f.name
    try:
        source = SqlSource.from_df_csv(path)
        assert len(source) == 1
        assert source[0].name == "target"
        assert source[0].source_type == "df_csv"
        assert "set spark" not in source[0].content.lower()
        assert "INSERT OVERWRITE TABLE target" in source[0].content
        assert source[0].metadata["content_hash"]
        assert source[0].metadata["source_uri"] == "target.sql"
    finally:
        os.unlink(path)


def test_from_any_detects_df_csv():
    content = (
        '"table_name","code"\n'
        '"target","INSERT OVERWRITE TABLE target SELECT id FROM source;"\n'
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(content)
        f.flush()
        path = f.name
    try:
        source = SqlSource.from_any(path)
        assert len(source) == 1
        assert source[0].source_type == "df_csv"
    finally:
        os.unlink(path)
