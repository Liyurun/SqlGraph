import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from sqlgraph.utils.batch import BatchResult, FailedCase, process_batch

def test_batch_result_success():
    result = BatchResult()
    result.add_success("file1.sql")
    result.add_success("file2.sql")
    assert result.success_count == 2
    assert result.failure_count == 0

def test_batch_result_failure():
    result = BatchResult()
    result.add_failure(FailedCase(file_path="bad.sql", error_message="syntax error", sql_content="SELECT FROM"))
    assert result.success_count == 0
    assert result.failure_count == 1

def test_batch_process_all_success():
    def processor(item):
        return item * 2
    items = [1, 2, 3]
    result = process_batch(items, processor, desc="Testing")
    assert result.success_count == 3
    assert result.failure_count == 0

def test_batch_process_partial_failure():
    def processor(item):
        if item == 2:
            raise ValueError("bad value")
        return item * 2
    items = [1, 2, 3]
    result = process_batch(items, processor, desc="Testing")
    assert result.success_count == 2
    assert result.failure_count == 1

def test_failed_cases_json_output():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = BatchResult()
        result.add_failure(FailedCase(file_path="bad.sql", error_message="parse error", sql_content="BAD SQL"))
        path = os.path.join(tmpdir, "failed_cases.json")
        result.write_failed_cases(path)
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["file_path"] == "bad.sql"
