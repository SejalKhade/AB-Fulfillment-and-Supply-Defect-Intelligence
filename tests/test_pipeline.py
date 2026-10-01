"""AB Defect Intelligence — Unit Tests"""
import sys
from pathlib import Path
import pytest
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.data_generator import generate
from modules.anomaly_detector import run_all as detect, by_node, by_carrier, by_category
from modules.root_cause import run_all as root_cause, pareto_analysis, weighted_impact


@pytest.fixture(scope="module")
def df():
    return generate(n_days=30, seed=42)


class TestDataGenerator:
    def test_returns_dataframe(self, df):
        assert isinstance(df, pd.DataFrame)

    def test_required_columns(self, df):
        for col in ["node", "carrier", "category", "total_shipments",
                    "total_defects", "defect_rate"]:
            assert col in df.columns

    def test_no_negative_shipments(self, df):
        assert (df["total_shipments"] >= 0).all()

    def test_no_negative_defects(self, df):
        assert (df["total_defects"] >= 0).all()

    def test_defect_rate_between_0_and_1(self, df):
        assert df["defect_rate"].between(0, 1).all()

    def test_defects_leq_shipments(self, df):
        assert (df["total_defects"] <= df["total_shipments"]).all()

    def test_seed_is_deterministic(self):
        a = generate(n_days=7, seed=99)
        b = generate(n_days=7, seed=99)
        assert a["total_defects"].sum() == b["total_defects"].sum()

    def test_different_seeds_differ(self):
        a = generate(n_days=7, seed=1)
        b = generate(n_days=7, seed=2)
        assert a["total_defects"].sum() != b["total_defects"].sum()


class TestAnomalyDetector:
    def test_by_node_has_status(self, df):
        result = by_node(df)
        assert "status" in result.columns
        assert set(result["status"]).issubset({"ESCALATE", "WATCH", "OK"})

    def test_by_node_sorted_desc(self, df):
        result = by_node(df)
        rates = result["defect_rate"].tolist()
        assert rates == sorted(rates, reverse=True)

    def test_by_carrier_has_zscore(self, df):
        result = by_carrier(df)
        assert "z_score" in result.columns

    def test_by_category_returns_all_categories(self, df):
        result = by_category(df)
        assert len(result) == df["category"].nunique()

    def test_run_all_keys(self, df):
        result = detect(df)
        for key in ["overall", "nodes", "carriers", "categories",
                    "weekday", "wow", "escalation_summary"]:
            assert key in result

    def test_overall_rate_formula(self, df):
        result = detect(df)
        o = result["overall"]
        expected = o["total_defects"] / o["total_shipments"]
        assert abs(o["overall_defect_rate"] - expected) < 1e-3

    def test_escalation_count_consistent(self, df):
        result = detect(df)
        n_esc = result["escalation_summary"]["n_escalate"]
        actual = (result["nodes"]["status"] == "ESCALATE").sum()
        assert n_esc == actual

    def test_wow_direction_valid(self, df):
        result = detect(df)
        assert result["wow"]["direction"] in ("UP", "DOWN", "STABLE")

    def test_anomaly_flag_uses_zscore(self, df):
        result = detect(df)
        nodes = result["nodes"]
        flagged = nodes[nodes["anomaly"] == True]
        assert (flagged["z_score"].abs() >= 2.0).all()


class TestRootCause:
    def test_pareto_cumulative_reaches_1(self, df):
        result = pareto_analysis(df)
        assert result["cumulative_pct"].iloc[-1] >= 0.99

    def test_pareto_sorted_desc(self, df):
        result = pareto_analysis(df)
        counts = result["count"].tolist()
        assert counts == sorted(counts, reverse=True)

    def test_pareto_80_flag(self, df):
        result = pareto_analysis(df)
        in_pareto = result[result["in_pareto_80"] == True]
        assert len(in_pareto) >= 1
        last_cum = in_pareto["cumulative_pct"].iloc[-1]
        assert last_cum <= 0.80 + 0.01

    def test_weighted_impact_has_rank(self, df):
        result = weighted_impact(df)
        assert "rank" in result.columns
        assert result["rank"].iloc[0] == 1

    def test_weighted_formula(self, df):
        result = weighted_impact(df)
        for _, row in result.iterrows():
            expected = row["raw_rate"] * row["weight"] * 100
            assert abs(row["impact_score"] - expected) < 1e-2

    def test_run_all_keys(self, df):
        result = root_cause(df)
        for key in ["pareto", "weighted_impact", "node_breakdown", "top_3_priorities"]:
            assert key in result

    def test_top3_has_3_entries(self, df):
        result = root_cause(df)
        assert len(result["top_3_priorities"]) == 3

    def test_action_present_for_each(self, df):
        result = root_cause(df)
        for p in result["top_3_priorities"]:
            assert "action" in p and len(p["action"]) > 10


class TestExcelReporter:
    def test_workbook_created(self, df, tmp_path):
        from modules.anomaly_detector import run_all as detect
        from modules.root_cause import run_all as rc
        from modules.excel_reporter import build_workbook
        anomalies = detect(df)
        root = rc(df)
        path = build_workbook(df, anomalies, root, output_path=tmp_path / "test.xlsx")
        assert path.exists()
        assert path.stat().st_size > 1000

    def test_workbook_has_correct_sheets(self, df, tmp_path):
        import openpyxl
        from modules.anomaly_detector import run_all as detect
        from modules.root_cause import run_all as rc
        from modules.excel_reporter import build_workbook
        anomalies = detect(df)
        root = rc(df)
        path = build_workbook(df, anomalies, root, output_path=tmp_path / "test2.xlsx")
        wb = openpyxl.load_workbook(path)
        expected = {"Weekly Summary", "Node Analysis", "Root Cause", "Carrier Report",
                    "Drill Down", "Escalation Memo", "Formula Pivot", "Data_Weekly", "Assumptions"}
        assert expected == set(wb.sheetnames)
