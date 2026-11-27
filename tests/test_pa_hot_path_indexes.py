"""Hot-path composite indexes for member/office list queries."""

from app.prior_auth.models import PriorAuthRequest
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from tests.conftest import TEST_SCHEMA


def test_hot_path_indexes_in_metadata():
    index_cols = {
        index.name: list(index.columns.keys()) for index in PriorAuthRequest.__table__.indexes
    }
    assert index_cols["ix_pa_member_created"] == ["member_id", "created_at"]
    assert index_cols["ix_pa_practice_created"] == ["practice_id", "created_at"]


def test_hot_path_indexes_created_on_schema(engine: Engine):
    insp = inspect(engine)
    by_name = {
        idx["name"]: idx["column_names"]
        for idx in insp.get_indexes("prior_auth_requests", schema=TEST_SCHEMA)
    }
    assert by_name["ix_pa_member_created"] == ["member_id", "created_at"]
    assert by_name["ix_pa_practice_created"] == ["practice_id", "created_at"]


def test_alembic_chain_is_linear_single_head():
    # mutmut's mutants/ tree omits alembic/; skip the file assert there.
    import importlib.util
    from pathlib import Path

    versions = Path(__file__).resolve().parents[1] / "alembic/versions"
    if not versions.is_dir():
        return
    files = sorted(versions.glob("*.py"))
    assert files, "expected at least the baseline migration"
    by_rev: dict[str, object] = {}
    down_of: dict[str | None, list[str]] = {}
    for path in files:
        spec = importlib.util.spec_from_file_location(path.stem, path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rev = mod.revision
        down = mod.down_revision
        by_rev[rev] = mod
        down_of.setdefault(down, []).append(rev)
    roots = down_of.get(None, [])
    assert len(roots) == 1, roots
    baseline_path = next(p for p in files if p.stem.startswith("20261125_initial"))
    assert "ix_pa_member_created" in baseline_path.read_text()
    assert "ix_pa_practice_created" in baseline_path.read_text()
    # Exactly one head: every revision (except the tip) is a down_revision of exactly one child.
    pointed_at = {d for d in down_of if d is not None}
    heads = [rev for rev in by_rev if rev not in pointed_at]
    assert len(heads) == 1, heads
    for parent, children in down_of.items():
        if parent is None:
            continue
        assert len(children) == 1, (parent, children)
